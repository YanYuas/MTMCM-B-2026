from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parents[3]
DATA = BASE / "03_编程手" / "数据获取" / "data" / "processed"
OUT = BASE / "03_编程手" / "Q2" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)


def load_tiff(path: Path):
    im = Image.open(path)
    return np.asarray(im), im.tag_v2


def grid(tags):
    return float(tags[33922][3]), float(tags[33922][4]), float(tags[33550][0]), float(tags[33550][1])


def utm45_forward(lon, lat):
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lon0 = math.radians(87.0)
    phi = np.radians(lat)
    lam = np.radians(lon)
    n = a / np.sqrt(1 - e2 * np.sin(phi) ** 2)
    t = np.tan(phi) ** 2
    c = ep2 * np.cos(phi) ** 2
    aa = np.cos(phi) * (lam - lon0)
    m = a * (
        (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
        - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * np.sin(2 * phi)
        + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * np.sin(4 * phi)
        - (35 * e2**3 / 3072) * np.sin(6 * phi)
    )
    x = k0 * n * (aa + (1 - t + c) * aa**3 / 6 + (5 - 18 * t + t**2 + 72 * c - 58 * ep2) * aa**5 / 120) + 500000.0
    y = k0 * (m + n * np.tan(phi) * (aa**2 / 2 + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24 + (61 - 58 * t + t**2 + 600 * c - 330 * ep2) * aa**6 / 720))
    return x, y


def rasterize(feature, rows, cols, west, north, sx, sy):
    image = Image.new("L", (cols, rows), 0)
    draw = ImageDraw.Draw(image)
    geom = feature.get("geometry") or {}
    polys = [geom.get("coordinates") or []] if geom.get("type") == "Polygon" else geom.get("coordinates") or []
    for rings in polys:
        for ring in rings:
            pts = [((float(lon) - west) / sx, (north - float(lat)) / sy) for lon, lat in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=1)
    return np.asarray(image) == 1


def landcover_on_dem(dem_tags, dem_shape, lc, lc_tags):
    west, north, sx, sy = grid(dem_tags)
    lc_west, lc_north, lc_sx, lc_sy = grid(lc_tags)
    rows, cols = dem_shape
    rr, cc = np.indices((rows, cols))
    lon = west + (cc + 0.5) * sx
    lat = north - (rr + 0.5) * sy
    col = np.rint((lon - lc_west) / lc_sx).astype("int64")
    row = np.rint((lc_north - lat) / lc_sy).astype("int64")
    inside = (row >= 0) & (row < lc.shape[0]) & (col >= 0) & (col < lc.shape[1])
    out = np.zeros((rows, cols), dtype=lc.dtype)
    out[inside] = lc[row[inside], col[inside]]
    return out


def glacier_on_dem(dem_tags, dem_shape, glacier, glacier_tags):
    west, north, sx, sy = grid(dem_tags)
    gx0, gy0, gdx, gdy = grid(glacier_tags)
    rows, cols = dem_shape
    rr, cc = np.indices((rows, cols))
    lon = west + (cc + 0.5) * sx
    lat = north - (rr + 0.5) * sy
    x, y = utm45_forward(lon, lat)
    gcol = np.rint((x - gx0) / gdx).astype("int64")
    grow = np.rint((gy0 - y) / abs(gdy)).astype("int64")
    inside = (grow >= 0) & (grow < glacier.shape[0]) & (gcol >= 0) & (gcol < glacier.shape[1])
    out = np.zeros((rows, cols), dtype=bool)
    vals = np.zeros((rows, cols), dtype=float)
    vals[inside] = glacier[grow[inside], gcol[inside]]
    out[inside] = vals[inside] == 1
    return out, (x.min(), x.max(), y.min(), y.max())


def chamfer_distance(seed: np.ndarray) -> np.ndarray:
    rows, cols = seed.shape
    inf = 1e12
    d = np.where(seed, 0.0, inf)
    w1, w2 = 1.0, math.sqrt(2.0)
    for i in range(1, rows):
        for j in range(cols):
            best = d[i, j]
            best = min(best, d[i - 1, j] + w1)
            if j > 0:
                best = min(best, d[i - 1, j - 1] + w2, d[i, j - 1] + w1)
            if j + 1 < cols:
                best = min(best, d[i - 1, j + 1] + w2)
            d[i, j] = best
    for i in range(rows - 2, -1, -1):
        for j in range(cols - 1, -1, -1):
            best = d[i, j]
            best = min(best, d[i + 1, j] + w1)
            if j > 0:
                best = min(best, d[i + 1, j - 1] + w2)
            if j + 1 < cols:
                best = min(best, d[i + 1, j + 1] + w2, d[i, j + 1] + w1)
            d[i, j] = best
    return d


def main() -> None:
    dem, dem_tags = load_tiff(DATA / "tpdc07_dem" / "dem_core_30m.tif")
    slope, _ = load_tiff(DATA / "tpdc07_dem" / "slope_deg.tif")
    accum, _ = load_tiff(DATA / "tpdc07_dem" / "flow_accumulation_cells.tif")
    channel, _ = load_tiff(DATA / "tpdc07_dem" / "channel_mask_acc1000.tif")
    lc, lc_tags = load_tiff(DATA / "tpdc05_landcover" / "jilong_LUCD_2023.tif")
    glacier, glacier_tags = load_tiff(DATA / "tpdc04_glacier" / "glacier_mask.tif")
    geojson = json.loads((DATA / "tpdc06_points" / "tpdc06_points.geojson").read_text(encoding="utf-8"))
    west, north, sx, sy = grid(dem_tags)
    rows, cols = dem.shape
    dx = abs(sx) * 111320.0 * math.cos(math.radians(north - sy * rows / 2))
    dy = abs(sy) * 110574.0
    cell_area_km2 = dx * dy / 1e6
    lc_on_dem = landcover_on_dem(dem_tags, dem.shape, lc, lc_tags)
    glacier_dem, utm_bbox = glacier_on_dem(dem_tags, dem.shape, glacier, glacier_tags)
    dist = chamfer_distance(glacier_dem) * math.sqrt(dx * dy) / 1000.0  # km

    rows_out = []
    for order, feature in enumerate(geojson["features"], start=1):
        props = feature.get("properties") or {}
        mask = rasterize(feature, rows, cols, west, north, sx, sy)
        cells = int(mask.sum())
        if cells == 0:
            continue
        z = dem[mask]
        s = slope[mask]
        ch = channel[mask] == 1
        n_ch = int(ch.sum())
        area_km2 = cells * cell_area_km2
        l_ch = n_ch * math.sqrt(dx * dy) / 1000.0
        if n_ch:
            zch = dem[mask][ch]
            drop = float(np.nanmax(zch) - np.nanmin(zch))
        else:
            drop = float("nan")
        rows_out.append(
            {
                "id": order,
                "Code": props.get("Code", ""),
                "Name": props.get("Name", ""),
                "cells": cells,
                "area_km2": round(area_km2, 4),
                "G1_slope_mean": round(float(np.nanmean(s)), 3),
                "G2_slope_p90": round(float(np.nanpercentile(s, 90)), 3),
                "G3_relief_m": round(float(np.nanmax(z) - np.nanmin(z)), 2),
                "G4_HI": round(float((np.nanmean(z) - np.nanmin(z)) / (np.nanmax(z) - np.nanmin(z))), 4),
                "G5_drainage_density": round(float(l_ch / area_km2), 4) if area_km2 else None,
                "G6_channel_gradient_pct": round(float(drop / (10 * l_ch)), 3) if n_ch and l_ch > 0 else None,
                "G7_dist_to_glacier_km": round(float(np.nanmin(dist[mask])), 3),
                "G8_glacier_fraction": round(float(glacier_dem[mask].mean()), 4),
                "channel_cells": n_ch,
                "lc_majority": int(pd.Series(lc_on_dem[mask][lc_on_dem[mask] > 0]).mode().iloc[0]) if (lc_on_dem[mask] > 0).any() else None,
            }
        )

    df = pd.DataFrame(rows_out)
    df.to_csv(OUT / "q2_geometry_factors.csv", index=False, encoding="utf-8-sig")
    summary = {
        "gullies": len(df),
        "dem_shape": [int(rows), int(cols)],
        "pixel_m": [round(dx, 2), round(dy, 2)],
        "glacier_cells_on_dem": int(glacier_dem.sum()),
        "utm_bbox": [round(float(x), 1) for x in utm_bbox],
        "notes": [
            "几何统计在 DEM 原生 EPSG:4326 网格上做，面积按中心纬度近似米制像元",
            "G5 L_ch 用 channel_mask 像元数×像元边长近似；G6 drop 用沟域内沟道像元 max-min 高程，均为工程近似",
            "G7 用 chamfer 距离（像元单位）乘平均像元边长；不是精确测地距离",
            "G8 用 TPDC-04 glacier_mask 经 UTM45N 正变换最近邻采样到 DEM 网格",
            "土地覆盖 0=nodata；lc_majority 只在 >0 中取众数，不代表官方类别名",
        ],
    }
    (OUT / "q2_geometry_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(df.to_string(index=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
