from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .process import _sha256, _write_geotiff, _write_json
from .spatial import _geometry_polygons, _grid, _load_tiff
from .store import Store


def _rasterize(feature: dict[str, Any], rows: int, cols: int, west: float, north: float, sx: float, sy: float) -> Any:
    image = Image.new("L", (cols, rows), 0)
    draw = ImageDraw.Draw(image)
    for rings in _geometry_polygons(feature.get("geometry") or {}):
        for ring in rings:
            points = [((float(lon) - west) / sx, (north - float(lat)) / sy) for lon, lat in ring]
            if len(points) >= 3:
                draw.polygon(points, fill=1)
    return np.asarray(image) == 1


def _continuous_bins(values: Any, n_bins: int = 5) -> tuple[Any, list[float]]:
    finite = values[np.isfinite(values)]
    edges = np.unique(np.quantile(finite, np.linspace(0, 1, n_bins + 1)))
    if len(edges) < 2:
        return np.zeros(values.shape, dtype="int64"), [float(edges[0]) if len(edges) else 0.0]
    bins = np.digitize(values, edges[1:-1], right=False).astype("int64")
    return np.clip(bins, 0, len(edges) - 2), [float(x) for x in edges]


def _woe_values(bins: Any, presence: Any, background: Any, n_bins: int) -> tuple[Any, list[dict[str, Any]]]:
    present_total = int(presence.sum())
    background_total = int(background.sum())
    woe = np.zeros(n_bins + 1, dtype="float64")
    rows: list[dict[str, Any]] = []
    for b in range(n_bins + 1):
        p = int(((bins == b) & presence).sum())
        q = int(((bins == b) & background).sum())
        p_rate = (p + 0.5) / (present_total + 0.5 * (n_bins + 1))
        b_rate = (q + 0.5) / (background_total + 0.5 * (n_bins + 1))
        value = math.log(p_rate / b_rate)
        woe[b] = value
        rows.append(
            {
                "bin": b,
                "presence_cells": p,
                "background_cells": q,
                "presence_rate": round(p / present_total, 6) if present_total else None,
                "background_rate": round(q / background_total, 6) if background_total else None,
                "woe": round(value, 4),
            }
        )
    return woe, rows


