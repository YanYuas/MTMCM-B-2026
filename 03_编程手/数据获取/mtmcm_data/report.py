from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, Source
from .manifest import Manifest
from .store import Store


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _meta_for(store: Store, source: Source) -> dict[str, Any] | None:
    if source.kind == "tpdc_dataset":
        return _read_json(store.data_dir / "meta" / "tpdc" / f"{source.metadata_id}.json")
    if source.kind == "article":
        return _read_json(store.data_dir / "meta" / "articles" / f"{source.id}.json")
    if source.kind == "api_json":
        return _read_json(store.data_dir / "meta" / "api" / f"{source.id}.json")
    return None


def _status(source: Source, entry: dict[str, Any] | None) -> str:
    if not entry:
        return "未抓取"
    if entry.get("error"):
        return "BLOCKED" if source.allow_blocked else "FAILED"
    status = entry.get("status")
    if status == 200:
        return "OK"
    return f"HTTP {status}" if status else "UNKNOWN"


def _entry_time(entry: dict[str, Any] | None) -> str:
    return (entry or {}).get("fetched_at", "") or ""


def _short_time(value: str | None) -> str:
    if not value:
        return "未给"
    return value.replace("T", " ")[:16]


def _bbox_text(meta: dict[str, Any] | None) -> str:
    if not meta:
        return ""
    spatial = meta.get("spatial_coverage") or {}
    bbox = spatial.get("bbox") or {}
    if not bbox:
        return "未给"
    if spatial.get("is_point"):
        return f"点 ({bbox['west']:.4f}, {bbox['south']:.4f})"
    return f"{bbox['west']:.4f}–{bbox['east']:.4f}, {bbox['south']:.4f}–{bbox['north']:.4f}"


def _mirror_text(meta: dict[str, Any] | None) -> str:
    if not meta:
        return ""
    mirror = meta.get("local_mirror") or {}
    if not mirror.get("exists"):
        return "未找到"
    size = mirror.get("size_bytes")
    if isinstance(size, (int, float)):
        return f"有，{size / 1e6:.2f} MB"
    return "有"


def _questions_text(source: Source) -> str:
    return "、".join(source.questions) if source.questions else "背景"


def _citation_for(source: Source, meta: dict[str, Any] | None, entry: dict[str, Any] | None) -> str:
    accessed = _short_time(_entry_time(entry))[:10] or datetime.now().strftime("%Y-%m-%d")
    if meta and meta.get("citation_cn"):
        return str(meta["citation_cn"])
    if source.kind == "article":
        title = (meta or {}).get("title") or source.name
        if "：" in title:
            title = title.split("：", 1)[1]
        published = (meta or {}).get("published_at") or ""
        published_part = f"{published}. " if published else ""
        org = source.name.split("：")[0] if "：" in source.name else source.name
        return f"{org}. {title}[EB/OL]. {published_part}{source.url}（访问日期 {accessed}）."
    if source.id.startswith("open_meteo"):
        return f"Open-Meteo. Historical/Forecast Weather API[DB/OL]. https://open-meteo.com/（访问日期 {accessed}）."
    if source.id == "nasa_power":
        return f"NASA POWER. Hourly Point Data[DB/OL]. https://power.larc.nasa.gov/（访问日期 {accessed}）."
    if source.id.startswith("copernicus"):
        return (
            "Copernicus Data Space Ecosystem. Sentinel product metadata via OData API[DB/OL]. "
            f"https://dataspace.copernicus.eu/（访问日期 {accessed}）."
        )
    return f"{source.name}[EB/OL]. {source.url}（访问日期 {accessed}）."


