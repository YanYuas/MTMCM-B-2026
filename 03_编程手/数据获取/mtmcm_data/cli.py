from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import APP_ROOT, Config, Source, load_config
from .http import FetchError, HttpClient, decode_body
from .manifest import Manifest, ManifestEntry, new_run_id, summarise
from .parsers import article as article_parser
from .parsers import copernicus as copernicus_parser
from .parsers import nasa_power as nasa_parser
from .parsers import open_meteo as open_meteo_parser
from .parsers import tpdc as tpdc_parser
from .store import Store


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

    meta = tpdc_parser.normalize(
        detail_json,
        google_json,
        source,
        local_mirror_path=source.local_mirror_path,
    )
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

    LOGGER.info(
        "  ✓ %s | DOI=%s | 时间=%s→%s | 本地附件=%s",
        meta.get("title", "")[:60],
        meta.get("doi") or "无",
        (meta.get("time_coverage") or {}).get("start") or "未给",
        (meta.get("time_coverage") or {}).get("end") or "未给",
        "有" if (meta.get("local_mirror") or {}).get("exists") else "无",
    )
    return meta


def fetch_article(
    source: Source,
    client: HttpClient,
    store: Store,
    manifest: Manifest,
    run_id: str,
) -> dict[str, Any]:
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


def cmd_report(args: argparse.Namespace) -> int:
    from .report import build_report

    config = load_config()
    store = Store()
    manifest = Manifest(store.data_dir / "manifest.jsonl")
    md_path, csv_path = build_report(config, store, manifest)
    print(f"报告：{store.rel(md_path)}")
    print(f"表格：{store.rel(csv_path)}")
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
