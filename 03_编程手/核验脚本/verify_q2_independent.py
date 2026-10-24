# -*- coding: utf-8 -*-
"""
Q2 独立复算（建模手核验脚本）
- 不 import / 不调用 03_编程手/Q2/源代码/q2_*.py
- 独立复算 V1–V12 公式、G1–G6/G8 几何、WOE 全局/2×2/3×3 AUC、冰崩筛选计数
- 输出：03_编程手/核验往来/q2_recompute/

说明：
- 仅用 PIL/numpy/pandas，不依赖 rasterio/geopandas。
- G7 不做精确距离变换；只核验数量级（G7 只作描述，不进主模型）。
- LOO 需要逐折重训 WOE；本脚本只复算 2×2/3×3 空间块，LOO 不复算。
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

ROOT = Path(r"C:\Users\21722\Desktop\妈妈杯秋季赛\MTMCM比赛协作")
DATA = ROOT / "03_编程手" / "数据获取" / "data" / "processed"
Q2OUT = ROOT / "03_编程手" / "Q2" / "实验结果"
OUT = ROOT / "03_编程手" / "核验往来" / "q2_recompute"
OUT.mkdir(parents=True, exist_ok=True)

DEM = DATA / "tpdc07_dem" / "dem_core_30m.tif"
SLOPE = DATA / "tpdc07_dem" / "slope_deg.tif"
CHANNEL = DATA / "tpdc07_dem" / "channel_mask_acc1000.tif"
GLACIER = DATA / "tpdc04_glacier" / "glacier_mask.tif"
G_DEM = DATA / "tpdc04_glacier" / "dem.tif"
G_SLOPE = DATA / "tpdc04_glacier" / "slope.tif"
G_THICK = DATA / "tpdc04_glacier" / "thickness.tif"
G_V = DATA / "tpdc04_glacier" / "v.tif"
SCORE = DATA / "q2_susceptibility" / "q2_susceptibility_score.tif"
ACCUM = DATA / "tpdc07_dem" / "flow_accumulation_cells.tif"
LC = DATA / "tpdc05_landcover" / "jilong_LUCD_2023.tif"
GULLY = DATA / "tpdc06_points" / "tpdc06_points.geojson"
REF_GEO = Q2OUT / "q2_geometry_factors.csv"
REF_SPATIAL = Q2OUT / "q2_spatial_summary.json"


def load_tiff(path):
    im = Image.open(path)
    arr = np.asarray(im)
    tags = im.tag_v2
    west = float(tags[33922][3])
    north = float(tags[33922][4])
    sx = float(tags[33550][0])
    sy = float(tags[33550][1])
    return arr, (west, north, sx, sy)


def rasterize(feature, rows, cols, west, north, sx, sy):
    img = Image.new("L", (cols, rows), 0)
    draw = ImageDraw.Draw(img)
    geom = feature.get("geometry") or {}
    polys = [geom.get("coordinates") or []] if geom.get("type") == "Polygon" else geom.get("coordinates") or []
    for rings in polys:
        for ring in rings:
            pts = [((float(lon) - west) / sx, (north - float(lat)) / sy) for lon, lat in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=1)
    return np.asarray(img) == 1


def auc_score(y, s):
    y = np.asarray(y, dtype=bool)
    s = np.asarray(s, dtype=float)
    ok = np.isfinite(s)
    y = y[ok]
    s = s[ok]
    n1 = int(y.sum())
    n0 = int((~y).sum())
    if n1 == 0 or n0 == 0:
        return None, n1, n0
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    # average ranks for ties
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    auc = (ranks[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)
    return float(auc), n1, n0


def block_auc(presence, score, row_edges, col_edges, scheme):
    out = []
    for ri in range(len(row_edges) - 1):
        for ci in range(len(col_edges) - 1):
            rs, re = row_edges[ri], row_edges[ri + 1]
            cs, ce = col_edges[ci], col_edges[ci + 1]
            y = presence[rs:re, cs:ce]
            s = score[rs:re, cs:ce]
            auc, n1, n0 = auc_score(y.ravel(), s.ravel())
            out.append({"scheme": scheme, "block": f"r{ri}c{ci}", "test_presence": n1,
                        "test_background": n0, "auc": auc})
    return out


def main():
    dem, dem_gt = load_tiff(DEM)
    slope, _ = load_tiff(SLOPE)
    channel, _ = load_tiff(CHANNEL)
    score, _ = load_tiff(SCORE)
    accum, _ = load_tiff(ACCUM)
    lc, lc_tags = load_tiff(LC)
    rows, cols = dem.shape
    west, north, sx, sy = dem_gt
    print("DEM", dem.shape, dem_gt, "score", score.shape)

    geoms = json.load(open(GULLY, encoding="utf-8"))["features"]
    gully_masks = []
    for f in geoms:
        m = rasterize(f, rows, cols, west, north, sx, sy)
        gully_masks.append(m)
    presence_all = np.zeros((rows, cols), dtype=bool)
    for m in gully_masks:
        presence_all |= m
    print("gully polygons", len(gully_masks), "presence cells", int(presence_all.sum()))

    # 23 in DEM
    in_dem = [(i, int(m.sum())) for i, m in enumerate(gully_masks) if m.sum() > 0]
    print("in DEM", len(in_dem), [x[0] for x in in_dem])

    cell_area_km2 = 0.000835
    edge_m = 28.955  # (27.2+30.71)/2

    # ---------- G1-G6/G8 independent ----------
    rows_geo = []
    for idx, (i, ncell) in enumerate(in_dem):
        f = geoms[i]
        m = gully_masks[i]
        z = dem[m]
        z = z[np.isfinite(z) & (z > -1000)]
        sl = slope[m]
        sl = sl[np.isfinite(sl)]
        ch = channel[m] > 0
        n_ch = int(ch.sum())
        area = ncell * cell_area_km2
        l_ch = n_ch * edge_m / 1000.0
        g5 = l_ch / area if area > 0 else np.nan
        if n_ch > 0:
            zch = dem[m][ch]
            drop = float(np.nanmax(zch) - np.nanmin(zch))
            g6 = drop / (10 * l_ch) if l_ch > 0 else np.nan
        else:
            g6 = np.nan
        rows_geo.append({
            "id": i + 1,
            "Code": f["properties"].get("Code", ""),
            "cells": ncell,
            "G1_slope_mean": float(np.mean(sl)) if len(sl) else np.nan,
            "G2_slope_p90": float(np.percentile(sl, 90)) if len(sl) else np.nan,
            "G3_relief_m": float(z.max() - z.min()) if len(z) else np.nan,
            "G4_HI": float((z.mean() - z.min()) / (z.max() - z.min())) if len(z) and z.max() > z.min() else np.nan,
            "G5_drainage_density": float(g5),
            "G6_channel_gradient_pct": float(g6) if np.isfinite(g6) else np.nan,
            "channel_cells": n_ch,
        })
    geo = pd.DataFrame(rows_geo)
    geo.to_csv(OUT / "q2_recompute_geometry.csv", index=False, encoding="utf-8-sig")

    ref = pd.read_csv(REF_GEO)
    # match by Code (fallback id)
    ref_by_code = ref.set_index("Code")
    comp = []
    for r in geo.itertuples():
        if r.Code not in ref_by_code.index:
            continue
        rr = ref_by_code.loc[r.Code]
        for c in ["G1_slope_mean", "G2_slope_p90", "G3_relief_m", "G4_HI",
                  "G5_drainage_density", "G6_channel_gradient_pct"]:
            a = getattr(r, c)
            b = rr[c]
            if pd.notna(a) and pd.notna(b):
                comp.append({"Code": r.Code, "factor": c, "recompute": float(a), "reference": float(b),
                             "abs_diff": abs(float(a) - float(b))})
    compdf = pd.DataFrame(comp)
    compdf.to_csv(OUT / "q2_recompute_geometry_diff.csv", index=False, encoding="utf-8-sig")

    # G8: resample glacier mask to DEM grid via UTM forward + nearest neighbor
    gl_mask, (gx0, gy0, gdx, gdy) = load_tiff(GLACIER)
    # UTM45N forward (WGS84), central meridian 87E
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lon0 = math.radians(87.0)

    def utm_forward(lon, lat):
        phi = np.radians(lat)
        lam = np.radians(lon)
        n = a / np.sqrt(1 - e2 * np.sin(phi) ** 2)
        t = np.tan(phi) ** 2
        c = ep2 * np.cos(phi) ** 2
        aa = np.cos(phi) * (lam - lon0)
        m = a * ((1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
                 - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * np.sin(2 * phi)
                 + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * np.sin(4 * phi)
                 - (35 * e2**3 / 3072) * np.sin(6 * phi))
        x = k0 * n * (aa + (1 - t + c) * aa**3 / 6 + (5 - 18 * t + t**2 + 72 * c - 58 * ep2) * aa**5 / 120) + 500000.0
        y = k0 * (m + n * np.tan(phi) * (aa**2 / 2 + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24
                                          + (61 - 58 * t + t**2 + 600 * c - 330 * ep2) * aa**6 / 720))
        return x, y

    rr, cc = np.indices((rows, cols))
    lon = west + (cc + 0.5) * sx
    lat = north - (rr + 0.5) * sy
    ux, uy = utm_forward(lon, lat)
    gcol = np.rint((ux - gx0) / gdx).astype(np.int64)
    grow = np.rint((gy0 - uy) / gdy).astype(np.int64)
    inside = (grow >= 0) & (grow < gl_mask.shape[0]) & (gcol >= 0) & (gcol < gl_mask.shape[1])
    gl_on_dem = np.zeros((rows, cols), dtype=np.float32)
    gl_on_dem[inside] = gl_mask[grow[inside], gcol[inside]]
    gl_on_dem[gl_on_dem < 0] = np.nan

    g8 = []
    for r in geo.itertuples():
        m = gully_masks[r.id - 1]
        vals = gl_on_dem[m]
        vals = vals[np.isfinite(vals)]
        frac = float(np.mean(vals >= 0.5)) if len(vals) else np.nan
        g8.append({"Code": r.Code, "G8_recompute": frac,
                   "G8_reference": float(ref_by_code.loc[r.Code, "G8_glacier_fraction"]) if r.Code in ref_by_code.index else np.nan})
    g8df = pd.DataFrame(g8)
    g8df.to_csv(OUT / "q2_recompute_g8.csv", index=False, encoding="utf-8-sig")

    # ---------- AUC：独立重拟合 WOE + 2x2/3x3 空间块 ----------
    # 全局 score 栅格只作对照；块 CV 必须在训练块内重拟合 WOE，不能直接切全局 score。
    lc_west, lc_north, lc_sx, lc_sy = lc_tags
    rr, cc = np.indices((rows, cols))
    lon = west + (cc + 0.5) * sx
    lat = north - (rr + 0.5) * sy
    lcol = np.rint((lon - lc_west) / lc_sx).astype(np.int64)
    lrow = np.rint((lc_north - lat) / lc_sy).astype(np.int64)
    inside_lc = (lrow >= 0) & (lrow < lc.shape[0]) & (lcol >= 0) & (lcol < lc.shape[1])
    lc_on_dem = np.zeros((rows, cols), dtype=np.int16)
    lc_on_dem[inside_lc] = lc[lrow[inside_lc], lcol[inside_lc]].astype(np.int16)

    valid_score = np.isfinite(score) & (score > -9998)
    valid_cov = valid_score & np.isfinite(dem) & (dem > -1000) & np.isfinite(slope) & np.isfinite(accum)
    presence = presence_all & valid_cov
    background = valid_cov & ~presence
    print("presence/background", int(presence.sum()), int(background.sum()), "valid", int(valid_cov.sum()))

    y_score = presence[valid_score].astype(bool)
    s_score = score[valid_score]
    global_auc_score, n1_score, n0_score = auc_score(y_score, s_score)

    def continuous_bins(values, n=5):
        finite = values[np.isfinite(values)]
        edges = np.unique(np.quantile(finite, np.linspace(0, 1, n + 1)))
        if len(edges) < 2:
            return np.zeros(values.shape, dtype=int), [float(edges[0]) if len(edges) else 0.0]
        bins = np.digitize(values, edges[1:-1], right=False).astype(int)
        return np.clip(bins, 0, len(edges) - 2), [float(x) for x in edges]

    cov_bins = []
    cov_names = []
    for name, arr in [("slope_deg", slope), ("elevation_m", dem), ("log1p_accum", np.log1p(accum))]:
        bins, _ = continuous_bins(arr, 5)
        cov_bins.append(bins)
        cov_names.append(name)
    cov_bins.append(lc_on_dem.astype(int))
    cov_names.append("landcover")

    def woe_fit(pres, back, bins_list):
        p_total = int(pres.sum())
        b_total = int(back.sum())
        out = []
        for bins in bins_list:
            nb = int(bins.max())
            p_counts = np.bincount(bins[pres].astype(np.int64), minlength=nb + 1)
            q_counts = np.bincount(bins[back].astype(np.int64), minlength=nb + 1)
            w = np.zeros(nb + 1, dtype=float)
            for b in range(nb + 1):
                p = int(p_counts[b])
                q = int(q_counts[b])
                pr = (p + 0.5) / (p_total + 0.5 * (nb + 1))
                br = (q + 0.5) / (b_total + 0.5 * (nb + 1))
                w[b] = math.log(pr / br)
            out.append(w)
        return out

    def woe_score(bins_list, weights):
        s = np.zeros((rows, cols), dtype=float)
        for bins, w in zip(bins_list, weights):
            s += w[bins]
        return s

    w_global = woe_fit(presence, background, cov_bins)
    score_woe = woe_score(cov_bins, w_global)
    global_auc_woe, n1_woe, n0_woe = auc_score(presence.ravel(), score_woe.ravel())

    def refit_blocks(parts, scheme):
        r_edges = np.linspace(0, rows, parts + 1).astype(int)
        c_edges = np.linspace(0, cols, parts + 1).astype(int)
        out = []
        for bi in range(parts):
            for bj in range(parts):
                test = np.zeros((rows, cols), dtype=bool)
                test[r_edges[bi]:r_edges[bi + 1], c_edges[bj]:c_edges[bj + 1]] = True
                tp = presence & test
                tb = background & test
                if tp.sum() < 5 or tb.sum() < 100:
                    out.append({"scheme": scheme, "block": f"r{bi}c{bj}", "test_presence": int(tp.sum()),
                                "test_background": int(tb.sum()), "auc": None})
                    continue
                trp = presence & ~test
                trb = background & ~test
                ws = woe_fit(trp, trb, cov_bins)
                sc = woe_score(cov_bins, ws)
                # 注：auc_score 里 y 与 s 必须同一批像元；用整块 test 的 y/score
                yb = tp[test].astype(bool)
                sb = sc[test]
                a, _, _ = auc_score(yb, sb)
                out.append({"scheme": scheme, "block": f"r{bi}c{bj}", "test_presence": int(tp.sum()),
                            "test_background": int(tb.sum()), "auc": a})
        return out

    blocks2 = refit_blocks(2, "2x2")
    blocks3 = refit_blocks(3, "3x3")
    pd.DataFrame(blocks2 + blocks3).to_csv(OUT / "q2_recompute_spatial_cv.csv", index=False, encoding="utf-8-sig")

    # ---------- V1-V12 formulas ----------
    def mcr(beta, phi, c=0.0, gamma=20.0, z=2.0, r=0.5):
        b = math.radians(beta); p = math.radians(phi)
        return (1 / r) * (1 - math.tan(b) / math.tan(p) + c / (gamma * z * math.cos(b) ** 2 * math.tan(p)))

    def fs(beta, z, c, phi, gamma, zw):
        b = math.radians(beta); p = math.radians(phi)
        return (c + (gamma * z - 9.81 * zw) * math.cos(b) ** 2 * math.tan(p)) / (gamma * z * math.sin(b) * math.cos(b))

    v = {
        "V1_mcr": mcr(30, 35),
        "V2_fs": fs(30, 2, 5, 30, 20, 1),
        "V3_ic": 10 * 24 ** -0.5,
        "V5_mcr": mcr(10, 35),
        "V7_hi": (1800 - 1000) / (3000 - 1000),
        "V8_dd": 10 / 20,
        "V9_g8": 25 / 100,
        "V10a": 0.8 * 1,
        "V10b": 0.8 * 0,
        "V11": 3992.74 / (10 * 49.622),
    }
    v["V4_api"] = float(np.dot(np.array([1, 2, 3])[::-1], 0.9 ** np.arange(3)))
    v["V12a"] = 1 if (5200 >= 5000 and 30 >= 25 and 50 >= 20 and 8 >= 5) else 0
    v["V12b"] = 1 if (4800 >= 5000 and 30 >= 25 and 50 >= 20 and 8 >= 5) else 0

    # ---------- ice screening ----------
    gdem, _ = load_tiff(G_DEM)
    gslope, _ = load_tiff(G_SLOPE)
    gth, _ = load_tiff(G_THICK)
    gv, _ = load_tiff(G_V)
    valid = np.isfinite(gdem) & (gdem > -1000) & np.isfinite(gslope) & np.isfinite(gth) & np.isfinite(gv)
    z_ok = gdem >= 5000
    sl_ok = gslope >= 25
    th_ok = gth >= 20
    v_ok = gv >= 5
    ice = {
        "cells": int(valid.sum()),
        "z_ge_5000": int((valid & z_ok).sum()),
        "slope_ge_25": int((valid & sl_ok).sum()),
        "thickness_ge_20": int((valid & th_ok).sum()),
        "velocity_ge_5": int((valid & v_ok).sum()),
        "all_four": int((valid & z_ok & sl_ok & th_ok & v_ok).sum()),
        "z_max": float(np.nanmax(gdem[valid])),
        "slope_max": float(np.nanmax(gslope[valid])),
        "thickness_max": float(np.nanmax(gth[valid])),
        "velocity_max": float(np.nanmax(gv[valid])),
    }

    summary = {
        "rows": int(rows), "cols": int(cols),
        "gully_polygons": len(gully_masks),
        "gullies_in_dem": len(in_dem),
        "presence_cells": int(presence_all.sum()),
        "geometry": {
            "n": len(geo),
            "g6_nan": int(geo["G6_channel_gradient_pct"].isna().sum()),
            "g6_min": float(geo["G6_channel_gradient_pct"].min()),
            "g6_max": float(geo["G6_channel_gradient_pct"].max()),
            "g8_all_zero": bool((g8df["G8_recompute"] == 0).all()),
            "max_abs_diff": {c: float(compdf[compdf["factor"] == c]["abs_diff"].max()) for c in compdf["factor"].unique()},
        },
        "auc": {
            "global_score_raster": global_auc_score,
            "global_woe_refit": global_auc_woe,
            "presence": n1_score,
            "background": n0_score,
        },
        "presence_cells": int(presence.sum()),
        "background_cells": int(background.sum()),
        "blocks2": blocks2,
        "blocks3": blocks3,
        "v": v,
        "ice": ice,
    }
    with open(OUT / "q2_recompute_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=float)

    lines = []
    lines.append("# Q2 独立复算报告（建模手）\n")
    lines.append("> 脚本：`03_编程手/核验脚本/verify_q2_independent.py`；不 import/调用 `q2_*.py`。\n")
    lines.append("## 1. 规模\n")
    lines.append(f"- DEM {rows}×{cols}；gully 多边形 {len(gully_masks)}；DEM 内 {len(in_dem)}；presence 像元 {int(presence_all.sum())}\n")
    lines.append("## 2. 几何复算\n")
    lines.append(f"- G6 NaN：{summary['geometry']['g6_nan']}/23；G8 全 0：{summary['geometry']['g8_all_zero']}\n")
    lines.append(f"- 与编程手最大绝对差：{summary['geometry']['max_abs_diff']}\n")
    lines.append("## 3. AUC\n")
    lines.append(f"- 全局 score 栅格：{global_auc_score:.6f}（presence {n1_score}, background {n0_score}）\n")
    lines.append(f"- 全局 WOE 重拟合：{global_auc_woe:.6f}\n")
    lines.append("| scheme | block | presence | background | AUC |\n|---|---:|---:|---:|\n")
    for b in blocks2 + blocks3:
        lines.append(f"| {b['scheme']} | {b['block']} | {b['test_presence']} | {b['test_background']} | {b['auc']} |\n")
    lines.append("## 4. V1–V12 / 冰崩\n")
    lines.append("```json\n" + json.dumps(v, ensure_ascii=False, indent=2, default=float) + "\n```\n")
    lines.append("```json\n" + json.dumps(ice, ensure_ascii=False, indent=2, default=float) + "\n```\n")
    (OUT / "q2_recompute_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=float))


if __name__ == "__main__":
    main()