def build_report(config: Config, store: Store, manifest: Manifest) -> tuple[Path, Path]:
    latest = manifest.latest_by_source()
    generated = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    metas: dict[str, dict[str, Any] | None] = {}

    for source in config.sources:
        entry = latest.get(source.id)
        meta = _meta_for(store, source)
        metas[source.id] = meta
        payload = {
            "source_id": source.id,
            "name": source.name,
            "kind": source.kind,
            "questions": _questions_text(source),
            "status": _status(source, entry),
            "fetched_at": _entry_time(entry),
            "url": source.url,
            "doi": (meta or {}).get("doi", ""),
            "local_mirror": _mirror_text(meta),
            "row_count": (meta or {}).get("row_count", ""),
            "notes": source.notes,
            "error": (entry or {}).get("error", ""),
        }
        rows.append(payload)

    report_dir = store.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / "source_audit.md"
    csv_path = report_dir / "source_audit.csv"

    lines: list[str] = []
    lines.append("# B 题数据来源审计报告")
    lines.append("")
    lines.append(f"> 生成时间：{generated}")
    lines.append("> 工具：`03_编程手/数据获取`（`python -m mtmcm_data fetch all && python -m mtmcm_data report`）")
    lines.append("> 配套数据治理：`data/reports/data_governance.md`（角色/质量/不确定性传导）与 `data/data_cards/`。")
    lines.append("> 原则：每个来源都保留 URL、抓取时间、HTTP 状态和 sha256；失败也留痕，不绕过登录/反爬。")
    lines.append("")

    ok = sum(1 for r in rows if r["status"] == "OK")
    failed = sum(1 for r in rows if r["status"] in {"FAILED", "BLOCKED"})
    lines.append(f"**汇总**：{len(rows)} 个来源，OK {ok}，FAILED/BLOCKED {failed}。")
    lines.append("")

    lines.append("## 1. 来源总表")
    lines.append("")
    lines.append("| 来源 | 类型 | 对应问题 | 状态 | 抓取时间 | 备注 |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        lines.append(
            f"| `{_md(row['source_id'])}` | {_md(row['kind'])} | {_md(row['questions'])} | "
            f"{_md(row['status'])} | {_md(row['fetched_at'])} | {_md(row['notes'])} |"
        )
    lines.append("")

    lines.append("## 2. TPDC 八个数据集")
    lines.append("")
    lines.append("| 来源 | 标题 | DOI | 时间范围 | 空间范围 | 本地附件 |")
    lines.append("|---|---|---|---|---|---|")
    for source in config.sources:
        if source.kind != "tpdc_dataset":
            continue
        meta = metas.get(source.id) or {}
        tc = meta.get("time_coverage") or {}
        if tc.get("start") or tc.get("end"):
            time_range = f"{tc.get('start') or '未给'} → {tc.get('end') or '未给'}"
        elif tc.get("title_hint"):
            time_range = f"未给（标题：{tc['title_hint']}）"
        else:
            time_range = "未给"
        lines.append(
            f"| `{source.id}` | {_md(meta.get('title') or source.name)} | {_md(meta.get('doi') or '无')} | "
            f"{_md(time_range)} | {_md(_bbox_text(meta))} | {_md(_mirror_text(meta))} |"
        )
    lines.append("")

    lines.append("### 2.1 TPDC 文件下载核对")
    lines.append("")
    lines.append("| 来源 | 文件数 | 总大小 | 下载状态 | ZIP | 与本地附件差异 |")
    lines.append("|---|---|---|---|---|---|")
    for source in config.sources:
        if source.kind != "tpdc_dataset":
            continue
        files_meta = _read_json(store.data_dir / "meta" / "tpdc" / f"{source.metadata_id}.files.json") or {}
        status = files_meta.get("download_status") or "未运行"
        total = files_meta.get("total_size_bytes")
        total_text = f"{total / 1e6:.1f} MB" if isinstance(total, (int, float)) else "—"
        if files_meta.get("zip_members") is not None:
            zip_text = f"{files_meta.get('zip_members')} 文件 / {files_meta.get('zip_bytes', 0) / 1e6:.1f} MB"
        else:
            zip_text = "—"
        missing = files_meta.get("missing_vs_local") or []
        if missing:
            diff_text = f"缺 {len(missing)} 个: {', '.join(missing[:3])}"
        elif files_meta.get("comparison_status") == "same_nested":
            diff_text = "一致（嵌套 ZIP）"
        elif files_meta.get("comparison_status") == "same":
            diff_text = "一致"
        else:
            diff_text = "—"
        lines.append(
            f"| `{source.id}` | {_md(files_meta.get('file_count') or '—')} | {_md(total_text)} | "
            f"{_md(status)} | {_md(zip_text)} | {_md(diff_text)} |"
        )
    lines.append("")

    lines.append("### 2.2 关键审计发现（人工摘要）")
    lines.append("")
    lines.append("> 以下结论来自 TPDC 元数据与本地附件核对；逐条可在 `data/meta/tpdc/*.json` 中复核。")
    lines.append("")
    lines.append("- **TPDC-01**：站点约 **28.86°N, 85.29°E, 4140 m**，距吉隆口岸约 **65 km**；时间为 **北京时间 UTC+8**；缺测 **9999.9**；QC 码 **0/1/2/4/8/9**。")
    lines.append("- **TPDC-01 下载差异**：免登录 ZIP 只有 21 个文件，缺 `FLUX_Gyirong_2024/2025/2026.csv`；本地附件有 24 个，建模以本地附件为准。")
    lines.append("- **坐标冲突**：`getGoogleJson` 英文描述写 28.26°N，与 `detail` 的 28.86°N 不一致；本工具以 `detail` 为准，论文引用不要用 GoogleJson 的坐标。")
    lines.append("- **TPDC-06**：84 个沟域多边形，字段只有 `解译Time`/`影像Time`，**没有事件发生时间**；只能做“登记沟域”空间标签。")
    lines.append("- **TPDC-02/07/08**：日气温 2025 年不完整；DEM 获取时点未说明；人口为县级多边形（合计 17,536 人），不含居民点。")
    lines.append("- **TPDC-03**：268.88 MB RAR，`7z` 可读；不是“数据不可用”，只是量大，需要筛选 2000–2020 分时段 dhdt。")
    lines.append("- **补充源**：Open-Meteo / NASA POWER 是再分析或预报，不是站点实测；网格海拔约 4138 m / 4995 m，与站点 4140 m 不同。百度百科被 robots/403 阻断，背景以自然资源部页面为准。")
    lines.append("")

    lines.append("## 3. 补充数据与背景来源")
    lines.append("")
    lines.append("| 来源 | 内容 | 行数/字数 | 时间范围 | 状态 |")
    lines.append("|---|---|---|---|---|")
    for source in config.sources:
        if source.kind == "tpdc_dataset":
            continue
        meta = metas.get(source.id) or {}
        if source.kind == "article":
            content = f"{meta.get('char_count')} 字" if meta else "未抓取"
            time_range = meta.get("published_at") or "未给"
        else:
            content = f"{meta.get('row_count')} 行" if meta else "未抓取"
            time_range = f"{meta.get('time_start') or '未给'} → {meta.get('time_end') or '未给'}" if meta else "未给"
        lines.append(
            f"| `{source.id}` | {_md(meta.get('title') or source.name)} | {_md(content)} | "
            f"{_md(time_range)} | {_md(_status(source, latest.get(source.id)))} |"
        )
    lines.append("")

    lines.append("## 4. 与四问的证据对应")
    lines.append("")
    lines.append("> 说明：这里只列“可支撑哪一问的数据证据”，不代表该数据已经足以回答该问。")
    lines.append("")
    lines.append("| 问 | 可用来源 | 用途 |")
    lines.append("|---|---|---|")
    mapping = {
        "Q1": "边界层/辐射/土壤/湍流特征，事件窗口与同季节背景对比。",
        "Q2": "地形、土地覆盖、历史沟域、冰川与卫星元数据，支撑临界条件与空间易发性。",
        "Q3": "再分析/预报/长期气温，支撑触发时间区间与预警提前量的代理验证。",
        "Q4": "DEM、冰川厚度/速度、人口与 SAR 元数据，支撑守恒仿真与暴露情景。",
    }
    for question, purpose in mapping.items():
        ids = [s.id for s in config.sources if question in s.questions]
        lines.append(f"| {question} | {', '.join(f'`{i}`' for i in ids) or '无'} | {purpose} |")
    lines.append("")

    lines.append("## 5. 可直接引用的来源")
    lines.append("")
    for source in config.sources:
        meta = metas.get(source.id)
        entry = latest.get(source.id)
        if not meta and not entry:
            continue
        citation = _citation_for(source, meta, entry)
        lines.append(f"- **{source.id}**：{citation}")
    lines.append("")
    lines.append("- TPDC 八个数据集已生成 `data/meta/tpdc/<uuid>.ris`，可直接导入 Zotero/EndNote。")
    lines.append("")

    lines.append("## 6. 失败、受限与合规说明")
    lines.append("")
    blocked = [r for r in rows if r["status"] in {"FAILED", "BLOCKED"}]
    if blocked:
        for row in blocked:
            lines.append(f"- `{row['source_id']}`：{row['status']}；{row['error'] or '见 data/meta/errors/'}。")
    else:
        lines.append("- 本次运行没有失败来源。")
    lines.append("")
    lines.append("- 百度百科返回 403（百度安全验证），本工具**不绕过**反爬，只保留引用链接并记录失败证据；背景知识以自然资源部页面为准。")
    lines.append("- Copernicus 只取公开产品元数据；产品下载需要账号/OAuth，工具不代填凭据。")
    lines.append("- Open-Meteo / NASA POWER 为再分析或预报产品，不能当作站点实测；网格海拔与站点海拔不同，引用时必须标注。")
    lines.append("- TPDC 数据使用需按元数据中的 `useTerms` 注明数据来源与作者；本报告已生成 `citation_cn`。")
    lines.append("")

    lines.append("## 7. 复现")
    lines.append("")
    lines.append("```powershell")
    lines.append('cd "03_编程手/数据获取"')
    lines.append("python -m mtmcm_data fetch all --refresh")
    lines.append("python -m mtmcm_data download all")
    lines.append("python -m mtmcm_data existing")
    lines.append("python -m mtmcm_data report")
    lines.append("python -m mtmcm_data audit")
    lines.append("python -m mtmcm_data validate")
    lines.append("python -m mtmcm_data governance")
    lines.append("python -m mtmcm_data verify")
    lines.append("```")
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    _write_csv(csv_path, rows)
    return md_path, csv_path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_id",
        "name",
        "kind",
        "questions",
        "status",
        "fetched_at",
        "url",
        "doi",
        "local_mirror",
        "row_count",
        "notes",
        "error",
    ]
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
