from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageFilter

import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from q2_geometry import DATA, grid, landcover_on_dem, load_tiff, rasterize, utm45_forward  # noqa: E402

BASE = HERE.parents[2]
OUT = BASE / "03_编程手" / "Q2" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)


def continuous_bins(values: np.ndarray, n: int = 5):
    finite = values[np.isfinite(values)]
    edges = np.unique(np.quantile(finite, np.linspace(0, 1, n + 1)))
    if len(edges) < 2:
        return np.zeros(values.shape, dtype=int), [float(edges[0]) if len(edges) else 0.0]
    bins = np.digitize(values, edges[1:-1], right=False).astype(int)
    return np.clip(bins, 0, len(edges) - 2), [float(x) for x in edges]


def woe_values(bins: np.ndarray, presence: np.ndarray, background: np.ndarray, n_bins: int):
    p_total = int(presence.sum())
    b_total = int(background.sum())
    woe = np.zeros(n_bins + 1)
    rows = []
    for b in range(n_bins + 1):
        p = int(((bins == b) & presence).sum())
        q = int(((bins == b) & background).sum())
        pr = (p + 0.5) / (p_total + 0.5 * (n_bins + 1))
        br = (q + 0.5) / (b_total + 0.5 * (n_bins + 1))
        woe[b] = math.log(pr / br)
        rows.append({"bin": b, "presence_cells": p, "background_cells": q, "woe": round(float(woe[b]), 4)})
    return woe, rows


def rank_auc(pos: np.ndarray, neg: np.ndarray):
    n1, n0 = len(pos), len(neg)
    if n1 == 0 or n0 == 0:
        return None
    s = np.concatenate([pos, neg])
    order = np.argsort(s, kind="mergesort")
    sorted_s = s[order]
    ranks = np.empty(len(s))
    i = 0
    while i < len(s):
        j = i + 1
        while j < len(s) and sorted_s[j] == sorted_s[i]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2
        i = j
    return float((ranks[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def pr_auc(pos: np.ndarray, neg: np.ndarray):
    if len(pos) == 0 or len(neg) == 0:
        return None
    s = np.concatenate([pos, neg])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    order = np.argsort(-s, kind="mergesort")
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / len(pos)
    recall_prev = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - recall_prev) * precision))


def score_from_woe(bins, woes):
    score = np.zeros(bins[0].shape, dtype=float)
    for b, w in zip(bins, woes):
        score += w[b]
    return score


