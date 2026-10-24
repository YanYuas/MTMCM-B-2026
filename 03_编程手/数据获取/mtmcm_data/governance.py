from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .audit import EVENT_TIME, read_station_rows, window_stats
from .config import APP_ROOT, Config, Source
from .manifest import Manifest
from .store import Store


GOVERNANCE_PATH = APP_ROOT / "config" / "governance.json"


@dataclass
class GovernanceEntry:
    source_id: str
    role: str
    temporal: str
    spatial: str
    crs: str
    license: str
    can: list[str]
    cannot: list[str]
    quality_flags: list[str]
    uncertainty: str
    priority: int
    leakage_risk: str
    precision_risk: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_governance(path: Path | str = GOVERNANCE_PATH) -> dict[str, GovernanceEntry]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到数据治理配置: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, GovernanceEntry] = {}
    for source_id, item in (raw.get("sources") or {}).items():
        out[str(source_id)] = GovernanceEntry(
            source_id=str(source_id),
            role=str(item.get("role", "")),
            temporal=str(item.get("temporal", "")),
            spatial=str(item.get("spatial", "")),
            crs=str(item.get("crs", "")),
            license=str(item.get("license", "")),
            can=[str(x) for x in (item.get("can") or [])],
            cannot=[str(x) for x in (item.get("cannot") or [])],
            quality_flags=[str(x) for x in (item.get("quality_flags") or [])],
            uncertainty=str(item.get("uncertainty", "")),
            priority=int(item.get("priority", 9)),
            leakage_risk=str(item.get("leakage_risk", "")),
            precision_risk=str(item.get("precision_risk", "")),
        )
    return out


def _md(value: Any) -> str:
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ").strip()


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


def _files_meta(store: Store, source: Source) -> dict[str, Any]:
    path = store.data_dir / "meta" / "tpdc" / f"{source.metadata_id}.files.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _status(source: Source, entry: dict[str, Any] | None) -> str:
    if not entry:
        return "未抓取"
    if entry.get("error"):
        return "BLOCKED" if source.allow_blocked else "FAILED"
    return f"HTTP {entry.get('status')}" if entry.get("status") else "UNKNOWN"


def _access_date(entry: dict[str, Any] | None) -> str:
    value = (entry or {}).get("fetched_at", "")
    return value[:10] if value else "—"


def _coverage(source: Source, store: Store, meta: dict[str, Any] | None) -> str:
    if source.kind == "tpdc_dataset":
        files_meta = _files_meta(store, source)
        parts = []
        if files_meta:
            parts.append(f"{files_meta.get('file_count', 0)} 文件 / {files_meta.get('total_size_bytes', 0) / 1e6:.1f} MB")
            parts.append(f"下载:{files_meta.get('download_status', '—')}")
        tc = (meta or {}).get("time_coverage") or {}
        time_text = tc.get("start") or tc.get("title_hint") or "未给"
        parts.append(f"时间:{time_text}")
        if source.id == "tpdc_01_hourly":
            zip_path = source.local_mirror_path
            if zip_path and zip_path.exists():
                try:
                    rows = read_station_rows(zip_path)
                    stats = window_stats(
                        rows,
                        column="Precip(mm)",
                        start=EVENT_TIME - timedelta(hours=72),
                        end=EVENT_TIME,
                    )
                    parts.append(f"事件窗口:{stats['valid']}/{stats['slots']} h")
                except Exception:
                    pass
        return "；".join(parts)
    if source.kind == "article":
        return f"{ (meta or {}).get('char_count', 0) } 字"
    if source.kind == "api_json":
        parts = [f"{ (meta or {}).get('row_count', 0) } 行"]
        if meta and meta.get("time_start"):
            parts.append(f"{meta.get('time_start')} → {meta.get('time_end')}")
        if source.parser == "copernicus":
            parts.append(f"核心区相交 {meta.get('core_overlap_count', 0)}/{meta.get('row_count', 0)}")
        return "；".join(parts)
    return "—"