def _rank_auc(positive: Any, negative: Any) -> float | None:
    n1, n0 = len(positive), len(negative)
    if n1 == 0 or n0 == 0:
        return None
    scores = np.concatenate([positive, negative])
    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(len(scores), dtype="float64")
    i = 0
    while i < len(scores):
        j = i + 1
        while j < len(scores) and sorted_scores[j] == sorted_scores[i]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    sum_ranks_pos = ranks[:n1].sum()
    return float((sum_ranks_pos - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def process_susceptibility(store: Store) -> dict[str, Any]:
    import pandas as pd

    out = store.data_dir / "processed" / "q2_susceptibility"
    out.mkdir(parents=True, exist_ok=True)
    dem, tags = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif")
    slope, _ = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "slope_deg.tif")
    filled_acc = store.data_dir / "processed" / "tpdc07_channel" / "flow_accumulation_filled.tif"
    if filled_acc.exists():
        accumulation, _ = _load_tiff(filled_acc)
        accum_source = "filled_d8"
    else:
        accumulation, _ = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "flow_accumulation_cells.tif")
        accum_source = "unfilled_d8"
    landcover, lc_tags = _load_tiff(store.data_dir / "processed" / "tpdc05_landcover" / "jilong_LUCD_2023.tif")
    geojson = json.loads(
        (store.data_dir / "processed" / "tpdc06_points" / "tpdc06_points.geojson").read_text(encoding="utf-8")
    )
    west, north, sx, sy = _grid(tags, dem.shape)
    rows, cols = dem.shape
    dx_m = abs(sx) * 111320.0 * math.cos(math.radians(north - sy * rows / 2))
    dy_m = abs(sy) * 110574.0
    cell_area_km2 = dx_m * dy_m / 1e6

    # 全部 84 个沟域栅格化；presence 只取与 DEM 相交的部分。
    gully_masks: list[Any] = []
    presence = np.zeros((rows, cols), dtype=bool)
    for feature in geojson.get("features", []):
        mask = _rasterize(feature, rows, cols, west, north, sx, sy)
        gully_masks.append(mask)
        presence |= mask
    valid = np.isfinite(dem)
    background = valid & ~presence

    # 土地覆盖最近邻到 DEM 网格。
    lc_west, lc_north, lc_sx, lc_sy = _grid(lc_tags, landcover.shape)
    rr, cc = np.indices((rows, cols))
    lc_col = np.rint((west + (cc + 0.5) * sx - lc_west) / lc_sx).astype("int64")
    lc_row = np.rint((lc_north - (north - (rr + 0.5) * sy)) / lc_sy).astype("int64")
    inside = (lc_row >= 0) & (lc_row < landcover.shape[0]) & (lc_col >= 0) & (lc_col < landcover.shape[1])
    lc = np.zeros((rows, cols), dtype="int64")
    lc[inside] = landcover[lc_row[inside], lc_col[inside]].astype("int64")

    covariates: list[tuple[str, Any, int, list[float] | None]] = []
    for name, values in (("slope_deg", slope), ("elevation_m", dem), ("log1p_accum", np.log1p(accumulation))):
        bins, edges = _continuous_bins(values, 5)
        covariates.append((name, bins, max(int(bins.max()), 0), edges))
    covariates.append(("landcover", lc, 10, None))

    score = np.zeros((rows, cols), dtype="float64")
    woe_rows: list[dict[str, Any]] = []
    for name, bins, n_bins, edges in covariates:
        woe, table = _woe_values(bins, presence, background, n_bins)
        for row in table:
            row["covariate"] = name
            row["bin_edges"] = json.dumps(edges) if edges else "class_code"
            woe_rows.append(row)
        score += woe[bins]

    auc_global = _rank_auc(score[presence], score[background])
    # 2×2 空间块交叉验证：用其余块估计 WOE，在留出块上算 AUC。
    block_rows = [0, rows // 2, rows]
    block_cols = [0, cols // 2, cols]
    block_aucs: list[dict[str, Any]] = []
    for bi in range(2):
        for bj in range(2):
            test = np.zeros((rows, cols), dtype=bool)
            test[block_rows[bi] : block_rows[bi + 1], block_cols[bj] : block_cols[bj + 1]] = True
            train_p = presence & ~test
            train_b = background & ~test
            test_p = presence & test
            test_b = background & test
            if test_p.sum() < 5 or test_b.sum() < 100:
                block_aucs.append(
                    {"block": f"r{bi}c{bj}", "test_presence": int(test_p.sum()), "test_background": int(test_b.sum()), "auc": None}
                )
                continue
            test_score = np.zeros((rows, cols), dtype="float64")
            for name, bins, n_bins, _ in covariates:
                woe, _ = _woe_values(bins, train_p, train_b, n_bins)
                test_score += woe[bins]
            block_aucs.append(
                {
                    "block": f"r{bi}c{bj}",
                    "test_presence": int(test_p.sum()),
                    "test_background": int(test_b.sum()),
                    "auc": _rank_auc(test_score[test_p], test_score[test_b]),
                }
            )

    background_sorted = np.sort(score[background])
    gully_rows = []
    for order, (feature, mask) in enumerate(zip(geojson.get("features", []), gully_masks), start=1):
        props = feature.get("properties") or {}
        cells = int(mask.sum())
        mean_score = float(score[mask].mean()) if cells else None
        percentile = (
            float(np.searchsorted(background_sorted, mean_score) / len(background_sorted))
            if cells and len(background_sorted)
            else None
        )
        gully_rows.append(
            {
                "id": order,
                "Code": props.get("Code", ""),
                "Name": props.get("Name", ""),
                "in_dem": cells > 0,
                "cells": cells,
                "area_km2": round(cells * cell_area_km2, 4),
                "mean_score": round(mean_score, 4) if mean_score is not None else None,
                "background_percentile": round(percentile, 4) if percentile is not None else None,
                "规模": props.get("规模", ""),
                "频率": props.get("频率", ""),
                "类型": props.get("类型", ""),
            }
        )
    in_dem_scores = [r["background_percentile"] for r in gully_rows if r["in_dem"] and r["background_percentile"] is not None]

    # 分级：背景分数的 20/40/60/80 分位。
    edges = np.quantile(score[background], [0.2, 0.4, 0.6, 0.8])
    classes = np.digitize(score, edges, right=False).astype("uint8") + 1
    class_raster = np.where(valid, classes, 255).astype("uint8")

    score_path = out / "q2_susceptibility_score.tif"
    _write_geotiff(score_path, score.astype("float32"), mode="F", tags=tags, nodata=-9999)
    class_path = out / "q2_susceptibility_class.tif"
    _write_geotiff(class_path, class_raster, mode="L", tags=tags, nodata=255)
    woe_path = out / "q2_woe_bins.csv"
    pd.DataFrame(woe_rows).to_csv(woe_path, index=False, encoding="utf-8-sig")
    gully_path = out / "q2_gully_scores.csv"
    pd.DataFrame(gully_rows).to_csv(gully_path, index=False, encoding="utf-8-sig")

    summary = {
        "dataset": "Q2 空间易发性基线（WOE）",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "presence_cells": int(presence.sum()),
        "background_cells": int(background.sum()),
        "gullies_total": len(gully_rows),
        "gullies_in_dem": sum(1 for r in gully_rows if r["in_dem"]),
        "covariates": [name for name, _, _, _ in covariates],
        "accum_source": accum_source,
        "auc_global_pixel": round(auc_global, 4) if auc_global is not None else None,
        "auc_spatial_blocks": block_aucs,
        "median_gully_percentile": round(float(np.median(in_dem_scores)), 4) if in_dem_scores else None,
        "min_gully_percentile": round(float(np.min(in_dem_scores)), 4) if in_dem_scores else None,
        "max_gully_percentile": round(float(np.max(in_dem_scores)), 4) if in_dem_scores else None,
        "class_breaks": [round(float(x), 4) for x in edges],
        "notes": [
            "标签是 23 个与 DEM 相交的登记沟域多边形，不是 23 次事件；没有事件时间",
            "WOE 分数是相对易发性，不是发生概率；不能据此算 95% 覆盖率",
            "AUC_global_pixel 受空间自相关影响偏乐观；优先看 2×2 空间块 AUC",
            "土地覆盖 0=nodata 作为单独类别参与 WOE，解释时要谨慎；1–10 无官方图例",
            "坡度/高程/汇流使用固定分位分箱；分箱在全数据上确定，块验证仍有轻微信息泄漏",
        ],
    }
    summary_path = out / "summary.json"
    _write_json(summary_path, summary)
    manifest = {
        **summary,
        "source_files": [
            store.rel(store.data_dir / "processed" / "tpdc06_points" / "tpdc06_points.geojson"),
            store.rel(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif"),
            store.rel(store.data_dir / "processed" / "tpdc07_dem" / "slope_deg.tif"),
            store.rel(filled_acc),
            store.rel(store.data_dir / "processed" / "tpdc05_landcover" / "jilong_LUCD_2023.tif"),
        ],
        "outputs": [
            {"path": store.rel(score_path), "bytes": score_path.stat().st_size, "sha256": _sha256(score_path)},
            {"path": store.rel(class_path), "bytes": class_path.stat().st_size, "sha256": _sha256(class_path)},
            {"path": store.rel(woe_path), "bytes": woe_path.stat().st_size, "sha256": _sha256(woe_path)},
            {"path": store.rel(gully_path), "bytes": gully_path.stat().st_size, "sha256": _sha256(gully_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest
