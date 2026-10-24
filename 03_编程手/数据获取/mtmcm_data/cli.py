from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import APP_ROOT, Config, Source, load_config
from .http import FetchError, HttpClient, decode_body, utc_now
from .manifest import Manifest, ManifestEntry, new_run_id, summarise
from .parsers import article as article_parser
from .parsers import copernicus as copernicus_parser
from .parsers import nasa_power as nasa_parser
from .parsers import open_meteo as open_meteo_parser
from .parsers import tpdc as tpdc_parser
from .store import Store
from .ziputil import expand_zip_names


LOGGER = logging.getLogger("mtmcm_data")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger("mtmcm_data")
    root.setLevel(level)
    root.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)
    log_dir = APP_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "crawl.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)


def _common_client(config: Config, *, refresh: bool, offline: bool, insecure: bool) -> HttpClient:
    return HttpClient(
        cache_dir=APP_ROOT / "data" / "cache",
        user_agent=config.user_agent,
        defaults=config.defaults,
        logger=LOGGER,
        refresh=refresh,
        offline=offline,
        insecure=insecure,
    )


def _manifest_entry(
    run_id: str,
    source: Source,
    *,
    url: str,
    method: str,
    status: int | None,
    fetched_at: str,
    sha256: str = "",
    size: int = 0,
    content_type: str = "",
    raw_path: str = "",
    parser: str = "",
    from_cache: bool = False,
    elapsed_ms: int = 0,
    error: str = "",
) -> ManifestEntry:
    return ManifestEntry(
        run_id=run_id,
        source_id=source.id,
        source_name=source.name,
        kind=source.kind,
        url=url,
        method=method,
        status=status,
        fetched_at=fetched_at,
        sha256=sha256,
        bytes=size,
        content_type=content_type,
        raw_path=raw_path,
        parser=parser or source.parser,
        from_cache=from_cache,
        elapsed_ms=elapsed_ms,
        questions=list(source.questions),
        notes=source.notes,
        error=error,
    )


def _record_failure(
    manifest: Manifest,
    store: Store,
    run_id: str,
    source: Source,
    exc: FetchError,
) -> None:
    snippet = decode_body(exc.body[:4000], exc.headers or {}) if exc.body else ""
    error_doc = {
        "source_id": source.id,
        "source_name": source.name,
        "url": exc.url or source.url,
        "status": exc.status,
        "fetched_at": exc.fetched_at,
        "error": str(exc),
        "body_snippet": snippet,
        "notes": source.notes,
    }
    store.save_error(source.id, error_doc)
    manifest.append(
        _manifest_entry(
            run_id,
            source,
            url=exc.url or source.url,
            method="GET",
            status=exc.status,
            fetched_at=exc.fetched_at,
            error=str(exc),
        )
    )


def _save_raw_pair(
    store: Store,
    source: Source,
    detail_resp: Any,
    google_resp: Any,
) -> tuple[str, str]:
    detail_path = store.save_raw(source.id, detail_resp)
    google_path = store.save_raw(source.id, google_resp)
    return store.rel(detail_path), store.rel(google_path)


def fetch_tpdc(
    source: Source,
    client: HttpClient,
    store: Store,
    manifest: Manifest,
    run_id: str,
) -> dict[str, Any]:
    base = "https://www.tpdc.ac.cn"
    detail_url = base + "/view/metadataView/detail/"
    google_url = base + "/view/metadataView/getGoogleJson"

    detail_resp = client.fetch(
        source.id,
        detail_url,
        method="POST",
        json_body={"userId": "", "metadataId": source.metadata_id},
        cache_ttl=source.cache_ttl_sec,
        respect_robots=source.respect_robots,
        max_bytes=source.max_bytes,
        timeout=source.timeout_sec,
        retries=source.retries,
        min_interval_sec=source.min_interval_sec,
        headers=source.headers,
    )
    google_resp = client.fetch(
        source.id,
        google_url,
        params={"metadataId": source.metadata_id},
        cache_ttl=source.cache_ttl_sec,
        respect_robots=source.respect_robots,
        max_bytes=source.max_bytes,
        timeout=source.timeout_sec,
        retries=source.retries,
        min_interval_sec=source.min_interval_sec,
        headers=source.headers,
    )

    detail_raw, google_raw = _save_raw_pair(store, source, detail_resp, google_resp)
    detail_json = json.loads(detail_resp.text())
    google_json = json.loads(google_resp.text())
    if str(detail_json.get("code")) != "200":
        raise FetchError(
            f"TPDC detail 返回 code={detail_json.get('code')}: {detail_json.get('message')}",
            url=detail_url,
            status=detail_resp.status,
            body=detail_resp.body,
        )

    # TPDC 公开的 RIS 引用接口：给论文手一份可直接导入 Zotero/EndNote 的引用。
    ris_text = ""
    ris_path_rel = ""
    ris_resp = None
    try:
        ris_resp = client.fetch(
            source.id,
            base + "/view/metadataView/downloadNew",
            method="POST",
            json_body={"metadataId": source.metadata_id, "type": "1"},
            cache_ttl=source.cache_ttl_sec,
            respect_robots=source.respect_robots,
            max_bytes=source.max_bytes,
            timeout=source.timeout_sec,
            retries=source.retries,
            min_interval_sec=source.min_interval_sec,
            headers=source.headers,
        )
        ris_text = ris_resp.text()
        if "TY  - DATA" not in ris_text:
            raise FetchError("RIS 响应缺少 TY  - DATA", url=ris_resp.url, status=ris_resp.status, body=ris_resp.body)
        ris_path = store.save_text(f"meta/tpdc/{source.metadata_id}.ris", ris_text)
        ris_path_rel = store.rel(ris_path)
    except FetchError as exc:
        LOGGER.warning("  · RIS 引用获取失败（不阻塞元数据）: %s", exc)
        ris_resp = None

    meta = tpdc_parser.normalize(
        detail_json,
        google_json,
        source,
        local_mirror_path=source.local_mirror_path,
    )
    meta["citation_ris"] = ris_text
    meta["citation_ris_path"] = ris_path_rel
    meta["citation_ris_status"] = ris_resp.status if ris_resp is not None else None
    meta["fetched_at"] = detail_resp.fetched_at
    meta["http"] = {
        "detail_status": detail_resp.status,
        "google_status": google_resp.status,
        "detail_raw": detail_raw,
        "google_raw": google_raw,
        "detail_from_cache": detail_resp.from_cache,
        "google_from_cache": google_resp.from_cache,
    }
    store.save_json(f"meta/tpdc/{source.metadata_id}.json", meta)

    for response, url, raw_path, parser_name in (
        (detail_resp, detail_url, detail_raw, "tpdc.detail"),
        (google_resp, google_url, google_raw, "tpdc.google"),
    ):
        manifest.append(
            _manifest_entry(
                run_id,
                source,
                url=response.final_url or url,
                method="POST" if "detail" in parser_name else "GET",
                status=response.status,
                fetched_at=response.fetched_at,
                sha256=response.sha256,
                size=len(response.body),
                content_type=response.content_type,
                raw_path=raw_path,
                parser=parser_name,
                from_cache=response.from_cache,
                elapsed_ms=response.elapsed_ms,
            )
        )

    if ris_resp is not None and ris_path_rel:
        manifest.append(
            _manifest_entry(
                run_id,
                source,
                url=ris_resp.final_url or ris_resp.url,
                method="POST",
                status=ris_resp.status,
                fetched_at=ris_resp.fetched_at,
                sha256=ris_resp.sha256,
                size=len(ris_resp.body),
                content_type=ris_resp.content_type,
                raw_path=ris_path_rel,
                parser="tpdc.ris",
                from_cache=ris_resp.from_cache,
                elapsed_ms=ris_resp.elapsed_ms,
            )
        )

    LOGGER.info(
        "  ✓ %s | DOI=%s | 时间=%s→%s | 本地附件=%s",
        meta.get("title", "")[:60],
        meta.get("doi") or "无",
        (meta.get("time_coverage") or {}).get("start") or "未给",
        (meta.get("time_coverage") or {}).get("end") or "未给",
        "有" if (meta.get("local_mirror") or {}).get("exists") else "无",
    )
    return meta