def _card_markdown(
    source: Source,
    entry: GovernanceEntry,
    meta: dict[str, Any] | None,
    status: str,
    access_date: str,
    coverage: str,
) -> str:
    doi = (meta or {}).get("doi") or ""
    landing = (meta or {}).get("landing_url") or source.url
    lines = [
        f"# 数据卡：{source.name}",
        "",
        f"> 数据治理层生成；来源配置 `config/governance.json`；来源 ID `{source.id}`。",
        "",
        "## 1. 基本信息",
        "",
        "| 项 | 内容 |",
        "|---|---|",
        f"| 类型 | {source.kind} |",
        f"| URL | {landing} |",
        f"| DOI | {doi or '—'} |",
        f"| 访问日期 | {access_date} |",
        f"| 抓取状态 | {status} |",
        f"| 覆盖/规模 | {coverage} |",
        f"| 对应问题 | {'、'.join(source.questions) or '背景'} |",
        "",
        "## 2. 角色与尺度",
        "",
        f"- **角色**：{entry.role}",
        f"- **时间**：{entry.temporal}",
        f"- **空间**：{entry.spatial}",
        f"- **坐标系**：{entry.crs}",
        f"- **许可**：{entry.license}",
        "",
        "## 3. 能支持 / 不能支持",
        "",
        "**能支持：**",
        *[f"- {item}" for item in entry.can],
        "",
        "**不能支持：**",
        *[f"- {item}" for item in entry.cannot],
        "",
        "## 4. 质量标记",
        "",
        *[f"- {item}" for item in entry.quality_flags],
        "",
        "## 5. 不确定性传导",
        "",
        entry.uncertainty,
        "",
        "## 6. 风险",
        "",
        f"- **时间泄漏风险**：{entry.leakage_risk}",
        f"- **虚假精度风险**：{entry.precision_risk}",
        "",
        "## 7. 复现",
        "",
        "```powershell",
        f"python -m mtmcm_data fetch {source.id}",
        f"python -m mtmcm_data validate",
        "```",
        "",
    ]
    return "\n".join(lines)


