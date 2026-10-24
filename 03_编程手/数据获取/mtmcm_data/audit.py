from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import load_config
from .store import Store


EVENT_TIME = datetime.fromisoformat("2026-08-26T10:30:00")
STATION_MEMBER = "MET_Gyirong_2026.csv"


def parse_station_time(value: str) -> datetime | None:
    """TPDC 站点时间形如 `2026-8-26 10:00`，没有前导零。"""
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", value or "")
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        )
    except ValueError:
        return None


def parse_iso_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def read_station_rows(zip_path: Path, member: str = STATION_MEMBER) -> list[dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as archive:
        raw = archive.read(member)
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        timestamp = parse_station_time(row.get("Timestamp", ""))
        if timestamp is None:
            continue
        rows.append({"time": timestamp, "row": row})
    return rows


def read_table_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for row in rows:
        timestamp = parse_iso_time(row.get("time", ""))
        if timestamp is not None:
            out.append({"time": timestamp, "row": row})
    return out


def _number(value: Any, missing: float | None = 9999.9) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if missing is not None and abs(number - missing) < 1e-9:
        return None
    return number


def window_stats(
    rows: list[dict[str, Any]],
    *,
    column: str,
    start: datetime,
    end: datetime,
    missing: float | None = 9999.9,
) -> dict[str, Any]:
    values: list[float] = []
    missing_count = 0
    total_slots = 0
    for item in rows:
        timestamp = item["time"]
        if not (start <= timestamp <= end):
            continue
        total_slots += 1
        value = _number(item["row"].get(column), missing=missing)
        if value is None:
            missing_count += 1
        else:
            values.append(value)
    return {
        "column": column,
        "window_start": start.isoformat(sep=" ", timespec="minutes"),
        "window_end": end.isoformat(sep=" ", timespec="minutes"),
        "slots": total_slots,
        "valid": len(values),
        "missing": missing_count,
        "sum": round(sum(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
        "nonzero_hours": sum(1 for v in values if v > 0),
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def build_event_audit(store: Store, *, event: datetime = EVENT_TIME, hours: int = 72) -> Path:
    config = load_config()
    source = config.get("tpdc_01_hourly")
    zip_path = source.local_mirror_path
    if zip_path is None or not zip_path.exists():
        raise FileNotFoundError("TPDC-01 本地附件不存在，无法做事件窗口核对")

    start = event - timedelta(hours=hours)
    end = event
    station_rows = read_station_rows(zip_path)
    station_precip = window_stats(station_rows, column="Precip(mm)", start=start, end=end)
    station_temp = window_stats(station_rows, column="Ta_2m(degree C)", start=start, end=end)

    om_rows = read_table_rows(store.table_dir / "open_meteo_archive.csv")
    om_precip = window_stats(om_rows, column="precipitation", start=start, end=end, missing=None)
    nasa_rows = read_table_rows(store.table_dir / "nasa_power.csv")
    nasa_precip = window_stats(nasa_rows, column="PRECTOTCORR", start=start, end=end, missing=None)

    lines: list[str] = []
    lines.append("# 事件窗口数据核对（2026-08-26 10:30）")
    lines.append("")
    lines.append(f"> 窗口：事件前 {hours} 小时，{start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M}（北京时间）")
    lines.append("> 目的：用三套独立来源核对“灾前到底下了多少雨”，避免把站点零降雨当成“没有水源”。")
    lines.append("")
    lines.append("## 1. 降水对照")
    lines.append("")
    lines.append("| 来源 | 变量 | 有效小时 | 缺测 | 累计 | 最大 | 非零小时 |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append(
        f"| TPDC-01 站点 | `Precip(mm)` | {station_precip['valid']} | {station_precip['missing']} | "
        f"{_fmt(station_precip['sum'])} mm | {_fmt(station_precip['max'])} mm | {station_precip['nonzero_hours']} |"
    )
    lines.append(
        f"| Open-Meteo（ERA5） | `precipitation` | {om_precip['valid']} | {om_precip['missing']} | "
        f"{_fmt(om_precip['sum'])} mm | {_fmt(om_precip['max'])} mm | {om_precip['nonzero_hours']} |"
    )
    lines.append(
        f"| NASA POWER | `PRECTOTCORR` | {nasa_precip['valid']} | {nasa_precip['missing']} | "
        f"{_fmt(nasa_precip['sum'])} mm | {_fmt(nasa_precip['max'])} mm | {nasa_precip['nonzero_hours']} |"
    )
    lines.append("")
    lines.append("## 2. 站点气温（同一窗口）")
    lines.append("")
    lines.append(
        f"- `Ta_2m`：有效 {station_temp['valid']} 小时，缺测 {station_temp['missing']}，"
        f"均值 {_fmt(None if station_temp['sum'] is None else station_temp['sum'] / max(station_temp['valid'], 1))} °C，"
        f"最大值 {_fmt(station_temp['max'])} °C。"
    )
    lines.append("")
    lines.append("## 3. 结论（写论文时直接用）")
    lines.append("")
    lines.append(
        f"1. **站点在灾前 {hours} 小时累计降水为 {_fmt(station_precip['sum'])} mm**（有效 {station_precip['valid']} 小时）；"
        "这与“站点暴雨触发”叙事不一致，不能把本站降水当作灾害触发证据。"
    )
    lines.append(
        f"2. **再分析网格给出非零降水**（Open-Meteo {_fmt(om_precip['sum'])} mm，NASA POWER {_fmt(nasa_precip['sum'])} mm），"
        "说明“站点零降雨”不等于“源区没有水源”；源区在尼泊尔一侧，站点距口岸约 65 km。"
    )
    lines.append(
        "3. 三套来源的空间代表性不同：TPDC-01 是单点观测，Open-Meteo/NASA POWER 是网格再分析；"
        "网格海拔约 4138 m / 4995 m，与站点 4140 m 不同。论文中必须标注“观测/再分析/预报”的证据等级。"
    )
    lines.append(
        "4. 这段核对支持 Q1 的“事件窗口异常”写法：先证明站点没有强降水，再去找边界层/土壤/辐射信号；"
        "也支持 Q3 的“预警不能只看本站雨量”，需要卫星/源区降水或冰崩信号。"
    )
    lines.append("")
    lines.append("## 4. 复现")
    lines.append("")
    lines.append("```powershell")
    lines.append("python -m mtmcm_data fetch tpdc_01_hourly open_meteo_archive nasa_power")
    lines.append("python -m mtmcm_data audit")
    lines.append("```")
    lines.append("")
    lines.append("> 注意：TPDC-01 的 `9999.9` 按缺测处理；站点时间原始格式无前导零，已按 `YYYY-M-D H:MM` 解析。")
    lines.append("")

    path = store.report_dir / "event_window_audit.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