def download_tpdc_files(
    source: Source,
    client: HttpClient,
    store: Store,
    manifest: Manifest,
    run_id: str,
    *,
    max_mb: float = 50.0,
    include_large: bool = False,
) -> dict[str, Any]:
    """下载 TPDC 数据文件。

    2026-10 的 TPDC 详情页提供“免登录下载”按钮，前端调用
    `POST /file/file/batchDownloadFile?metadataId=...`，body `{"noToken": true}`。
    这里复用同一公开接口，不伪造登录态、不绕过权限。
    """
    base = "https://www.tpdc.ac.cn"
    list_url = base + "/file/file/getRootFileDataList"
    list_resp = client.fetch(
        source.id,
        list_url,
        params={"metadataId": source.metadata_id},
        cache_ttl=3600,
        respect_robots=source.respect_robots,
        max_bytes=10_000_000,
        timeout=source.timeout_sec,
        retries=source.retries,
        min_interval_sec=source.min_interval_sec,
        headers=source.headers,
    )
    payload = json.loads(list_resp.text())
    if str(payload.get("code")) != "200":
        raise FetchError(
            f"文件列表返回 code={payload.get('code')}: {payload.get('message')}",
            url=list_url,
            status=list_resp.status,
            body=list_resp.body,
        )
    files = payload.get("data") or []
    total_size = sum(int(item.get("size") or 0) for item in files)
    file_meta: dict[str, Any] = {
        "source_id": source.id,
        "metadata_id": source.metadata_id,
        "files": [
            {
                "name": item.get("name"),
                "ext": item.get("ext"),
                "size": item.get("size"),
                "type": item.get("type"),
                "path": item.get("path"),
            }
            for item in files
            if isinstance(item, dict)
        ],
        "file_count": len(files),
        "total_size_bytes": total_size,
        "fetched_at": list_resp.fetched_at,
        "list_url": list_url,
        "download_status": "pending",
    }
    file_meta_path = store.save_json(f"meta/tpdc/{source.metadata_id}.files.json", file_meta)
    list_raw = store.save_raw(source.id, list_resp)
    manifest.append(
        _manifest_entry(
            run_id,
            source,
            url=list_resp.final_url or list_url,
            method="GET",
            status=list_resp.status,
            fetched_at=list_resp.fetched_at,
            sha256=list_resp.sha256,
            size=len(list_resp.body),
            content_type=list_resp.content_type,
            raw_path=store.rel(list_raw),
            parser="tpdc.filelist",
            from_cache=list_resp.from_cache,
        )
    )
    if not files:
        raise FetchError("TPDC 文件列表为空", url=list_url, status=list_resp.status)

    if total_size > max_mb * 1_000_000 and not include_large:
        file_meta["download_status"] = "skipped_large"
        file_meta["skip_reason"] = f"总大小 {total_size / 1e6:.1f} MB > max_mb={max_mb}；如需下载用 --include-large"
        store.save_json(f"meta/tpdc/{source.metadata_id}.files.json", file_meta)
        LOGGER.info(
            "  - %s | %s 个文件 %.1f MB，超过 %.0f MB，跳过（--include-large 可下载）",
            source.id,
            len(files),
            total_size / 1e6,
            max_mb,
        )
        return file_meta

    zip_url = base + "/file/file/batchDownloadFile"
    zip_resp = client.fetch(
        source.id,
        zip_url,
        method="POST",
        params={"metadataId": source.metadata_id},
        json_body={"noToken": True},
        cache=False,
        respect_robots=source.respect_robots,
        max_bytes=max(total_size * 2 + 10_000_000, 20_000_000),
        timeout=180,
        retries=1,
        min_interval_sec=source.min_interval_sec,
        headers=source.headers,
    )
    if not zip_resp.body.startswith(b"PK"):
        raise FetchError("下载响应不是 ZIP", url=zip_url, status=zip_resp.status, body=zip_resp.body[:200])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_path = store.save_bytes(f"tpdc_files/{source.id}/{stamp}.zip", zip_resp.body)
    try:
        with zipfile.ZipFile(io.BytesIO(zip_resp.body)) as archive:
            bad = archive.testzip()
            members = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise FetchError(f"ZIP 校验失败: {exc}", url=zip_url, status=zip_resp.status) from exc
    if bad:
        raise FetchError(f"ZIP 内文件损坏: {bad}", url=zip_url, status=zip_resp.status)

    file_meta.update(
        {
            "download_status": "ok",
            "zip_path": store.rel(zip_path),
            "zip_bytes": len(zip_resp.body),
            "zip_members": len(members),
            "member_names": members[:100],
            "downloaded_at": zip_resp.fetched_at,
        }
    )
    local_zip = source.local_mirror_path
    if local_zip is not None and local_zip.exists() and local_zip.suffix.lower() == ".zip":
        try:
            local_names, _ = expand_zip_names(local_zip)
            downloaded_names, nested = expand_zip_names(zip_resp.body)
            file_meta["local_zip_members"] = len(local_names)
            file_meta["downloaded_members_expanded"] = len(downloaded_names)
            file_meta["nested_archives"] = nested
            file_meta["missing_vs_local"] = sorted(local_names - downloaded_names)
            file_meta["extra_vs_local"] = sorted(downloaded_names - local_names)
            if not file_meta["missing_vs_local"] and not file_meta["extra_vs_local"]:
                file_meta["comparison_status"] = "same_nested" if nested else "same"
            else:
                file_meta["comparison_status"] = "different"
        except Exception as exc:  # noqa: BLE001 - 本地附件损坏不应阻塞下载结果
            file_meta["local_zip_compare_error"] = str(exc)
    store.save_json(f"meta/tpdc/{source.metadata_id}.files.json", file_meta)
    manifest.append(
        _manifest_entry(
            run_id,
            source,
            url=zip_resp.final_url or zip_url,
            method="POST",
            status=zip_resp.status,
            fetched_at=zip_resp.fetched_at,
            sha256=zip_resp.sha256,
            size=len(zip_resp.body),
            content_type=zip_resp.content_type,
            raw_path=store.rel(zip_path),
            parser="tpdc.zip",
        )
    )
    LOGGER.info(
        "  ✓ %s | %s 个文件 %.1f MB → ZIP %.1f MB | %s",
        source.id,
        len(files),
        total_size / 1e6,
        len(zip_resp.body) / 1e6,
        store.rel(zip_path),
    )
    return file_meta


