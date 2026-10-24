from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .config import Config, Source
from .manifest import Manifest
from .store import Store


@dataclass
class Check:
    source_id: str
    check: str
    status: str  # OK / WARN / FAIL / BLOCKED
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _meta_for(store: Store, source: Source) -> dict[str, Any] | None:
    if source.kind == "tpdc_dataset":
        path = store.data_dir / "meta" / "tpdc" / f"{source.metadata_id}.json"
    elif source.kind == "article":
        path = store.data_dir / "meta" / "articles" / f"{source.id}.json"
    elif source.kind == "api_json":
        path = store.data_dir / "meta" / "api" / f"{source.id}.json"
    else:
        return None
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _check(checks: list[Check], source: Source, name: str, ok: bool, detail: str = "", *, warn: bool = False) -> None:
    if ok:
        checks.append(Check(source.id, name, "OK", detail))
    else:
        checks.append(Check(source.id, name, "WARN" if warn else "FAIL", detail))


def _validate_tpdc(source: Source, meta: dict[str, Any], checks: list[Check], store: Store) -> None:
    _check(checks, source, "元数据文件", bool(meta))
    if not meta:
        return
    _check(checks, source, "标题", bool(meta.get("title")), str(meta.get("title", ""))[:80])
    _check(checks, source, "metadata_id", meta.get("metadata_id") == source.metadata_id)
    _check(checks, source, "landing_url", bool(meta.get("landing_url")))
    _check(checks, source, "citation_cn", bool(meta.get("citation_cn")), str(meta.get("citation_cn", ""))[:100])
    mirror = meta.get("local_mirror") or {}
    _check(checks, source, "本地附件", bool(mirror.get("exists")), str(mirror.get("path", "")))
    bbox = (meta.get("spatial_coverage") or {}).get("bbox")
    _check(checks, source, "空间范围", bool(bbox), str(bbox or "元数据未给出"), warn=True)
    tc = meta.get("time_coverage") or {}
    has_time = bool(tc.get("start") or tc.get("end") or tc.get("title_hint"))
    _check(checks, source, "时间范围", has_time, str(tc.get("start") or tc.get("title_hint") or "未给"), warn=True)
    _check(checks, source, "描述长度", len(meta.get("description") or "") >= 50, f"{len(meta.get('description') or '')} 字", warn=True)
    _check(checks, source, "关键词", bool(meta.get("keywords")), f"{len(meta.get('keywords') or [])} 个", warn=True)
    ris = meta.get("citation_ris") or ""
    _check(checks, source, "RIS 引用", "TY  - DATA" in ris, f"{len(ris)} 字符", warn=True)

    files_path = store.data_dir / "meta" / "tpdc" / f"{source.metadata_id}.files.json"
    if not files_path.exists():
        checks.append(Check(source.id, "数据文件下载", "WARN", "尚未运行 download"))
        return
    try:
        files_meta = json.loads(files_path.read_text(encoding="utf-8"))
    except Exception as exc:
        checks.append(Check(source.id, "数据文件下载", "WARN", f"files.json 读取失败: {exc}"))
        return
    status = files_meta.get("download_status")
    if status == "ok":
        checks.append(
            Check(
                source.id,
                "数据文件下载",
                "OK",
                f"{files_meta.get('zip_members')} 个文件，{files_meta.get('zip_bytes', 0) / 1e6:.1f} MB ZIP",
            )
        )
    elif status == "skipped_large":
        checks.append(Check(source.id, "数据文件下载", "WARN", files_meta.get("skip_reason") or "超过大小上限，未下载"))
    else:
        checks.append(Check(source.id, "数据文件下载", "WARN", f"状态: {status}"))
    missing = files_meta.get("missing_vs_local") or []
    if missing:
        checks.append(
            Check(
                source.id,
                "下载与本地附件差异",
                "WARN",
                f"下载 ZIP 缺 {len(missing)} 个本地文件: {', '.join(missing[:5])}",
            )
        )
    elif files_meta.get("comparison_status") == "same_nested":
        checks.append(Check(source.id, "下载与本地附件差异", "OK", "嵌套 ZIP，展开后与本地附件一致"))
    elif files_meta.get("comparison_status") == "same":
        checks.append(Check(source.id, "下载与本地附件差异", "OK", "与本地附件一致"))


def _validate_article(source: Source, meta: dict[str, Any], checks: list[Check]) -> None:
    _check(checks, source, "正文元数据", bool(meta))
    if not meta:
        return
    _check(checks, source, "标题", bool(meta.get("title")), str(meta.get("title", ""))[:80])
    char_count = int(meta.get("char_count") or 0)
    _check(checks, source, "正文长度", char_count >= 300, f"{char_count} 字", warn=True)
    _check(checks, source, "正文 hash", bool(meta.get("text_sha256")))
    mode = meta.get("source_mode") or "http"
    _check(checks, source, "获取方式", True, mode)


