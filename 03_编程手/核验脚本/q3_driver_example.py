# -*- coding: utf-8 -*-
"""
Q3 驱动数据算例（建模手）
- 2026 事件窗口：站点 + Open-Meteo/ERA5 + NASA POWER + CHIRPS
- 2025 事件窗口：站点 + CHIRPS；ERA5/NASA 无 2025 表，显式标缺失
- 输出：03_编程手/核验往来/q3_drivers/
- 目的：给编程手一个可对照的时间/单位/缺失/API/负控制样例，不是 Q3 真实模型结果
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\21722\Desktop\妈妈杯秋季赛\MTMCM比赛协作")
DATA = ROOT / "03_编程手" / "数据获取"
OUT = ROOT / "03_编程手" / "核验往来" / "q3_drivers"
OUT.mkdir(parents=True, exist_ok=True)

STATION = DATA / "data" / "processed" / "tpdc01_hourly" / "tpdc01_key_vars_long.csv.gz"
OM = DATA / "data" / "tables" / "open_meteo_archive.csv"
NASA = DATA / "data" / "tables" / "nasa_power.csv"
CHIRPS = DATA / "data" / "processed" / "event_catalog" / "chirps_daily_values.csv"

K = 0.9
A_ID = 10.0
API_C = 80.0
M_CR = 0.35
PHI = 0.40
P_MIN = 0.1
API_MIN = 5.0


def api72_series(p, k=K, window=72):
    p = np.asarray(p, dtype=float)
    out = np.full(len(p), np.nan)
    for t in range(len(p)):
        s = 0.0
        ok = True
        for i in range(window):
            j = t - i
            if j < 0:
                break
            v = p[j]
            if not np.isfinite(v):
                ok = False
                break
            s += (k ** i) * v
        if ok:
            out[t] = s
    return out


def station_pivot():
    df = pd.read_csv(STATION)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[df["variable"].isin(["Precip", "Ta_2m", "VWC_0.4m"])]
    wide = df.pivot_table(index="timestamp", columns="variable", values="value", aggfunc="first").sort_index()
    wide = wide.rename(columns={"Precip": "station_precip_mm", "Ta_2m": "station_ta_c", "VWC_0.4m": "station_vwc"})
    return wide


def window(df, start, end):
    return df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))].copy()


def add_station(df, st):
    out = df.join(st, how="left")
    # API 用完整站点序列计算，再取窗口
    api = api72_series(st["station_precip_mm"].to_numpy(float))
    out["station_api72_mm"] = pd.Series(api, index=st.index).reindex(out.index)
    out["station_m"] = (out["station_vwc"] / PHI).clip(0, 1)
    out["station_active"] = (out["station_precip_mm"] >= P_MIN) | (out["station_api72_mm"] >= API_MIN)
    raw_i = np.maximum.reduce([
        (out["station_precip_mm"] / A_ID).to_numpy(float),
        (out["station_api72_mm"] / API_C).to_numpy(float),
        (out["station_m"] / M_CR).to_numpy(float),
    ])
    out["station_I_rain"] = np.where(out["station_active"], raw_i, 0.0)
    return out


def add_om(df, om):
    om = om.copy()
    om["timestamp"] = pd.to_datetime(om["time"])
    om = om.set_index("timestamp").sort_index()
    # API 用 216h 完整序列
    om["om_api72_mm"] = api72_series(om["precipitation"].to_numpy(float))
    sub = om.reindex(df.index)
    out = df.copy()
    out["era5_precip_mm"] = sub["precipitation"].to_numpy(float)
    out["era5_ta_c"] = sub["temperature_2m"].to_numpy(float)
    out["era5_vwc_0_7"] = sub["soil_moisture_0_to_7cm"].to_numpy(float)
    out["era5_api72_mm"] = sub["om_api72_mm"].to_numpy(float)
    out["era5_m"] = (out["station_vwc"] / PHI).clip(0, 1)  # 站点 VWC 作为共同土壤水；论文需说明
    out["era5_active"] = (out["era5_precip_mm"] >= P_MIN) | (out["era5_api72_mm"] >= API_MIN)
    raw_i = np.maximum.reduce([
        (out["era5_precip_mm"] / A_ID).to_numpy(float),
        (out["era5_api72_mm"] / API_C).to_numpy(float),
        (out["era5_m"] / M_CR).to_numpy(float),
    ])
    out["era5_I_rain"] = np.where(out["era5_active"], raw_i, 0.0)
    return out


def add_nasa(df, nasa):
    nasa = nasa.copy()
    # NASA 时间为 LST；这里保留 LST 原时间，并给“按经度差对齐到北京时”的映射列
    nasa["timestamp_lst"] = pd.to_datetime(nasa["time"])
    nasa = nasa.set_index("timestamp_lst").sort_index()
    nasa["nasa_api72_mm"] = api72_series(nasa["PRECTOTCORR"].to_numpy(float))
    # 85.29E 的 LST 与 UTC+8 差约 (120-85.29)/15 = 2.314 h
    offset_h = (120.0 - 85.29) / 15.0
    out = df.copy()
    # 仅按 LST 原时间对齐（不静默平移）；另给对齐时间列，供敏感性
    sub = nasa.reindex(df.index)
    out["nasa_precip_mm_lst"] = sub["PRECTOTCORR"].to_numpy(float)
    out["nasa_ta_c_lst"] = sub["T2M"].to_numpy(float)
    out["nasa_gwettop"] = sub["GWETTOP"].to_numpy(float)
    out["nasa_api72_mm_lst"] = sub["nasa_api72_mm"].to_numpy(float)
    out["nasa_time_bjt_aligned"] = out.index + pd.Timedelta(hours=offset_h)
    out["nasa_m"] = (out["station_vwc"] / PHI).clip(0, 1)
    out["nasa_active_lst"] = (out["nasa_precip_mm_lst"] >= P_MIN) | (out["nasa_api72_mm_lst"] >= API_MIN)
    raw_i = np.maximum.reduce([
        (out["nasa_precip_mm_lst"] / A_ID).to_numpy(float),
        (out["nasa_api72_mm_lst"] / API_C).to_numpy(float),
        (out["nasa_m"] / M_CR).to_numpy(float),
    ])
    out["nasa_I_rain_lst"] = np.where(out["nasa_active_lst"], raw_i, 0.0)
    return out


def add_chirps(df, chirps, event_id):
    ch = chirps[chirps["event_id"] == event_id].copy()
    ch["date"] = pd.to_datetime(ch["date"]).dt.normalize()
    ch = ch.set_index("date")
    out = df.copy()
    dates = out.index.normalize()
    out["chirps_station_mm_day"] = ch["station_mm"].reindex(dates).to_numpy(float)
    out["chirps_event_area_mm_day"] = ch["event_area_mm"].reindex(dates).to_numpy(float)
    # 展示用：日值均匀到小时；不是真小时观测
    out["chirps_event_area_mm_h_uniform"] = out["chirps_event_area_mm_day"] / 24.0
    # API 用“日值重复到小时”的均匀序列，仅作展示
    tmp = out["chirps_event_area_mm_h_uniform"].copy()
    # 用窗口前的日值构造 API 不够；这里用窗口内可用序列，标 NA 前段
    out["chirps_api72_mm_uniform"] = api72_series(tmp.to_numpy(float))
    out["chirps_m"] = (out["station_vwc"] / PHI).clip(0, 1)
    out["chirps_active_uniform"] = (out["chirps_event_area_mm_h_uniform"] >= P_MIN) | (out["chirps_api72_mm_uniform"] >= API_MIN)
    raw_i = np.maximum.reduce([
        (out["chirps_event_area_mm_h_uniform"] / A_ID).to_numpy(float),
        (out["chirps_api72_mm_uniform"] / API_C).to_numpy(float),
        (out["chirps_m"] / M_CR).to_numpy(float),
    ])
    out["chirps_I_rain_uniform"] = np.where(out["chirps_active_uniform"], raw_i, 0.0)
    return out


def summarize(df, label, event_time, notes):
    def col_stats(col):
        s = pd.to_numeric(df[col], errors="coerce")
        return {
            "n": int(s.notna().sum()),
            "sum": float(s.sum()) if s.notna().any() else None,
            "max": float(s.max()) if s.notna().any() else None,
        }

    drivers = {}
    for prefix, cols in {
        "station": ["station_precip_mm", "station_api72_mm", "station_I_rain"],
        "era5": ["era5_precip_mm", "era5_api72_mm", "era5_I_rain"],
        "nasa_lst": ["nasa_precip_mm_lst", "nasa_api72_mm_lst", "nasa_I_rain_lst"],
        "chirps_uniform": ["chirps_event_area_mm_h_uniform", "chirps_api72_mm_uniform", "chirps_I_rain_uniform"],
    }.items():
        drivers[prefix] = {
            "available": bool(df[cols[0]].notna().any()) if cols[0] in df else False,
            "precip": col_stats(cols[0]) if cols[0] in df else None,
            "api72": col_stats(cols[1]) if cols[1] in df else None,
            "max_I": col_stats(cols[2]) if cols[2] in df else None,
        }
    for prefix, active_col in {
        "station": "station_active",
        "era5": "era5_active",
        "nasa_lst": "nasa_active_lst",
        "chirps_uniform": "chirps_active_uniform",
    }.items():
        if prefix in drivers and active_col in df:
            drivers[prefix]["active_n"] = int(df[active_col].fillna(False).sum())
    return {
        "label": label,
        "event_time": event_time,
        "window_start": str(df.index.min()),
        "window_end": str(df.index.max()),
        "rows": int(len(df)),
        "drivers": drivers,
        "notes": notes,
    }


def main():
    st = station_pivot()
    om = pd.read_csv(OM)
    nasa = pd.read_csv(NASA)
    ch = pd.read_csv(CHIRPS)

    # 2026 window: 2026-08-23 10:00 -> 2026-08-26 10:00 (73 hourly rows)
    idx26 = pd.date_range("2026-08-23 10:00", "2026-08-26 10:00", freq="h")
    df26 = pd.DataFrame(index=idx26)
    df26 = add_station(df26, st)
    df26 = add_om(df26, om)
    df26 = add_nasa(df26, nasa)
    df26 = add_chirps(df26, ch, "E20260826")
    df26.index.name = "timestamp_bjt"
    df26.to_csv(OUT / "q3_driver_example_2026.csv", encoding="utf-8-sig")
    s26 = summarize(df26, "2026-08-26 冰崩链", "2026-08-26 10:30",
                    ["站点/ERA5 为 Asia/Shanghai；NASA 原始为 LST，另给按经度差对齐列",
                     "CHIRPS 为日值；uniform 仅展示，不是小时观测",
                     "窗口末 10:00，事件 10:30；小时数据不能给分钟级触发"])

    # 2025 window: 2025-07-05 05:00 -> 2025-07-08 05:00 (73 rows)
    idx25 = pd.date_range("2025-07-05 05:00", "2025-07-08 05:00", freq="h")
    df25 = pd.DataFrame(index=idx25)
    df25 = add_station(df25, st)
    # 2025 ERA5/NASA 表不存在；显式 NA 列
    df25["era5_precip_mm"] = np.nan
    df25["era5_api72_mm"] = np.nan
    df25["era5_I_rain"] = np.nan
    df25["nasa_precip_mm_lst"] = np.nan
    df25["nasa_api72_mm_lst"] = np.nan
    df25["nasa_I_rain_lst"] = np.nan
    df25 = add_chirps(df25, ch, "E20250708")
    df25.index.name = "timestamp_bjt"
    df25.to_csv(OUT / "q3_driver_example_2025.csv", encoding="utf-8-sig")
    s25 = summarize(df25, "2025-07-08 GLOF", "2025-07-08 05:00",
                    ["2025 只有站点 + CHIRPS；ERA5/NASA 无 2025 表，显式 NA",
                     "CHIRPS 为日值；uniform 仅展示",
                     "事件 05:00；窗口包含事件整点"])

    summary = {"2026": s26, "2025": s25}
    with open(OUT / "q3_driver_example_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