def fetch_article(
    source: Source,
    client: HttpClient,
    store: Store,
    manifest: Manifest,
    run_id: str,
) -> dict[str, Any]:
    # 先看有没有人工保存的快照：百度百科这类反爬站点，合规做法是人工保存
    # 一份公开页面快照，再离线解析，而不是在爬虫里伪造 cookie / 绕过验证码。
    manual = source.manual_snapshot_path
    if manual is not None and manual.exists():
        raw = manual.read_bytes()
        meta = article_parser.parse(raw.decode("utf-8", errors="replace"), source)
        fetched_at = utc_now()
        meta.update(
            {
                "fetched_at": fetched_at,
                "http_status": 200,
                "source_mode": "manual_snapshot",
                "raw_path": store.rel(manual),
                "manual_note": "人工保存的公开页面快照；不经过反爬绕过。",
            }
        )
        store.save_json(f"meta/articles/{source.id}.json", meta)
        manifest.append(
            _manifest_entry(
                run_id,
                source,
                url=source.url,
                method="MANUAL",
                status=200,
                fetched_at=fetched_at,
                sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),
                content_type="text/html",
                raw_path=store.rel(manual),
                parser="article.manual",
            )
        )
        LOGGER.info("  ✓ %s | 人工快照 | %s 字", meta.get("title", "")[:60], meta.get("char_count"))
        return meta

    response = client.fetch(
        source.id,
        source.url,
        cache_ttl=source.cache_ttl_sec,
        respect_robots=source.respect_robots,
        max_bytes=source.max_bytes,
        timeout=source.timeout_sec,
        retries=source.retries,
        min_interval_sec=source.min_interval_sec,
        headers=source.headers,
    )
    raw_path = store.save_raw(source.id, response)
    meta = article_parser.parse(response.text(), source)
    meta.update(
        {
            "fetched_at": response.fetched_at,
            "http_status": response.status,
            "raw_path": store.rel(raw_path),
        }
    )
    store.save_json(f"meta/articles/{source.id}.json", meta)
    manifest.append(
        _manifest_entry(
            run_id,
            source,
            url=response.final_url or source.url,
            method="GET",
            status=response.status,
            fetched_at=response.fetched_at,
            sha256=response.sha256,
            size=len(response.body),
            content_type=response.content_type,
            raw_path=store.rel(raw_path),
            parser="article",
            from_cache=response.from_cache,
            elapsed_ms=response.elapsed_ms,
        )
    )
    LOGGER.info("  ✓ %s | %s 字 | 发布=%s", meta.get("title", "")[:60], meta.get("char_count"), meta.get("published_at") or "未给")
    return meta