def coarse_buffer(mask: np.ndarray, radius_m: float = 2000.0, factor: int = 4):
    rows, cols = mask.shape
    small = Image.fromarray((mask.astype(np.uint8) * 255)).resize((max(1, cols // factor), max(1, rows // factor)), Image.Resampling.NEAREST)
    r = max(1, int(round(radius_m / (30.0 * factor))))
    small = small.filter(ImageFilter.MaxFilter(2 * r + 1))
    big = small.resize((cols, rows), Image.Resampling.NEAREST)
    return np.asarray(big) > 0


def main() -> None:
    dem, dem_tags = load_tiff(DATA / "tpdc07_dem" / "dem_core_30m.tif")
    slope, _ = load_tiff(DATA / "tpdc07_dem" / "slope_deg.tif")
    accum, _ = load_tiff(DATA / "tpdc07_dem" / "flow_accumulation_cells.tif")
    lc, lc_tags = load_tiff(DATA / "tpdc05_landcover" / "jilong_LUCD_2023.tif")
    geojson = json.loads((DATA / "tpdc06_points" / "tpdc06_points.geojson").read_text(encoding="utf-8"))
    west, north, sx, sy = grid(dem_tags)
    rows, cols = dem.shape
    lc_on_dem = landcover_on_dem(dem_tags, dem.shape, lc, lc_tags)

    gully_masks = []
    presence = np.zeros((rows, cols), dtype=bool)
    for feature in geojson["features"]:
        m = rasterize(feature, rows, cols, west, north, sx, sy)
        gully_masks.append(m)
        presence |= m
    valid = np.isfinite(dem)
    background = valid & ~presence

    cov_bins = []
    cov_names = []
    for name, values, nb in [
        ("slope_deg", slope.astype(float), None),
        ("elevation_m", dem.astype(float), None),
        ("log1p_accum", np.log1p(accum.astype(float)), None),
    ]:
        bins, edges = continuous_bins(values, 5)
        cov_bins.append(bins)
        cov_names.append(name)
    cov_bins.append(lc_on_dem.astype(int))
    cov_names.append("landcover")

    # Global WOE reproduction
    wes = []
    woe_rows = []
    for name, bins in zip(cov_names, cov_bins):
        nb = int(bins.max())
        w, table = woe_values(bins, presence, background, nb)
        for r in table:
            r["covariate"] = name
        woe_rows.extend(table)
        wes.append(w)
    score = score_from_woe(cov_bins, wes)
    auc_global = rank_auc(score[presence], score[background])
    pd.DataFrame(woe_rows).to_csv(OUT / "q2_woe_bins.csv", index=False, encoding="utf-8-sig")

    # 2x2 / 3x3 block CV
    block_rows = []
    for bname, parts in [("2x2", 2), ("3x3", 3)]:
        r_edges = np.linspace(0, rows, parts + 1).astype(int)
        c_edges = np.linspace(0, cols, parts + 1).astype(int)
        for bi in range(parts):
            for bj in range(parts):
                test = np.zeros((rows, cols), dtype=bool)
                test[r_edges[bi] : r_edges[bi + 1], c_edges[bj] : c_edges[bj + 1]] = True
                tp = presence & test
                tb = background & test
                if tp.sum() < 5 or tb.sum() < 100:
                    block_rows.append({"scheme": bname, "block": f"r{bi}c{bj}", "test_presence": int(tp.sum()), "test_background": int(tb.sum()), "auc": None, "pr_auc": None})
                    continue
                trp = presence & ~test
                trb = background & ~test
                # 训练块内重新拟合 WOE；分箱沿用全数据（已知轻微泄漏，复现基线口径）
                ws = []
                for bins in cov_bins:
                    nb = int(bins.max())
                    w, _ = woe_values(bins, trp, trb, nb)
                    ws.append(w)
                sc = score_from_woe(cov_bins, ws)
                block_rows.append({"scheme": bname, "block": f"r{bi}c{bj}", "test_presence": int(tp.sum()), "test_background": int(tb.sum()), "auc": round(rank_auc(sc[tp], sc[tb]), 4), "pr_auc": round(pr_auc(sc[tp], sc[tb]), 4)})

    # Leave-one-gully-out + 2 km coarse buffer
    loo_rows = []
    for k, mask in enumerate(gully_masks, start=1):
        if mask.sum() == 0:
            continue
        buffer = coarse_buffer(mask, 2000, factor=4)
        tp = mask
        tb = background & ~buffer
        trp = presence & ~mask & ~buffer
        trb = background & ~buffer
        if tp.sum() < 10 or tb.sum() < 100 or trp.sum() < 10:
            loo_rows.append({"fold": k, "test_presence": int(tp.sum()), "test_background": int(tb.sum()), "train_presence": int(trp.sum()), "auc": None, "pr_auc": None})
            continue
        ws = []
        for bins in cov_bins:
            nb = int(bins.max())
            w, _ = woe_values(bins, trp, trb, nb)
            ws.append(w)
        sc = score_from_woe(cov_bins, ws)
        loo_rows.append({"fold": k, "test_presence": int(tp.sum()), "test_background": int(tb.sum()), "train_presence": int(trp.sum()), "auc": round(rank_auc(sc[tp], sc[tb]), 4), "pr_auc": round(pr_auc(sc[tp], sc[tb]), 4)})

    pd.DataFrame(block_rows).to_csv(OUT / "q2_spatial_cv_blocks.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(loo_rows).to_csv(OUT / "q2_spatial_cv_loo.csv", index=False, encoding="utf-8-sig")
    valid_loo = [r for r in loo_rows if r["auc"] is not None]
    summary = {
        "global_auc": round(auc_global, 4),
        "blocks_2x2": [r for r in block_rows if r["scheme"] == "2x2"],
        "blocks_3x3": [r for r in block_rows if r["scheme"] == "3x3"],
        "loo_folds_valid": len(valid_loo),
        "loo_auc_mean": round(float(np.mean([r["auc"] for r in valid_loo])), 4) if valid_loo else None,
        "loo_auc_std": round(float(np.std([r["auc"] for r in valid_loo])), 4) if valid_loo else None,
        "loo_pr_auc_mean": round(float(np.mean([r["pr_auc"] for r in valid_loo])), 4) if valid_loo else None,
        "notes": [
            "WOE 复现沿用数据窗口的 4 协变量/5 分位/landcover 编码；分箱全局确定，轻微泄漏，和基线口径一致",
            "LOO 2 km buffer 用 4x 粗网格 MaxFilter 近似；不是精确测地缓冲",
            "3x3 部分块无正例；只报告有正例块",
            "主指标看空间块/LOO，不看 global_auc",
        ],
    }
    (OUT / "q2_spatial_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(pd.DataFrame(block_rows).to_string(index=False))


if __name__ == "__main__":
    main()