def build_governance_report(config: Config, store: Store, manifest: Manifest) -> tuple[Path, Path, Path, dict[str, GovernanceEntry]]:
    governance = load_governance()
    latest = manifest.latest_by_source()
    report_dir = store.report_dir
    card_dir = store.data_dir / "data_cards"
    report_dir.mkdir(parents=True, exist_ok=True)
    card_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    cards: list[Path] = []
    for source in config.sources:
        entry = governance.get(source.id)
        meta = _meta_for(store, source)
        status = _status(source, latest.get(source.id))
        access = _access_date(latest.get(source.id))
        coverage = _coverage(source, store, meta)
        if entry is None:
            rows.append(
                {
                    "source_id": source.id,
                    "role": "缺少治理配置",
                    "temporal": "—",
                    "spatial": "—",
                    "crs": "—",
                    "license": "—",
                    "status": status,
                    "access_date": access,
                    "coverage": coverage,
                    "quality_flags": "缺少 config/governance.json 条目",
                    "uncertainty": "—",
                    "leakage_risk": "—",
                    "precision_risk": "—",
                    "questions": "、".join(source.questions),
                }
            )
            continue
        card = card_dir / f"{source.id}.md"
        card.write_text(_card_markdown(source, entry, meta, status, access, coverage), encoding="utf-8")
        cards.append(card)
        rows.append(
            {
                "source_id": source.id,
                "role": entry.role,
                "temporal": entry.temporal,
                "spatial": entry.spatial,
                "crs": entry.crs,
                "license": entry.license,
                "status": status,
                "access_date": access,
                "coverage": coverage,
                "quality_flags": "；".join(entry.quality_flags),
                "uncertainty": entry.uncertainty,
                "leakage_risk": entry.leakage_risk,
                "precision_risk": entry.precision_risk,
                "questions": "、".join(source.questions),
            }
        )

    md_path = report_dir / "data_governance.md"
    csv_path = report_dir / "data_governance.csv"
    lines = [
        "# 多源数据治理与质量评估",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "> 定位：不是“爬虫技术章节”，而是论文的“多源数据治理与质量评估”小节底稿。",
        "> 先内后外：已有 8 组附件的格式/质量审计见 `data/reports/existing_data_audit.md`。",
        "> 第一批 processed 基线（TPDC-01/02/06）见 `data/processed/README.md`。",
        "> 第二批 processed 基线（TPDC-05/07）同样在 `data/processed/`。",
        "> 原则：每个来源都写清“能支持什么、不能支持什么、质量如何进入不确定性”。",
        "",
        f"**汇总**：{len(rows)} 个来源，{len(cards)} 张数据卡；治理配置缺失 {sum(1 for r in rows if r['role'] == '缺少治理配置')} 个。",
        "",
        "## 1. 数据来源与角色表",
        "",
        "| 来源 | 角色 | 时间分辨率/覆盖 | 空间分辨率/范围 | 许可 | 对应问题 | 状态 | 访问日期 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{_md(row['source_id'])}` | {_md(row['role'])} | {_md(row['temporal'])} | "
            f"{_md(row['spatial'])} | {_md(row['license'])} | {_md(row['questions'])} | "
            f"{_md(row['status'])} | {_md(row['access_date'])} |"
        )
    lines.extend(
        [
            "",
            "## 2. 治理流程",
            "",
            "```mermaid",
            "flowchart LR",
            "  A[采集 fetch/download] --> B[去重/哈希]",
            "  B --> C[坐标系/单位统一]",
            "  C --> D[时空对齐]",
            "  D --> E[缺失/异常/QC]",
            "  E --> F[质量标记]",
            "  F --> G[版本快照 manifest]",
            "  G --> H[Q1-Q4 模型与不确定性]",
            "```",
            "",
            "## 3. 质量评估表",
            "",
            "| 来源 | 完整率/覆盖 | 时间戳基准 | 空间分辨率 | 代表性/质量标记 | 参与建模 | 不确定性用途 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{_md(row['source_id'])}` | {_md(row['coverage'])} | {_md(row['temporal'])} | "
            f"{_md(row['spatial'])} | {_md(row['quality_flags'])} | {_md(row['questions'])} | "
            f"{_md(row['uncertainty'])} |"
        )
    lines.extend(
        [
            "",
            "## 4. 四问证据链（谁支撑哪一问、不能做什么）",
            "",
        ]
    )
    for question in ("Q1", "Q2", "Q3", "Q4"):
        selected = [r for r in rows if question in (r["questions"] or "")]
        lines.append(f"### {question}")
        lines.append("")
        if not selected:
            lines.append("- 暂无专门来源；用通用背景/模型假设补足。")
        for row in selected:
            lines.append(f"- `{row['source_id']}`：{row['role']}；质量：{row['quality_flags']}")
        lines.append("")
    lines.extend(
        [
            "### 4.1 质量不确定性如何进入四问",
            "",
            "| 问 | 质量输入 | 传播方式 | 论文写法 |",
            "|---|---|---|---|",
            "| Q1 | 单点 vs 源区代表性误差；两套再分析分歧；9999.9 缺测 | 同季节匹配 + 年份簇 bootstrap；多源排序一致性；缺测率敏感性 | 写“排序不确定性”，不写“唯一重要特征” |",
            "| Q2 | DEM 30 m 与获取时点未知；84 个沟域无事件时间；土地覆盖 2020–2023 | 空间块交叉验证 + 缓冲带；分辨率敏感性；登记偏差讨论 | 写“空间外推边界”，不写“发生概率” |",
            "| Q3 | 站点零降雨 vs 再分析非零；预报误差；无独立事件目录 | 驱动集合扰动；区间/共形校准；明确不可识别边界 | 写“时间区间与预警提前量的条件”，不写“已验证覆盖率” |",
            "| Q4 | DEM 分辨率；冰厚估算；速度气候态；县级人口 | 情景包络 + 参数敏感性；流路一致性核查；暴露分级 | 写“情景结果”，不写“真实灾情复原” |",
            "",
        ]
    )
    lines.extend(
        [
            "## 5. 风险检查（写论文局限时直接用）",
            "",
            "| 来源 | 时间泄漏风险 | 虚假精度风险 |",
            "|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(f"| `{_md(row['source_id'])}` | {_md(row['leakage_risk'])} | {_md(row['precision_risk'])} |")
    lines.extend(
        [
            "",
            "## 6. 可复现性附录",
            "",
            "### 6.1 清洗规则（当前实现）",
            "",
            "- **缺测**：TPDC 的 `9999.9` 与 `QC=8` 标记为缺失，不补零；NASA POWER 的 `fill_value` 转 `null`；Open-Meteo 的空值保留。",
            "- **时间**：TPDC 原始为北京时间 UTC+8；NASA POWER 为 LST；Open-Meteo 显式 `Asia/Shanghai`。跨源合并前统一到 UTC+8，并保留原始时间字段。",
            "- **空间**：保留各源原始分辨率与网格，不强行重采样到同一网格；需要叠加时在模型中显式说明重采样方法与误差。",
            "- **文本**：删除 `script/style/noscript`，去私有区/零宽字符；不做内容改写。",
            "- **下载**：ZIP 完整性校验；嵌套 ZIP 展开后与本地附件比对；原始 ZIP 不覆盖。",
            "",
            "### 6.2 复现命令",
            "",
            "- 采集命令：`python -m mtmcm_data fetch all`；TPDC 数据文件：`python -m mtmcm_data download all`。",
            "- 质量核验：`python -m mtmcm_data validate`；来源审计：`python -m mtmcm_data report`。",
            "- 数据治理：`python -m mtmcm_data governance`；事件窗口：`python -m mtmcm_data audit`。",
            f"- 审计清单：`{store.rel(store.data_dir / 'manifest.jsonl')}`（每个请求的 URL、状态、时间、sha256）。",
            "- 访问日期、许可、坐标系、时间/空间分辨率见上表；所有数据卡在 `data/data_cards/`。",
            "- 不采集登录/付费/个人数据；百度百科被 robots/403 阻断时不绕过，只保留引用链接。",
            "",
            "> 数据质量标记不是“免责声明”，而是不确定性传播的输入：Q1 的排序、Q2 的空间外推、Q3 的时间区间、Q4 的情景包络，都应说明哪些质量标记进入了模型。",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    fieldnames = [
        "source_id",
        "role",
        "temporal",
        "spatial",
        "crs",
        "license",
        "status",
        "access_date",
        "coverage",
        "quality_flags",
        "uncertainty",
        "leakage_risk",
        "precision_risk",
        "questions",
    ]
    tmp = csv_path.with_name(csv_path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)
    return md_path, csv_path, card_dir, governance