def fetch_api(
    source: Source,
    client: HttpClient,
    store: Store,
    manifest: Manifest,
    run_id: str,
) -> dict[str, Any]:
    response = client.fetch(
        source.id,
        source.url,
        method=source.method,
        params=source.params,
        cache_ttl=source.cache_ttl_sec,
        respect_robots=source.respect_robots,
        max_bytes=source.max_bytes,
        timeout=source.timeout_sec,
        retries=source.retries,
        min_interval_sec=source.min_interval_sec,
        headers=source.headers,
    )
    raw_path = store.save_raw(source.id, response)
    payload = json.loads(response.text())

    if source.parser == "open_meteo":
        meta, rows = open_meteo_parser.parse(payload, source)
    elif source.parser == "nasa_power":
        meta, rows = nasa_parser.parse(payload, source)
    elif source.parser == "copernicus":
        meta, rows = copernicus_parser.parse(payload, source)
    else:
        raise ValueError(f"未知 api parser: {source.parser}")

    meta.update(
        {
            "fetched_at": response.fetched_at,
            "http_status": response.status,
            "raw_path": store.rel(raw_path),
        }
    )
    store.save_json(f"meta/api/{source.id}.json", meta)
    if rows:
        store.save_table(source.id, rows)
    manifest.append(
        _manifest_entry(
            run_id,
            source,
            url=response.final_url or source.url,
            method=source.method,
            status=response.status,
            fetched_at=response.fetched_at,
            sha256=response.sha256,
            size=len(response.body),
            content_type=response.content_type,
            raw_path=store.rel(raw_path),
            parser=source.parser,
            from_cache=response.from_cache,
            elapsed_ms=response.elapsed_ms,
        )
    )
    LOGGER.info(
        "  ✓ %s | %s 行 | %s→%s",
        source.id,
        meta.get("row_count", len(rows)),
        meta.get("time_start") or "未给",
        meta.get("time_end") or "未给",
    )
    return meta


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config()
    print(f"{'ID':<26} {'类型':<14} {'问题':<10} {'启用':<5} 名称")
    print("-" * 110)
    for source in config.sources:
        print(
            f"{source.id:<26} {source.kind:<14} {','.join(source.questions) or '-':<10} "
            f"{'是' if source.enabled else '否':<5} {source.name}"
        )
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    client = _common_client(config, refresh=args.refresh, offline=args.offline, insecure=args.insecure)

    try:
        ids = args.sources or None
        if ids == ["all"]:
            ids = None
        sources = config.select(ids, include_disabled=args.include_disabled)
    except KeyError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2
    if args.exclude:
        excluded = set(args.exclude)
        sources = [s for s in sources if s.id not in excluded]

    run_id = new_run_id()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict[str, Any]] = []
    LOGGER.info("run %s | %s 个来源", run_id, len(sources))

    for index, source in enumerate(sources, 1):
        LOGGER.info("[%s/%s] %s", index, len(sources), source.id)
        started_source = time.monotonic()
        try:
            if source.kind == "tpdc_dataset":
                meta = fetch_tpdc(source, client, store, manifest, run_id)
            elif source.kind == "article":
                meta = fetch_article(source, client, store, manifest, run_id)
            elif source.kind == "api_json":
                meta = fetch_api(source, client, store, manifest, run_id)
            else:
                raise ValueError(f"未知 kind: {source.kind}")
            records.append(
                {
                    "source_id": source.id,
                    "status": "ok",
                    "elapsed_ms": int((time.monotonic() - started_source) * 1000),
                    "meta_keys": sorted(meta.keys()),
                }
            )
        except FetchError as exc:
            LOGGER.warning("  ✗ %s | %s", source.id, exc)
            _record_failure(manifest, store, run_id, source, exc)
            records.append(
                {
                    "source_id": source.id,
                    "status": "blocked" if source.allow_blocked else "failed",
                    "error": str(exc),
                    "http_status": exc.status,
                }
            )
            if args.fail_fast and not source.allow_blocked:
                break
        except Exception as exc:  # noqa: BLE001 - CLI 需要把单个来源的异常隔离
            LOGGER.error("  ✗ %s | %s", source.id, exc)
            LOGGER.debug("traceback", exc_info=True)
            _record_failure(
                manifest,
                store,
                run_id,
                source,
                FetchError(str(exc), url=source.url),
            )
            records.append({"source_id": source.id, "status": "failed", "error": str(exc)})
            if args.fail_fast:
                break

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "source_count": len(sources),
        "records": records,
        "manifest_entries": len(manifest.entries_for_run(run_id)),
    }
    store.save_run(run_id, summary)

    ok = sum(1 for r in records if r["status"] == "ok")
    blocked = sum(1 for r in records if r["status"] == "blocked")
    failed = sum(1 for r in records if r["status"] == "failed")
    print()
    print(f"完成：ok={ok} blocked={blocked} failed={failed} | run_id={run_id}")
    print(f"清单：{store.rel(manifest.path)}")
    print(f"元数据：{store.rel(store.meta_dir)}")
    print(f"数据表：{store.rel(store.table_dir)}")
    if failed:
        print("有失败来源，详见 data/meta/errors/ 与日志 logs/crawl.log", file=sys.stderr)
        return 1
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    client = _common_client(config, refresh=False, offline=False, insecure=args.insecure)

    try:
        ids = args.sources or None
        if ids == ["all"]:
            ids = None
        sources = config.select(ids, include_disabled=args.include_disabled)
    except KeyError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2
    if args.exclude:
        excluded = set(args.exclude)
        sources = [s for s in sources if s.id not in excluded]

    run_id = new_run_id()
    records: list[dict[str, Any]] = []
    LOGGER.info("download run %s | max_mb=%.0f include_large=%s", run_id, args.max_mb, args.include_large)
    for source in sources:
        if source.kind != "tpdc_dataset":
            LOGGER.info("  - %s 不是 TPDC 数据集，跳过下载", source.id)
            continue
        try:
            meta = download_tpdc_files(
                source,
                client,
                store,
                manifest,
                run_id,
                max_mb=args.max_mb,
                include_large=args.include_large,
            )
            records.append(
                {
                    "source_id": source.id,
                    "status": meta.get("download_status"),
                    "file_count": meta.get("file_count"),
                    "total_size_bytes": meta.get("total_size_bytes"),
                    "zip_path": meta.get("zip_path"),
                }
            )
        except FetchError as exc:
            LOGGER.warning("  ✗ %s | %s", source.id, exc)
            _record_failure(manifest, store, run_id, source, exc)
            records.append({"source_id": source.id, "status": "failed", "error": str(exc)})
            if args.fail_fast:
                break
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("  ✗ %s | %s", source.id, exc)
            _record_failure(manifest, store, run_id, source, FetchError(str(exc), url=source.url))
            records.append({"source_id": source.id, "status": "failed", "error": str(exc)})
            if args.fail_fast:
                break

    store.save_run(
        run_id,
        {
            "run_id": run_id,
            "kind": "download",
            "records": records,
            "manifest_entries": len(manifest.entries_for_run(run_id)),
        },
    )
    ok = sum(1 for r in records if r["status"] == "ok")
    skipped = sum(1 for r in records if r["status"] == "skipped_large")
    failed = sum(1 for r in records if r["status"] == "failed")
    print(f"下载完成：ok={ok} skipped_large={skipped} failed={failed} | run_id={run_id}")
    return 1 if failed else 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import build_report

    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    md_path, csv_path = build_report(config, store, manifest)
    print(f"报告：{store.rel(md_path)}")
    print(f"表格：{store.rel(csv_path)}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .audit import build_event_audit

    store = Store()
    path = build_event_audit(store)
    print(f"事件窗口核对：{store.rel(path)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .validate import build_validation_report

    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    md_path, csv_path, checks = build_validation_report(config, store, manifest)
    failed = sum(1 for c in checks if c.status == "FAIL")
    warned = sum(1 for c in checks if c.status == "WARN")
    blocked = sum(1 for c in checks if c.status == "BLOCKED")
    print(f"核验报告：{store.rel(md_path)}")
    print(f"核验表格：{store.rel(csv_path)}")
    print(f"FAIL={failed} WARN={warned} BLOCKED={blocked}")
    return 1 if failed else 0


def cmd_governance(args: argparse.Namespace) -> int:
    from .governance import build_governance_report

    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    md_path, csv_path, card_dir, governance = build_governance_report(config, store, manifest)
    print(f"数据治理报告：{store.rel(md_path)}")
    print(f"治理表格：{store.rel(csv_path)}")
    print(f"数据卡：{store.rel(card_dir)}（{len(governance)} 个来源）")
    return 0


def cmd_existing(args: argparse.Namespace) -> int:
    from .existing_audit import build_existing_audit

    store = Store()
    md_path, csv_path, rows = build_existing_audit(store)
    print(f"已有数据审计：{store.rel(md_path)}")
    print(f"已有数据表格：{store.rel(csv_path)}")
    print(f"数据集：{len(rows)} 个")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    from .process import build_processed

    store = Store()
    manifest = build_processed(store, batch=args.batch)
    print(f"processed 批次：{manifest.get('batch')}")
    print(f"数据集：{', '.join(manifest.get('datasets') or [])}")
    print(f"输出目录：{store.rel(store.data_dir / 'processed')}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    latest = manifest.latest_by_source()
    problems: list[str] = []
    checked = 0
    for source in config.sources:
        entry = latest.get(source.id)
        if not entry:
            print(f"[MISS] {source.id}: 无抓取记录")
            problems.append(source.id)
            continue
        if entry.get("error"):
            if source.allow_blocked:
                print(f"[BLOCK] {source.id}: {entry['error']}（该来源已标记为允许受限）")
            else:
                print(f"[FAIL] {source.id}: {entry['error']}")
                problems.append(source.id)
            continue
        raw_path = entry.get("raw_path")
        if raw_path:
            path = APP_ROOT / raw_path
            checked += 1
            if not path.exists():
                print(f"[MISS] {source.id}: raw 文件不存在 {raw_path}")
                problems.append(source.id)
            elif entry.get("sha256"):
                import hashlib

                h = hashlib.sha256(path.read_bytes()).hexdigest()
                if h != entry["sha256"]:
                    print(f"[HASH] {source.id}: sha256 不一致")
                    problems.append(source.id)
                else:
                    print(f"[ OK ] {source.id}: {raw_path}")
        if source.local_mirror_path:
            mirror = source.local_mirror_path
            if not mirror.exists():
                print(f"[MISS] {source.id}: 本地附件不存在 {mirror}")
                problems.append(source.id)
            else:
                print(f"[ OK ] {source.id}: 本地附件 {mirror.stat().st_size} B")
    print()
    print(f"核验完成：{checked} 个 raw 文件，{len(problems)} 个问题")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mtmcm_data",
        description="MTMCM B 题数据获取工具：TPDC 元数据、背景文章、Open-Meteo/NASA/Copernicus 补充数据。",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出所有配置来源")
    p_list.set_defaults(func=cmd_list)

    p_fetch = sub.add_parser("fetch", help="抓取一个或多个来源")
    p_fetch.add_argument("sources", nargs="*", help="来源 ID；留空表示全部启用的来源")
    p_fetch.add_argument("--exclude", nargs="*", default=[], help="排除的来源 ID")
    p_fetch.add_argument("--refresh", action="store_true", help="忽略缓存，强制重新抓取")
    p_fetch.add_argument("--offline", action="store_true", help="只用缓存，不访问网络")
    p_fetch.add_argument("--insecure", action="store_true", help="跳过 TLS 校验（仅网络受限时临时使用）")
    p_fetch.add_argument("--fail-fast", action="store_true", help="遇到失败立即停止")
    p_fetch.add_argument("--include-disabled", action="store_true", help="包含 enabled=false 的来源")
    p_fetch.set_defaults(func=cmd_fetch)

    p_report = sub.add_parser("report", help="生成来源审计报告（Markdown + CSV）")
    p_report.set_defaults(func=cmd_report)

    p_download = sub.add_parser("download", help="下载 TPDC 数据文件（免登录公开接口）")
    p_download.add_argument("sources", nargs="*", help="来源 ID；留空/all 表示全部 TPDC 数据集")
    p_download.add_argument("--max-mb", type=float, default=50.0, help="单数据集总大小上限（MB），默认 50")
    p_download.add_argument("--include-large", action="store_true", help="允许下载超过 --max-mb 的数据集")
    p_download.add_argument("--exclude", nargs="*", default=[], help="排除的来源 ID")
    p_download.add_argument("--include-disabled", action="store_true", help="包含 enabled=false 的来源")
    p_download.add_argument("--insecure", action="store_true", help="跳过 TLS 校验（仅临时使用）")
    p_download.add_argument("--fail-fast", action="store_true", help="遇到失败立即停止")
    p_download.set_defaults(func=cmd_download)

    p_audit = sub.add_parser("audit", help="核对事件前 72 小时站点/再分析降水")
    p_audit.set_defaults(func=cmd_audit)

    p_validate = sub.add_parser("validate", help="按来源逐项核验抓取质量")
    p_validate.set_defaults(func=cmd_validate)

    p_governance = sub.add_parser("governance", help="生成多源数据治理报告与数据卡")
    p_governance.set_defaults(func=cmd_governance)

    p_existing = sub.add_parser("existing", help="审计赛题已有 8 组附件的格式/时间/空间/质量")
    p_existing.set_defaults(func=cmd_existing)

    p_process = sub.add_parser("process", help="生成 data/processed 基线（batch 1-7/all）")
    p_process.add_argument("--batch", default="1", choices=["1", "2", "3", "4", "5", "6", "7", "all"], help="批次；默认 1")
    p_process.set_defaults(func=cmd_process)

    p_verify = sub.add_parser("verify", help="核验 manifest、raw 文件和本地附件")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("未处理异常: %s", exc)
        traceback.print_exc()
        return 1