def _validate_api(source: Source, meta: dict[str, Any], checks: list[Check]) -> None:
    _check(checks, source, "API 元数据", bool(meta))
    if not meta:
        return
    row_count = int(meta.get("row_count") or 0)
    _check(checks, source, "数据行数", row_count > 0, f"{row_count} 行")
    _check(checks, source, "时间起止", bool(meta.get("time_start") and meta.get("time_end")), f"{meta.get('time_start')} → {meta.get('time_end')}")
    if source.parser == "copernicus":
        core = int(meta.get("core_overlap_count") or 0)
        _check(checks, source, "研究区相交", core > 0, f"{core} 个产品与 study_area 相交", warn=True)
        _check(checks, source, "产品类型", bool(meta.get("product_types")), str(meta.get("product_types")))
    else:
        variables = meta.get("variables") or []
        _check(checks, source, "变量数", len(variables) >= 3, f"{len(variables)} 个", warn=True)


def validate_all(config: Config, store: Store, manifest: Manifest) -> list[Check]:
    latest = manifest.latest_by_source()
    checks: list[Check] = []
    for source in config.sources:
        entry = latest.get(source.id)
        if not entry:
            checks.append(Check(source.id, "抓取记录", "FAIL", "manifest 中没有记录"))
            continue
        if entry.get("error"):
            status = "BLOCKED" if source.allow_blocked else "FAIL"
            checks.append(Check(source.id, "抓取", status, str(entry.get("error"))))
            continue
        checks.append(Check(source.id, "抓取", "OK", f"HTTP {entry.get('status')}，{entry.get('fetched_at')}"))
        meta = _meta_for(store, source)
        if source.kind == "tpdc_dataset":
            _validate_tpdc(source, meta or {}, checks, store)
        elif source.kind == "article":
            _validate_article(source, meta or {}, checks)
        elif source.kind == "api_json":
            _validate_api(source, meta or {}, checks)
    return checks


def _worst(checks: list[Check], source_id: str) -> str:
    order = {"FAIL": 0, "BLOCKED": 1, "WARN": 2, "OK": 3}
    values = [c.status for c in checks if c.source_id == source_id]
    if not values:
        return "FAIL"
    return min(values, key=lambda s: order.get(s, 99))


def build_validation_report(config: Config, store: Store, manifest: Manifest) -> tuple[Path, Path, list[Check]]:
    checks = validate_all(config, store, manifest)
    report_dir = store.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / "validation.md"
    csv_path = report_dir / "validation.csv"

    counts = {s: sum(1 for c in checks if c.status == s) for s in ("OK", "WARN", "FAIL", "BLOCKED")}
    overall = "通过" if counts["FAIL"] == 0 else "存在 FAIL"
    lines = [
        "# 数据获取质量核验",
        "",
        f"**结论：{overall}** — OK {counts['OK']} / WARN {counts['WARN']} / FAIL {counts['FAIL']} / BLOCKED {counts['BLOCKED']}",
        "",
        "> 说明：FAIL 表示工具/数据不满足最低要求；WARN 表示可用但需在论文中说明；BLOCKED 表示来源被合规地放弃（如 robots/403）。",
        "",
        "## 按来源汇总",
        "",
        "| 来源 | 最差状态 | 说明 |",
        "|---|---|---|",
    ]
    for source in config.sources:
        worst = _worst(checks, source.id)
        details = [c for c in checks if c.source_id == source.id and c.status == worst]
        detail = details[0].detail if details else ""
        lines.append(f"| `{source.id}` | {worst} | {detail.replace('|', '\\|')[:160]} |")
    lines.extend(["", "## 逐项检查", "", "| 来源 | 检查项 | 状态 | 说明 |", "|---|---|---|---|"])
    for c in checks:
        detail = (c.detail or "").replace("|", "\\|").replace("\n", " ")[:200]
        lines.append(f"| `{c.source_id}` | {c.check} | {c.status} | {detail} |")
    lines.extend(
        [
            "",
            "## 如何解读",
            "",
            "- TPDC 八数据集：元数据、引用、本地附件三项齐全才算高质量；时间范围缺失但标题有范围的记为 WARN。",
            "- 背景文章：正文 ≥300 字为 OK；百度百科被 robots/403 阻断，记为 BLOCKED，不视为工具失败。",
            "- 补充 API：行数 >0、时间起止齐全为 OK；Copernicus 额外检查产品是否与研究区相交。",
            "- 任何 FAIL 都应先修工具或配置，再让论文手引用。",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    tmp = csv_path.with_name(csv_path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["source_id", "check", "status", "detail"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(c.as_dict() for c in checks)
    tmp.replace(csv_path)
    return md_path, csv_path, checks
