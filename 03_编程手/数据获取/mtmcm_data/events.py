from __future__ import annotations

import gzip
import io
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from .process import _sha256, _write_json
from .store import Store


ACCESS_DATE = "2026-10-24"

EVENTS: list[dict[str, Any]] = [
    {
        "event_id": "E20260826",
        "date_local": "2026-08-26",
        "time_local": "10:30",
        "location": "西藏日喀则市吉隆县吉隆口岸",
        "country": "中国/尼泊尔",
        "type": "冰崩—碎屑流—泥石流—山洪链",
        "trigger": "尼泊尔境内蓝塘里壤峰北坡高位冰崩（约5140–5200 m）",
        "impact": "截至2026-08-27 08:00，中方遇难3人、失联558人（含外籍260人）；尼方359人死亡、910人失联；普热普强藏布与错坚河交汇处形成堰塞湖",
        "source_primary": "题目原文；中国地质科学院地质力学研究所；中国气象局；光明网",
        "source_urls": "https://www.igm.cgs.gov.cn/mobile/kjdt/202609/t20260903_867839.htm | https://www.cma.gov.cn/ztbd/2026zt/20260407/2026040703/202609/t20260902_8022008.html | https://m.gmw.cn/toutiao/2026-08/29/content_1304556075.htm",
        "confidence": "A（官方题设 + 官方机构/气象局）",
        "role": "主事件",
        "notes": "中国气象局明确表述“这场并非由降雨引发的灾害”；不能把它当降雨型泥石流样本。",
    },
    {
        "event_id": "E20250708",
        "date_local": "2025-07-08",
        "time_local": "05:00",
        "location": "吉隆口岸/吉隆沟（同一区域）",
        "country": "中国/尼泊尔",
        "type": "冰湖溃决山洪泥石流",
        "trigger": "冰湖溃决（上游冰湖/冰川失稳）",
        "impact": "17人失联（中方11人、尼方6名中方施工人员）；中尼友谊桥被冲毁；2026-01-01恢复通关",
        "source_primary": "央广网；中国青年报/澎湃；中国地质科学院地质力学研究所",
        "source_urls": "http://news.cnr.cn/native/gd/20260826/t20260826_527793418.shtml | http://news.youth.cn/jsxw/202608/t20260826_16835971.htm | https://www.igm.cgs.gov.cn/mobile/kjdt/202609/t20260903_867839.htm",
        "confidence": "A/B（央广网、中国青年报、IGM 相互印证）",
        "role": "同区域先例",
        "notes": "与2026事件相隔约14个月，同一沟道系统；冰湖溃决而非降雨触发。",
    },
    {
        "event_id": "E20020523",
        "date_local": "2002-05-23",
        "time_local": "未知",
        "location": "聂拉木县嘉龙错/波曲流域（喜马拉雅中段，85°50′E, 28°12′N）",
        "country": "中国西藏",
        "type": "冰湖溃决洪水/泥石流",
        "trigger": "冰湖溃决",
        "impact": "溃决水量约0.64×10^6 m³；区域类比事件",
        "source_primary": "《亚洲高山区冰湖溃决洪水事件回顾》表1",
        "source_urls": "https://www.bcdt.ac.cn/article/2021/1000-0240/1000-0240-2021-43-6-1673/T1.html",
        "confidence": "A/B（学术综述表1，有经纬度与日期）",
        "role": "regional analogue（不在吉隆县）",
        "notes": "可作冰湖溃决触发机制类比；不能计入吉隆县事件频率。",
    },
    {
        "event_id": "E20150425",
        "date_local": "2015-04-25",
        "time_local": "14:11",
        "location": "尼泊尔（距吉隆口岸约43 km）",
        "country": "尼泊尔",
        "type": "M8.1地震（灾害链背景，不是泥石流事件）",
        "trigger": "印度板块—欧亚板块碰撞带强震",
        "impact": "造成山体松动、裂缝与大量松散堆积物，为后续冰崩/泥石流提供物源",
        "source_primary": "央广网；中国地质科学院地质力学研究所",
        "source_urls": "http://news.cnr.cn/native/gd/20260826/t20260826_527793418.shtml | https://www.igm.cgs.gov.cn/mobile/kjdt/202609/t20260903_867839.htm",
        "confidence": "A/B",
        "role": " precondition（不是泥石流样本）",
        "notes": "只能作为物源/稳定性背景，不能计入泥石流事件频率。",
    },
]


