from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "Q2" / "源代码"))
from q2_geometry import DATA, glacier_on_dem, grid, load_tiff  # noqa: E402

BASE = HERE.parents[2]
WEB = HERE / "web"
DATA_OUT = WEB / "data"
DATA_OUT.mkdir(parents=True, exist_ok=True)
DOWN = 4

dem, dem_tags = load_tiff(DATA / "tpdc07_dem" / "dem_core_30m.tif")
slope, _ = load_tiff(DATA / "tpdc07_dem" / "slope_deg.tif")
glacier, glacier_tags = load_tiff(DATA / "tpdc04_glacier" / "glacier_mask.tif")
west, north, sx, sy = grid(dem_tags)
rows, cols = dem.shape
lat0 = north - rows * sy / 2
lon0 = west + cols * sx / 2
dx_km = abs(sx) * 111.320 * math.cos(math.radians(lat0))
dy_km = abs(sy) * 110.574

# 4x block mean for terrain; nearest for masks
r4, c4 = rows // DOWN, cols // DOWN
dem4 = dem[: r4 * DOWN, : c4 * DOWN].reshape(r4, DOWN, c4, DOWN).mean(axis=(1, 3)).astype("float32")
slope4 = slope[: r4 * DOWN, : c4 * DOWN].reshape(r4, DOWN, c4, DOWN).mean(axis=(1, 3)).astype("float32")
glacier_dem, _ = glacier_on_dem(dem_tags, dem.shape, glacier, glacier_tags)
glacier4 = glacier_dem[: r4 * DOWN, : c4 * DOWN].reshape(r4, DOWN, c4, DOWN).max(axis=(1, 3)).astype("uint8")

dem4.tofile(DATA_OUT / "terrain.bin")
slope4.tofile(DATA_OUT / "slope.bin")
glacier4.tofile(DATA_OUT / "glacier.bin")

# channel
profile = pd.read_csv(DATA / "tpdc07_channel" / "main_channel_profile.csv")
channel = []
for _, r in profile.iterrows():
    x = (float(r["lon"]) - lon0) * 111.320 * math.cos(math.radians(lat0))
    z = -(float(r["lat"]) - lat0) * 110.574
    channel.append({"x": round(x, 4), "z": round(z, 4), "y": round(float(r["elevation_m"]), 1), "d_km": round(float(r["distance_m"]) / 1000, 4)})
channel_meta = {
    "length_km": float(profile["distance_m"].max() / 1000),
    "drop_m": float(profile["elevation_m"].max() - profile["elevation_m"].min()),
    "points": len(channel),
    "source": channel[0],
    "outlet": channel[-1],
}

# sites
sites = [
    {"id": "source", "name": "主沟源头", "x": channel[0]["x"], "z": channel[0]["z"], "y": channel[0]["y"], "kind": "source", "note": "D8 主流路源头"},
    {"id": "outlet", "name": "吉隆口岸/沟口", "x": channel[-1]["x"], "z": channel[-1]["z"], "y": channel[-1]["y"], "kind": "outlet", "note": "主沟出口，海拔约 1621 m"},
    {"id": "event", "name": "2026 事件源区（近似）", "x": (85.53 - lon0) * 111.320 * math.cos(math.radians(lat0)), "z": -(28.29 - lat0) * 110.574, "y": 5200, "kind": "event", "note": "85.53E,28.29N 附近；仅示意，不是精确源点"},
]
# glacier points (subsample)
gpts = []
for i in range(0, r4, 2):
    for j in range(0, c4, 2):
        if glacier4[i, j]:
            gpts.append({"x": round((j / max(1, c4 - 1) - 0.5) * (c4 - 1) * dx_km, 4), "z": round((i / max(1, r4 - 1) - 0.5) * (r4 - 1) * dy_km, 4)})
(DATA_OUT / "glacier_points.json").write_text(json.dumps(gpts), encoding="utf-8")
(DATA_OUT / "channel.json").write_text(json.dumps({"meta": channel_meta, "points": channel}, ensure_ascii=False), encoding="utf-8")
(DATA_OUT / "sites.json").write_text(json.dumps(sites, ensure_ascii=False), encoding="utf-8")

# Q3 warning / interval
def clean_json(obj):
    if isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


warning = pd.read_csv(BASE / "03_编程手" / "Q3" / "实验结果" / "q3_warning_timeline.csv")
interval = pd.read_csv(BASE / "03_编程手" / "Q3" / "实验结果" / "q3_interval_summary.csv")
cases = pd.read_csv(BASE / "03_编程手" / "Q3" / "实验结果" / "q3_event_cases.csv")
q3 = {
    "warning": warning.to_dict("records"),
    "interval": interval.to_dict("records"),
    "cases": cases.to_dict("records"),
    "note": "Q3 是条件预测区间，不是事件级 95% 覆盖率；2026 有 4% 降雨分支。",
}
(WEB / "data" / "q3.json").write_text(json.dumps(clean_json(q3), ensure_ascii=False, indent=2), encoding="utf-8")

# 外采驱动（Q3 驱动长表）与数据来源说明
drivers = pd.read_csv(BASE / "03_编程手" / "Q3" / "实验结果" / "q3_drivers.csv")
drivers = drivers[drivers["year"] == 2026]
drv_obj = {"event": 2026, "window_start": str(drivers["timestamp_bjt"].min()), "window_end": str(drivers["timestamp_bjt"].max()), "drivers": {}}
for d in ["station", "era5", "nasa", "chirps"]:
    sub = drivers[drivers["driver"] == d].sort_values("timestamp_bjt")
    if len(sub) == 0:
        continue
    drv_obj["drivers"][d] = {
        "time": sub["timestamp_bjt"].tolist(),
        "precip_mm_h": [round(float(v), 4) for v in sub["precip_mm_h"]],
        "cum_mm": [round(float(v), 3) for v in sub["precip_mm_h"].fillna(0).cumsum()],
        "api72_mm": [round(float(v), 3) if pd.notna(v) else None for v in sub["api72_mm"]],
        "note": "CHIRPS 为日值均匀展示，不是小时观测" if d == "chirps" else "外采/站点驱动",
    }
(WEB / "data" / "drivers.json").write_text(json.dumps(clean_json(drv_obj), ensure_ascii=False, indent=2), encoding="utf-8")

pop = json.loads((BASE / "03_编程手" / "数据获取" / "data" / "processed" / "tpdc08_population" / "summary.json").read_text(encoding="utf-8"))
s1 = pd.read_csv(BASE / "03_编程手" / "数据获取" / "data" / "tables" / "copernicus_s1.csv")
s2 = pd.read_csv(BASE / "03_编程手" / "数据获取" / "data" / "tables" / "copernicus_s2.csv")
prov = {
    "attachment": [
        "TPDC-01 站点小时气象/土壤（24 CSV）",
        "TPDC-02 温度（21 XLSX）",
        "TPDC-03 冰川变化（168 TIFF/4 时段）",
        "TPDC-04 冰川厚度/速度（10 变量）",
        "TPDC-05 土地覆盖（2023，编码 1–10 无图例）",
        "TPDC-06 历史沟域（84 多边形/23 在 DEM 内）",
        "TPDC-07 DEM/沟道（30 m）",
        "TPDC-08 吉隆县人口普查（县级）",
    ],
    "external": [
        "Open-Meteo archive（2026-08-20→08-28，216 h）",
        "NASA POWER（2026-08-20→08-28，216 h，LST）",
        "CHIRPS v2.0 日值（事件窗口，0.05°）",
        f"Copernicus S1 元数据 {len(s1)} 景（仅 bbox，无影像）",
        f"Copernicus S2 元数据 {len(s2)} 景（仅 bbox，无影像）",
        "事件目录（官方/新闻；2 本地 + 1 区域 GLOF + 1 地震）",
    ],
    "model": ["Q2 WOE 相对易发性", "Q3 A+C 触发/预警集合", "Q4 2D HLL/Voellmy 首轮"],
    "population": {"合计": pop.get("合计"), "人口数": pop.get("人口数"), "urban": pop.get("urban"), "rural": pop.get("rural"), "households": pop.get("households"), "note": "县级；不能精确到个人/居民点"},
    "copernicus": {"s1": len(s1), "s2": len(s2), "note": "只取元数据，未下载影像；不能当灾后范围真值"},
}
(WEB / "data" / "provenance.json").write_text(json.dumps(clean_json(prov), ensure_ascii=False, indent=2), encoding="utf-8")

meta = {
    "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
    "dem_shape": [int(rows), int(cols)],
    "grid_shape": [int(r4), int(c4)],
    "downsample": DOWN,
    "dx_km": round(dx_km, 6),
    "dy_km": round(dy_km, 6),
    "width_km": round((c4 - 1) * dx_km * DOWN, 3),
    "depth_km": round((r4 - 1) * dy_km * DOWN, 3),
    "west": west,
    "north": north,
    "lat0": lat0,
    "lon0": lon0,
    "z_min": float(np.nanmin(dem4)),
    "z_max": float(np.nanmax(dem4)),
    "vertical_scale": 2.2,
    "notes": [
        "地形为 30m DEM 4x 块平均；用于浏览器预览，不用于定量坡度计算",
        "冰川点来自 TPDC-04 glacier_mask 的 UTM45N→WGS84 最近邻采样",
        "事件源区为近似 marker，不是精确坐标",
    ],
}
(DATA_OUT / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"meta": meta, "channel": channel_meta, "glacier_points": len(gpts), "sites": len(sites)}, ensure_ascii=False, indent=2))