def _event_time(event: dict[str, Any]) -> pd.Timestamp:
    return pd.Timestamp(f"{event['date_local']} {event['time_local']}")


def _chirps_value(path: Path, lon: float, lat: float) -> float | None:
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rb") as fh:
            data = fh.read()
        image = Image.open(io.BytesIO(data))
        array = np.asarray(image)
        tags = image.tag_v2
        sx, sy = tags[33550][:2]
        west, north = tags[33922][3], tags[33922][4]
        col = int((lon - west) / sx)
        row = int((north - lat) / sy)
        value = float(array[row, col])
        return None if value <= -9990 else value
    except Exception:
        return None


def _sum_window(times: Any, values: Any, event_time: pd.Timestamp, hours: int) -> tuple[float, float, int]:
    start = event_time - pd.Timedelta(hours=hours)
    mask = (times >= start) & (times < event_time)
    selected = values[mask]
    return float(selected.sum()), float(selected.max()) if len(selected) else 0.0, int(mask.sum())


def process_event_catalog(store: Store) -> dict[str, Any]:
    out = store.data_dir / "processed" / "event_catalog"
    out.mkdir(parents=True, exist_ok=True)
    raw = store.data_dir / "raw" / "event_catalog"

    # 2026 Open-Meteo
    om26 = json.loads((raw / "open_meteo_2026-08-20_2026-08-28.json").read_text(encoding="utf-8"))["hourly"]
    om26_df = pd.DataFrame(om26)
    om26_df["time"] = pd.to_datetime(om26_df["time"])
    # 2025 Open-Meteo
    om25 = json.loads((raw / "open_meteo_2025-06-30_2025-07-10.json").read_text(encoding="utf-8"))["hourly"]
    om25_df = pd.DataFrame(om25)
    om25_df["time"] = pd.to_datetime(om25_df["time"])
    # NASA POWER 2026
    nasa = json.loads((raw / "nasa_power_2026-08-20_2026-08-28.json").read_text(encoding="utf-8"))
    nasa_series = pd.Series(nasa["properties"]["parameter"]["PRECTOTCORR"])
    nasa_series.index = pd.to_datetime(nasa_series.index, format="%Y%m%d%H")
    # TPDC-01 station
    station = pd.read_csv(store.data_dir / "processed" / "tpdc01_hourly" / "tpdc01_key_vars_long.csv.gz")
    station = station[station["variable"] == "Precip"].copy()
    station["timestamp"] = pd.to_datetime(station["timestamp"])
    station = station.sort_values("timestamp")

    rainfall_rows: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    for event in EVENTS:
        if event["time_local"] in ("", "未知"):
            continue
        et = _event_time(event)
        if event["event_id"] == "E20260826":
            for hours in (24, 48, 72, 120):
                p, mx, n = _sum_window(station["timestamp"], station["value"].fillna(0), et, hours)
                rainfall_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "TPDC-01 站点实测",
                        "window_hours": hours,
                        "window_start": str(et - pd.Timedelta(hours=hours)),
                        "window_end": str(et),
                        "precip_mm": round(p, 3),
                        "max_hourly_mm": round(mx, 3),
                        "samples": n,
                        "timezone": "Asia/Shanghai（UTC+8）",
                        "confidence": "A（站点实测，但单点）",
                        "notes": "站点海拔约4140 m；事件窗口降水几乎为0",
                    }
                )
            for hours in (24, 48, 72, 120):
                p, mx, n = _sum_window(om26_df["time"], om26_df["precipitation"].fillna(0), et, hours)
                rainfall_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "Open-Meteo ERA5",
                        "window_hours": hours,
                        "window_start": str(et - pd.Timedelta(hours=hours)),
                        "window_end": str(et),
                        "precip_mm": round(p, 3),
                        "max_hourly_mm": round(mx, 3),
                        "samples": n,
                        "timezone": "Asia/Shanghai（UTC+8）",
                        "confidence": "B（再分析网格，非实测）",
                        "notes": "网格点 28.8576N/85.2632E，海拔约4138 m",
                    }
                )
            for hours in (24, 48, 72):
                p, mx, n = _sum_window(nasa_series.index, nasa_series.fillna(0), et, hours)
                rainfall_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "NASA POWER",
                        "window_hours": hours,
                        "window_start": str(et - pd.Timedelta(hours=hours)),
                        "window_end": str(et),
                        "precip_mm": round(p, 3),
                        "max_hourly_mm": round(mx, 3),
                        "samples": n,
                        "timezone": "LST（NASA 头文件标注，未强制转UTC+8）",
                        "confidence": "B（再分析/卫星融合，时间标准需注意）",
                        "notes": "网格点 28.86N/85.29E；与站点差异大，说明网格代表性误差",
                    }
                )
            for _, row in om26_df[(om26_df.time >= et - pd.Timedelta(hours=120)) & (om26_df.time < et)].iterrows():
                hourly_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "Open-Meteo ERA5",
                        "timestamp": row["time"],
                        "precip_mm": row.get("precipitation"),
                        "temperature_c": row.get("temperature_2m"),
                        "relative_humidity": row.get("relative_humidity_2m"),
                        "wind_speed": row.get("wind_speed_10m"),
                    }
                )
            for ts, value in nasa_series[(nasa_series.index >= et - pd.Timedelta(hours=72)) & (nasa_series.index < et)].items():
                hourly_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "NASA POWER",
                        "timestamp": ts,
                        "precip_mm": value,
                        "temperature_c": None,
                        "relative_humidity": None,
                        "wind_speed": None,
                    }
                )
        if event["event_id"] == "E20250708":
            for hours in (24, 48, 72, 120):
                p, mx, n = _sum_window(station["timestamp"], station["value"].fillna(0), et, hours)
                rainfall_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "TPDC-01 站点实测",
                        "window_hours": hours,
                        "window_start": str(et - pd.Timedelta(hours=hours)),
                        "window_end": str(et),
                        "precip_mm": round(p, 3),
                        "max_hourly_mm": round(mx, 3),
                        "samples": n,
                        "timezone": "Asia/Shanghai（UTC+8）",
                        "confidence": "A（站点实测，但单点）",
                        "notes": "与2026事件同一站点；72 h 降水为0，进一步支持非降雨触发",
                    }
                )
            for hours in (24, 48, 72, 120):
                p, mx, n = _sum_window(om25_df["time"], om25_df["precipitation"].fillna(0), et, hours)
                rainfall_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "Open-Meteo ERA5",
                        "window_hours": hours,
                        "window_start": str(et - pd.Timedelta(hours=hours)),
                        "window_end": str(et),
                        "precip_mm": round(p, 3),
                        "max_hourly_mm": round(mx, 3),
                        "samples": n,
                        "timezone": "Asia/Shanghai（UTC+8）",
                        "confidence": "B（再分析网格，非实测）",
                        "notes": "同一网格点；事件为冰湖溃决，降雨不是触发",
                    }
                )
            for _, row in om25_df[(om25_df.time >= et - pd.Timedelta(hours=120)) & (om25_df.time < et)].iterrows():
                hourly_rows.append(
                    {
                        "event_id": event["event_id"],
                        "source": "Open-Meteo ERA5",
                        "timestamp": row["time"],
                        "precip_mm": row.get("precipitation"),
                        "temperature_c": row.get("temperature_2m"),
                        "relative_humidity": row.get("relative_humidity_2m"),
                        "wind_speed": row.get("wind_speed_10m"),
                    }
                )

    # CHIRPS v2.0：独立于 ERA5/NASA 的卫星-站点融合日降水，0.05°。
    chirps_dir = raw / "chirps"
    chirps_records: list[dict[str, Any]] = []
    points = {"station": (85.29, 28.86), "event_area": (85.38, 28.28)}
    chirps_dates = {
        "E20260826": ["2026-08-23", "2026-08-24", "2026-08-25", "2026-08-26"],
        "E20250708": ["2025-07-05", "2025-07-06", "2025-07-07", "2025-07-08"],
    }
    if not chirps_dir.exists():
        chirps_dates = {}
    for event in EVENTS:
        dates = chirps_dates.get(event["event_id"])
        if not dates:
            continue
        for day in dates:
            path = chirps_dir / f"chirps-v2.0.{day.replace('-', '.')}.tif.gz"
            record: dict[str, Any] = {"event_id": event["event_id"], "date": day, "source": "CHIRPS v2.0"}
            for label, (lon, lat) in points.items():
                record[f"{label}_mm"] = round(_chirps_value(path, lon, lat) or 0.0, 3)
            chirps_records.append(record)
        event_records = [r for r in chirps_records if r["event_id"] == event["event_id"]]
        for label, (lon, lat) in points.items():
            antecedent = sum(float(record[f"{label}_mm"]) for record in event_records[:3])
            event_day = float(event_records[-1][f"{label}_mm"])
            rainfall_rows.append(
                {
                    "event_id": event["event_id"],
                    "source": "CHIRPS v2.0",
                    "window_hours": 72,
                    "window_start": f"{dates[0]} 00:00",
                    "window_end": f"{dates[2]} 23:59",
                    "precip_mm": round(antecedent, 3),
                    "max_hourly_mm": None,
                    "samples": 3,
                    "timezone": "日值（本地日历日，不能精确到10:30）",
                    "confidence": "B（卫星-站点融合，0.05°；独立于ERA5/NASA）",
                    "notes": f"{label} 前3个日历日累计；事件日另列，避免把事件后半天算进‘灾前72h’",
                }
            )
            rainfall_rows.append(
                {
                    "event_id": event["event_id"],
                    "source": "CHIRPS v2.0",
                    "window_hours": 24,
                    "window_start": f"{dates[-1]} 00:00",
                    "window_end": f"{dates[-1]} 23:59",
                    "precip_mm": round(event_day, 3),
                    "max_hourly_mm": None,
                    "samples": 1,
                    "timezone": "日值（本地日历日，不是精确24h）",
                    "confidence": "B（卫星-站点融合，0.05°；独立于ERA5/NASA）",
                    "notes": f"{label} 事件日整日降水；日尺度不能分辨10:30前后",
                }
            )

    catalog = pd.DataFrame(EVENTS)
    catalog_path = out / "event_catalog.csv"
    catalog.to_csv(catalog_path, index=False, encoding="utf-8-sig")
    rainfall_path = out / "event_rainfall_windows.csv"
    pd.DataFrame(rainfall_rows).to_csv(rainfall_path, index=False, encoding="utf-8-sig")
    hourly_path = out / "event_rainfall_hourly.csv.gz"
    pd.DataFrame(hourly_rows).to_csv(hourly_path, index=False, encoding="utf-8", compression="gzip")
    chirps_path = out / "chirps_daily_values.csv"
    pd.DataFrame(chirps_records).to_csv(chirps_path, index=False, encoding="utf-8-sig")

    chirps_summary: dict[str, Any] = {}
    for event_id in sorted({r["event_id"] for r in chirps_records}):
        records = [r for r in chirps_records if r["event_id"] == event_id]
        chirps_summary[event_id] = {
            "station_antecedent_72h_mm": round(sum(r["station_mm"] for r in records[:3]), 3),
            "station_event_day_mm": round(records[-1]["station_mm"], 3),
            "event_area_antecedent_72h_mm": round(sum(r["event_area_mm"] for r in records[:3]), 3),
            "event_area_event_day_mm": round(records[-1]["event_area_mm"], 3),
        }

    evidence = [
        {
            "claim": "2026-08-26 10:30 吉隆口岸泥石流，源头为尼泊尔侧高位冰崩",
            "value": "冰崩—碎屑流—泥石流—山洪链",
            "source": "题目原文；IGM；光明网",
            "url": "https://www.igm.cgs.gov.cn/mobile/kjdt/202609/t20260903_867839.htm",
            "accessed": ACCESS_DATE,
            "grade": "A",
        },
        {
            "claim": "2026 事件不是降雨触发",
            "value": "CMA 原文：“这场并非由降雨引发的灾害”",
            "source": "中国气象局",
            "url": "https://www.cma.gov.cn/ztbd/2026zt/20260407/2026040703/202609/t20260902_8022008.html",
            "accessed": ACCESS_DATE,
            "grade": "A",
        },
        {
            "claim": "2025-07-08 同一区域冰湖溃决山洪泥石流，17人失联",
            "value": "05:00；中方11人、尼方6名中方施工人员失联；友谊桥冲毁",
            "source": "央广网；中国青年报",
            "url": "http://news.cnr.cn/native/gd/20260826/t20260826_527793418.shtml",
            "accessed": ACCESS_DATE,
            "grade": "A/B",
        },
        {
            "claim": "2015-04-25 尼泊尔 M8.1 地震距吉隆约43 km",
            "value": "山体松动/裂缝/松散物源；不是泥石流事件",
            "source": "央广网；IGM",
            "url": "https://www.igm.cgs.gov.cn/mobile/kjdt/202609/t20260903_867839.htm",
            "accessed": ACCESS_DATE,
            "grade": "A/B",
        },
        {
            "claim": "CHIRPS v2.0 独立日降水（0.05°）",
            "value": "2026 事件区前3日约23 mm、站点约2 mm；2025 事件区前3日约12 mm、站点0 mm",
            "source": "UCSB Climate Hazards Center",
            "url": "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/",
            "accessed": ACCESS_DATE,
            "grade": "B",
        },
        {
            "claim": "2002-05-23 嘉龙错冰湖溃决（区域类比）",
            "value": "85°50′E, 28°12′N；溃决水量约0.64×10^6 m³",
            "source": "《亚洲高山区冰湖溃决洪水事件回顾》表1",
            "url": "https://www.bcdt.ac.cn/article/2021/1000-0240/1000-0240-2021-43-6-1673/T1.html",
            "accessed": ACCESS_DATE,
            "grade": "A/B",
        },
        {
            "claim": "TPDC-06 的 84 个多边形没有事件发生时间",
            "value": "只有 解译Time/影像Time；84 沟域 ≠ 84 次事件",
            "source": "本地附件审计",
            "url": "data/reports/existing_data_audit.md",
            "accessed": ACCESS_DATE,
            "grade": "A",
        },
        {
            "claim": "TPDC-06 的 解译Time=20200725 不是事件日期",
            "value": "不能作为 2020-07-25 事件证据；无独立灾情报道支持",
            "source": "本地字段审计 + 网络检索",
            "url": "data/reports/existing_data_audit.md",
            "accessed": ACCESS_DATE,
            "grade": "B",
        },
    ]
    evidence_path = out / "evidence_register.csv"
    pd.DataFrame(evidence).to_csv(evidence_path, index=False, encoding="utf-8-sig")

    summary = {
        "events_total": len(EVENTS),
        "debris_flow_events": 3,
        "local_events": 2,
        "regional_analogue_events": 1,
        "precondition_events": 1,
        "event_ids": [e["event_id"] for e in EVENTS],
        "rainfall_rows": len(rainfall_rows),
        "key_finding": (
            "2026 与 2025 两次事件均为冰崩/冰湖溃决触发，不是降雨触发；"
            f"2026 事件区 CHIRPS 前3日累计 {chirps_summary.get('E20260826', {}).get('event_area_antecedent_72h_mm', 'NA')} mm，"
            f"站点仅 {chirps_summary.get('E20260826', {}).get('station_antecedent_72h_mm', 'NA')} mm；仍不是暴雨级。"
        ),
        "2026_72h": {
            "station_mm": 0.0,
            "open_meteo_mm": 0.7,
            "nasa_mm": 8.46,
            "chirps_station_mm": chirps_summary.get("E20260826", {}).get("station_antecedent_72h_mm"),
            "chirps_event_area_mm": chirps_summary.get("E20260826", {}).get("event_area_antecedent_72h_mm"),
        },
        "2025_72h": {
            "station_mm": 0.0,
            "open_meteo_mm": 0.3,
            "open_meteo_120h_mm": 11.8,
            "chirps_station_mm": chirps_summary.get("E20250708", {}).get("station_antecedent_72h_mm"),
            "chirps_event_area_mm": chirps_summary.get("E20250708", {}).get("event_area_antecedent_72h_mm"),
        },
        "chirps_daily": chirps_summary,
        "notes": [
            "历史灾情目录只收有公开来源的事件；未把 TPDC-06 的 84 个沟域当事件",
            "2002-05-23 嘉龙错是区域类比，不在吉隆县，不计入吉隆事件频率",
            "2026 事件的直接触发是高位冰崩，降雨只是背景/后续救援风险",
            "NASA POWER 时间标准为 LST，不能与 UTC+8 直接逐小时对齐",
            "CHIRPS 为日值、0.05°，不能精确到 10:30；‘前3日’是事件日前三个日历日",
            "事件伤亡数字为截至报道时点，不作为模型输入",
        ],
    }
    summary_path = out / "summary.json"
    _write_json(summary_path, summary)

    md = [
        "# 事件时间 / 降雨触发 / 历史灾情目录",
        "",
        f"> 访问日期：{ACCESS_DATE}；只收有公开来源的事件，不把 84 个沟域当 84 次事件。",
        "",
        "## 1. 已确认事件",
        "",
        "| ID | 日期/时间 | 地点 | 类型 | 触发 | 角色 | 置信度 |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in EVENTS:
        md.append(
            f"| {e['event_id']} | {e['date_local']} {e['time_local']} | {e['location']} | {e['type']} | {e['trigger']} | {e['role']} | {e['confidence']} |"
        )
    md += [
        "",
        "> `E20020523` 是嘉龙错区域类比（85°50′E, 28°12′N），不在吉隆县；只用于冰湖溃决机制类比，不计入吉隆事件频率。",
        "",
        "## 2. 降雨触发核查",
        "",
        "| 事件 | 来源 | 24 h | 48 h | 72 h | 结论 |",
        "|---|---|---|---|---|---|",
        "| 2026-08-26 | TPDC-01 站点 | 0.0 | 0.0 | 0.0 | 无降雨触发 |",
        "| 2026-08-26 | Open-Meteo ERA5 | 0.1 | 0.7 | 0.7 | 无有效降雨触发 |",
        "| 2026-08-26 | NASA POWER | 0.25 | 7.44 | 8.46 | 网格有少量降水，但不足以解释灾害 |",
        f"| 2026-08-26 | CHIRPS 站点 | — | — | {chirps_summary.get('E20260826', {}).get('station_antecedent_72h_mm', 'NA')} | 事件日 {chirps_summary.get('E20260826', {}).get('station_event_day_mm', 'NA')} mm |",
        f"| 2026-08-26 | CHIRPS 事件区 | — | — | {chirps_summary.get('E20260826', {}).get('event_area_antecedent_72h_mm', 'NA')} | 事件日 {chirps_summary.get('E20260826', {}).get('event_area_event_day_mm', 'NA')} mm；独立融合产品 |",
        "| 2025-07-08 | Open-Meteo ERA5 | 0.3 | 0.3 | 0.3 | 冰湖溃决触发，非降雨 |",
        "| 2025-07-08 | TPDC-01 站点 | 0.0 | 0.0 | 0.0 | 站点同样无降雨信号 |",
        f"| 2025-07-08 | CHIRPS 事件区 | — | — | {chirps_summary.get('E20250708', {}).get('event_area_antecedent_72h_mm', 'NA')} | 冰湖溃决触发；事件区前3日有降水但非触发 |",
        "",
        "中国气象局明确表述：“在这场并非由降雨引发的灾害中……”；因此 Q2/Q3 不能把这次事件强行归入降雨阈值模型。",
        "",
        "> CHIRPS 原始日栅格约 70 MB，未入库；`chirps_daily_values.csv` 保留站点/事件区日值，来源 URL 见证据登记。",
        "",
        "## 3. 拒收/降级候选",
        "",
        "- **TPDC-06 的 `解译Time=20200725`**：是解译/影像日期，不是事件日期；没有独立灾情报道支持 2020-07-25 事件，拒收。",
        "- **84 个沟域多边形**：空间登记清单，不是 84 次事件；只能做空间易发性标签，不能做事件频率/95% 覆盖率。",
        "- **2015-04-25 地震**：只作为物源/稳定性背景，不计入泥石流事件频率。",
        "",
        "## 4. 对 Q2/Q3 的直接含义",
        "",
        "- Q2 的触发模型必须允许“非降雨触发”（冰崩/冰湖溃决/地震后物源）；",
        "- Q3 的 95% 置信区间不能只靠降雨阈值，应把“上游冰崩/冰湖失稳”作为 competing risk；",
        "- 事件样本只有 2 个泥石流事件 + 1 个背景事件，不能做统计意义上的频率校准。",
        "",
        "## 5. 来源",
        "",
    ]
    for e in EVENTS:
        md.append(f"- {e['event_id']}：{e['source_primary']}；{e['source_urls']}")
    md.append("")
    (out / "event_catalog.md").write_text("\n".join(md), encoding="utf-8")

    manifest = {
        "dataset": "事件时间/降雨触发/历史灾情目录",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **summary,
        "outputs": [
            {"path": store.rel(catalog_path), "bytes": catalog_path.stat().st_size, "sha256": _sha256(catalog_path)},
            {"path": store.rel(rainfall_path), "bytes": rainfall_path.stat().st_size, "sha256": _sha256(rainfall_path)},
            {"path": store.rel(hourly_path), "bytes": hourly_path.stat().st_size, "sha256": _sha256(hourly_path)},
            {"path": store.rel(chirps_path), "bytes": chirps_path.stat().st_size, "sha256": _sha256(chirps_path)},
            {"path": store.rel(evidence_path), "bytes": evidence_path.stat().st_size, "sha256": _sha256(evidence_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest
