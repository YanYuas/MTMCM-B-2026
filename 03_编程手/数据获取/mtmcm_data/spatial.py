from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import heapq

import numpy as np
from PIL import Image, ImageDraw

from .process import _d8_accumulation, _sha256, _write_geotiff, _write_json
from .store import Store


D8_OFFSETS = {
    1: (-1, 0),   # N
    2: (1, 0),    # S
    3: (0, -1),   # W
    4: (0, 1),    # E
    5: (-1, -1),  # NW
    6: (-1, 1),   # NE
    7: (1, -1),   # SW
    8: (1, 1),    # SE
}


def _load_tiff(path: Path) -> tuple[Any, dict[str, Any]]:
    image = Image.open(path)
    array = np.asarray(image)
    tags = {
        33550: tuple(image.tag_v2.get(33550) or (None, None, None)),
        33922: tuple(image.tag_v2.get(33922) or (0, 0, 0, None, None, 0)),
        34735: tuple(image.tag_v2.get(34735) or ()),
        42113: image.tag_v2.get(42113),
    }
    return array, tags


def _grid(tags: dict[str, Any], shape: tuple[int, int]) -> tuple[float, float, float, float]:
    west = float(tags[33922][3])
    north = float(tags[33922][4])
    sx = float(tags[33550][0])
    sy = float(tags[33550][1])
    return west, north, sx, sy


def _receiver(direction: Any) -> Any:
    rows, cols = direction.shape
    receiver = np.arange(rows * cols, dtype="int64").reshape(rows, cols)
    for code, (di, dj) in D8_OFFSETS.items():
        i0, i1 = max(0, -di), min(rows, rows - di)
        j0, j1 = max(0, -dj), min(cols, cols - dj)
        if i0 >= i1 or j0 >= j1:
            continue
        sub = receiver[i0:i1, j0:j1]
        mask = direction[i0:i1, j0:j1] == code
        flat = (np.arange(i0, i1)[:, None] * cols + np.arange(j0, j1)[None, :])[mask]
        sub[mask] = flat + di * cols + dj
    return receiver


def _fill_sinks(dem: Any, *, epsilon: float = 1e-4) -> tuple[Any, int]:
    """Priority-flood + epsilon：填洼并给平坦区一个极小坡降，避免 D8 在填洼面上停住。"""
    rows, cols = dem.shape
    filled = dem.astype("float64").copy()
    visited = np.zeros((rows, cols), dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for i in range(rows):
        for j in (0, cols - 1):
            if not visited[i, j]:
                visited[i, j] = True
                heapq.heappush(heap, (float(dem[i, j]), i, j))
    for j in range(cols):
        for i in (0, rows - 1):
            if not visited[i, j]:
                visited[i, j] = True
                heapq.heappush(heap, (float(dem[i, j]), i, j))
    neighbours = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    while heap:
        z, i, j = heapq.heappop(heap)
        for di, dj in neighbours:
            ni, nj = i + di, j + dj
            if 0 <= ni < rows and 0 <= nj < cols and not visited[ni, nj]:
                visited[ni, nj] = True
                value = max(float(dem[ni, nj]), z + epsilon)
                filled[ni, nj] = value
                heapq.heappush(heap, (value, ni, nj))
    return filled, int((filled > dem).sum())


def _trace_channel(
    dem: Any,
    filled: Any,
    direction: Any,
    accumulation: Any,
    threshold: int,
    *,
    dx_m: float,
    dy_m: float,
    west: float,
    north: float,
    sx: float,
    sy: float,
) -> dict[str, Any] | None:
    rows, cols = dem.shape
    receiver = _receiver(direction.astype("uint8")).ravel()
    channel = accumulation >= threshold
    channel_cells = np.flatnonzero(channel.ravel())
    if channel_cells.size == 0:
        return None
    upstream: dict[int, list[int]] = {}
    for index in channel_cells:
        target = int(receiver[index])
        if target != index and channel.ravel()[target]:
            upstream.setdefault(target, []).append(int(index))
    boundary = np.zeros((rows, cols), dtype=bool)
    boundary[0, :] = boundary[-1, :] = boundary[:, 0] = boundary[:, -1] = True
    candidates = np.flatnonzero((channel & boundary).ravel())
    if candidates.size:
        outlet = int(candidates[np.argmax(accumulation.ravel()[candidates])])
        outlet_boundary = True
    else:
        outlet = int(channel_cells[np.argmax(accumulation.ravel()[channel_cells])])
        outlet_boundary = False
    path = [outlet]
    current = outlet
    while current in upstream:
        cand = upstream[current]
        current = max(cand, key=lambda i: accumulation.ravel()[i])
        path.append(current)
        if len(path) > 100_000:
            break
    path.reverse()
    if len(path) < 2:
        return None
    asc = np.asarray(path)
    rr, cc = np.unravel_index(asc, (rows, cols))
    lon = west + (cc + 0.5) * sx
    lat = north - (rr + 0.5) * sy
    z = dem.astype("float64").ravel()[asc]
    distance = np.zeros(len(asc), dtype="float64")
    if len(asc) > 1:
        dr = np.diff(rr).astype("float64")
        dc = np.diff(cc).astype("float64")
        distance[1:] = np.cumsum(np.hypot(dc * dx_m, dr * dy_m))
    length_m = float(distance[-1]) if len(distance) else 0.0
    drop_m = float(z[0] - z[-1])
    return {
        "path_cells": len(asc),
        "length_km": round(length_m / 1000, 3),
        "drop_m": round(drop_m, 2),
        "gradient_pct": round(drop_m / length_m * 100, 3) if length_m else None,
        "gradient_deg": round(math.degrees(math.atan2(drop_m, length_m)), 3) if length_m else None,
        "outlet_boundary": outlet_boundary,
        "source": {
            "lon": round(float(lon[0]), 7),
            "lat": round(float(lat[0]), 7),
            "elevation_m": round(float(z[0]), 2),
            "flow_accum_cells": int(accumulation.ravel()[asc[0]]),
        },
        "outlet": {
            "lon": round(float(lon[-1]), 7),
            "lat": round(float(lat[-1]), 7),
            "elevation_m": round(float(z[-1]), 2),
            "flow_accum_cells": int(accumulation.ravel()[asc[-1]]),
        },
        "coordinates": [[round(float(x), 7), round(float(y), 7)] for x, y in zip(lon, lat)],
    }


def process_channel_sensitivity(store: Store) -> dict[str, Any]:
    out = store.data_dir / "processed" / "tpdc07_channel_sensitivity"
    out.mkdir(parents=True, exist_ok=True)
    dem, tags = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif")
    channel_manifest = json.loads(
        (store.data_dir / "processed" / "tpdc07_dem" / "manifest.json").read_text(encoding="utf-8")
    )
    dx_m = float(channel_manifest["pixel_size_m"][0])
    dy_m = float(channel_manifest["pixel_size_m"][1])
    west, north, sx, sy = _grid(tags, dem.shape)

    modes = [("none", None), ("epsilon_1e-4", 1e-4), ("epsilon_1e-3", 1e-3)]
    thresholds = [500, 1000, 2000]
    rows: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    for mode, epsilon in modes:
        if epsilon is None:
            filled = dem.astype("float64")
            filled_cells = 0
        else:
            filled, filled_cells = _fill_sinks(dem, epsilon=epsilon)
        direction, accumulation, sinks = _d8_accumulation(filled, dx_m, dy_m)
        for threshold in thresholds:
            result = _trace_channel(
                dem,
                filled,
                direction,
                accumulation,
                threshold,
                dx_m=dx_m,
                dy_m=dy_m,
                west=west,
                north=north,
                sx=sx,
                sy=sy,
            )
            run_id = f"{mode}_thr{threshold}"
            if result is None:
                rows.append(
                    {
                        "run_id": run_id,
                        "fill_mode": mode,
                        "epsilon": epsilon,
                        "threshold_cells": threshold,
                        "status": "no_channel",
                        "filled_cells": filled_cells,
                        "sink_cells": sinks,
                    }
                )
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "fill_mode": mode,
                    "epsilon": epsilon,
                    "threshold_cells": threshold,
                    "status": "ok",
                    "filled_cells": filled_cells,
                    "sink_cells": sinks,
                    **{k: result[k] for k in ("path_cells", "length_km", "drop_m", "gradient_pct", "gradient_deg", "outlet_boundary")},
                    "source_lon": result["source"]["lon"],
                    "source_lat": result["source"]["lat"],
                    "source_elev_m": result["source"]["elevation_m"],
                    "outlet_lon": result["outlet"]["lon"],
                    "outlet_lat": result["outlet"]["lat"],
                    "outlet_elev_m": result["outlet"]["elevation_m"],
                }
            )
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "run_id": run_id,
                        "fill_mode": mode,
                        "epsilon": epsilon,
                        "threshold_cells": threshold,
                        "length_km": result["length_km"],
                        "gradient_pct": result["gradient_pct"],
                        "outlet_boundary": result["outlet_boundary"],
                    },
                    "geometry": {"type": "LineString", "coordinates": result["coordinates"]},
                }
            )
    import pandas as pd

    csv_path = out / "main_channel_sensitivity_runs.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    geojson_path = out / "main_channel_sensitivity.geojson"
    _write_json(
        geojson_path,
        {"type": "FeatureCollection", "name": "主沟道阈值/填洼敏感性", "features": features},
    )
    ok = [r for r in rows if r["status"] == "ok"]
    summary = {
        "dataset": "TPDC-07 主流路阈值/填洼敏感性",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runs": len(rows),
        "successful_runs": len(ok),
        "thresholds": thresholds,
        "fill_modes": [m for m, _ in modes],
        "length_km_min": min((r["length_km"] for r in ok), default=None),
        "length_km_max": max((r["length_km"] for r in ok), default=None),
        "gradient_pct_min": min((r["gradient_pct"] for r in ok), default=None),
        "gradient_pct_max": max((r["gradient_pct"] for r in ok), default=None),
        "outlet_boundary_count": sum(1 for r in ok if r["outlet_boundary"]),
        "recommended": "epsilon_1e-4_thr1000",
        "notes": [
            "阈值 500/1000/2000 cells；填洼模式 none/epsilon_1e-4/epsilon_1e-3",
            "none 模式的汇流可能停在内部 sink，outlet_boundary=False",
            "结果只反映 D8/阈值选择，不是唯一真实沟道",
        ],
    }
    summary_path = out / "summary.json"
    _write_json(summary_path, summary)
    manifest = {
        **summary,
        "source_files": [store.rel(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif")],
        "outputs": [
            {"path": store.rel(csv_path), "bytes": csv_path.stat().st_size, "sha256": _sha256(csv_path)},
            {"path": store.rel(geojson_path), "bytes": geojson_path.stat().st_size, "sha256": _sha256(geojson_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def process_main_channel(store: Store) -> dict[str, Any]:
    out = store.data_dir / "processed" / "tpdc07_channel"
    out.mkdir(parents=True, exist_ok=True)
    dem, tags = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif")
    channel_manifest = json.loads(
        (store.data_dir / "processed" / "tpdc07_dem" / "manifest.json").read_text(encoding="utf-8")
    )
    threshold = int(channel_manifest.get("channel_threshold_cells", 1000))
    west, north, sx, sy = _grid(tags, dem.shape)
    dx_m = float(channel_manifest["pixel_size_m"][0])
    dy_m = float(channel_manifest["pixel_size_m"][1])
    rows, cols = dem.shape

    # 主流路必须在“填洼 + epsilon”后的 DEM 上做 D8，否则会停在内部 sink。
    filled, filled_cells = _fill_sinks(dem, epsilon=1e-4)
    direction, accumulation, sinks_after = _d8_accumulation(filled, dx_m, dy_m)
    receiver = _receiver(direction.astype("uint8")).ravel()
    channel = accumulation >= threshold
    channel_cells = np.flatnonzero(channel.ravel())
    if channel_cells.size == 0:
        raise RuntimeError("没有沟道像元，无法提取主流路")

    upstream: dict[int, list[int]] = {}
    for index in channel_cells:
        target = int(receiver[index])
        if target != index and channel.ravel()[target]:
            upstream.setdefault(target, []).append(int(index))

    boundary = np.zeros((rows, cols), dtype=bool)
    boundary[0, :] = boundary[-1, :] = boundary[:, 0] = boundary[:, -1] = True
    candidates = np.flatnonzero((channel & boundary).ravel())
    if candidates.size:
        outlet = int(candidates[np.argmax(accumulation.ravel()[candidates])])
        outlet_boundary = True
    else:
        outlet = int(channel_cells[np.argmax(accumulation.ravel()[channel_cells])])
        outlet_boundary = False
    path = [outlet]
    current = outlet
    while current in upstream:
        candidates = upstream[current]
        current = max(candidates, key=lambda i: accumulation.ravel()[i])
        path.append(current)
        if len(path) > 100_000:
            break
    path.reverse()
    if len(path) < 2:
        raise RuntimeError("主流路回溯过短（<2 像元），检查 D8/阈值")

    asc = np.asarray(path)
    rr, cc = np.unravel_index(asc, (rows, cols))
    lon = west + (cc + 0.5) * sx
    lat = north - (rr + 0.5) * sy
    z = dem.astype("float64").ravel()[asc]
    z_filled = filled.astype("float64").ravel()[asc]
    acc = accumulation.ravel()[asc]
    distance = np.zeros(len(asc), dtype="float64")
    if len(asc) > 1:
        dr = np.diff(rr).astype("float64")
        dc = np.diff(cc).astype("float64")
        distance[1:] = np.cumsum(np.hypot(dc * dx_m, dr * dy_m))
    local_deg = np.zeros(len(asc), dtype="float64")
    local_orig_deg = np.zeros(len(asc), dtype="float64")
    for i in range(1, len(asc)):
        step = distance[i] - distance[i - 1]
        if step > 0:
            local_deg[i] = math.degrees(math.atan2(z_filled[i - 1] - z_filled[i], step))
            local_orig_deg[i] = math.degrees(math.atan2(z[i - 1] - z[i], step))

    profile_rows = []
    for i in range(len(asc)):
        profile_rows.append(
            {
                "order": i + 1,
                "row": int(rr[i]),
                "col": int(cc[i]),
                "lon": round(float(lon[i]), 7),
                "lat": round(float(lat[i]), 7),
                "elevation_m": round(float(z[i]), 3),
                "routed_elevation_m": round(float(z_filled[i]), 3),
                "distance_m": round(float(distance[i]), 2),
                "local_slope_deg": round(float(local_deg[i]), 4),
                "local_slope_original_deg": round(float(local_orig_deg[i]), 4),
                "flow_accum_cells": int(acc[i]),
            }
        )
    import pandas as pd

    profile_path = out / "main_channel_profile.csv"
    pd.DataFrame(profile_rows).to_csv(profile_path, index=False, encoding="utf-8-sig")

    line = {
        "type": "FeatureCollection",
        "name": "TPDC-07 主流路（D8 最大汇流回溯）",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "channel": "main",
                    "threshold_cells": threshold,
                    "filled_dem": True,
                    "outlet_boundary": outlet_boundary,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(float(x), 7), round(float(y), 7)] for x, y in zip(lon, lat)],
                },
            }
        ],
    }
    geojson_path = out / "main_channel.geojson"
    _write_json(geojson_path, line)

    raster = np.zeros((rows, cols), dtype="uint8")
    raster[rr, cc] = 1
    raster_path = out / "main_channel_mask.tif"
    _write_geotiff(raster_path, raster, mode="L", tags=tags, nodata=255)

    filled_dem_path = out / "dem_filled_30m.tif"
    _write_geotiff(filled_dem_path, filled.astype("float32"), mode="F", tags=tags, nodata=-9999)
    filled_dir_path = out / "flow_direction_filled_d8.tif"
    _write_geotiff(filled_dir_path, direction, mode="L", tags=tags, nodata=255)
    filled_acc_path = out / "flow_accumulation_filled.tif"
    _write_geotiff(filled_acc_path, accumulation.astype("float32"), mode="F", tags=tags, nodata=-9999)

    length_m = float(distance[-1]) if len(distance) else 0.0
    drop_m = float(z[0] - z[-1])
    summary = {
        "dataset": "TPDC-07 主流路/纵剖面",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "threshold_cells": threshold,
        "path_cells": len(asc),
        "length_km": round(length_m / 1000, 3),
        "drop_m": round(drop_m, 2),
        "gradient_pct": round(drop_m / length_m * 100, 3) if length_m else None,
        "gradient_deg": round(math.degrees(math.atan2(drop_m, length_m)), 3) if length_m else None,
        "outlet_boundary": outlet_boundary,
        "filled_cells": filled_cells,
        "fill_epsilon_m": 1e-4,
        "sink_cells_before": int(channel_manifest.get("sink_cells", 0)),
        "sink_cells_after": sinks_after,
        "source": {k: profile_rows[0][k] for k in ("lon", "lat", "elevation_m", "routed_elevation_m", "flow_accum_cells")},
        "outlet": {k: profile_rows[-1][k] for k in ("lon", "lat", "elevation_m", "routed_elevation_m", "flow_accum_cells")},
        "notes": [
            "主流路 = 填洼+epsilon 后的 D8 汇流，再从边界出口逆流回溯到源头",
            "outlet 优先取 DEM 边界上汇流最大的沟道单元；outlet_boundary 表示是否成功",
            "elevation_m 为原始 DEM 高程；routed_elevation_m 为填洼后的路由高程",
            "local_slope_deg 用填洼路由高程（水力坡降）；local_slope_original_deg 用原始 DEM（可含局部上坡）",
            "D8 codes: 1=N,2=S,3=W,4=E,5=NW,6=NE,7=SW,8=SE,0=sink",
        ],
    }
    summary_path = out / "main_channel_summary.json"
    _write_json(summary_path, summary)
    manifest = {
        **summary,
        "source_files": [
            store.rel(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif"),
        ],
        "outputs": [
            {"path": store.rel(profile_path), "bytes": profile_path.stat().st_size, "sha256": _sha256(profile_path)},
            {"path": store.rel(geojson_path), "bytes": geojson_path.stat().st_size, "sha256": _sha256(geojson_path)},
            {"path": store.rel(raster_path), "bytes": raster_path.stat().st_size, "sha256": _sha256(raster_path)},
            {"path": store.rel(filled_dem_path), "bytes": filled_dem_path.stat().st_size, "sha256": _sha256(filled_dem_path)},
            {"path": store.rel(filled_dir_path), "bytes": filled_dir_path.stat().st_size, "sha256": _sha256(filled_dir_path)},
            {"path": store.rel(filled_acc_path), "bytes": filled_acc_path.stat().st_size, "sha256": _sha256(filled_acc_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def _geometry_polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates") or []]
    if geometry.get("type") == "MultiPolygon":
        return geometry.get("coordinates") or []
    return []


def process_gully_overlay(store: Store) -> dict[str, Any]:
    import pandas as pd

    out = store.data_dir / "processed" / "spatial_baseline"
    out.mkdir(parents=True, exist_ok=True)
    dem, tags = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "dem_core_30m.tif")
    slope, _ = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "slope_deg.tif")
    channel_manifest = json.loads(
        (store.data_dir / "processed" / "tpdc07_dem" / "manifest.json").read_text(encoding="utf-8")
    )
    threshold = int(channel_manifest.get("channel_threshold_cells", 1000))
    filled_acc_path = store.data_dir / "processed" / "tpdc07_channel" / "flow_accumulation_filled.tif"
    if filled_acc_path.exists():
        accumulation, _ = _load_tiff(filled_acc_path)
        channel = (accumulation >= threshold).astype("uint8")
        channel_source = "filled_d8"
    else:
        accumulation, _ = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "flow_accumulation_cells.tif")
        channel, _ = _load_tiff(store.data_dir / "processed" / "tpdc07_dem" / "channel_mask_acc1000.tif")
        channel_source = "unfilled_d8"
    landcover, lc_tags = _load_tiff(store.data_dir / "processed" / "tpdc05_landcover" / "jilong_LUCD_2023.tif")
    geojson = json.loads(
        (store.data_dir / "processed" / "tpdc06_points" / "tpdc06_points.geojson").read_text(encoding="utf-8")
    )
    west, north, sx, sy = _grid(tags, dem.shape)
    rows, cols = dem.shape
    dx_m = abs(sx) * 111320.0 * math.cos(math.radians(north - sy * rows / 2))
    dy_m = abs(sy) * 110574.0
    cell_area_km2 = dx_m * dy_m / 1e6

    # 土地覆盖是全县 6336×3957，DEM 是核心沟谷 1816×1148；最近邻采样到 DEM 网格。
    lc_west, lc_north, lc_sx, lc_sy = _grid(lc_tags, landcover.shape)
    rr, cc = np.indices((rows, cols))
    lon_dem = west + (cc + 0.5) * sx
    lat_dem = north - (rr + 0.5) * sy
    lc_col = np.rint((lon_dem - lc_west) / lc_sx).astype("int64")
    lc_row = np.rint((lc_north - lat_dem) / lc_sy).astype("int64")
    inside = (lc_row >= 0) & (lc_row < landcover.shape[0]) & (lc_col >= 0) & (lc_col < landcover.shape[1])
    landcover_on_dem = np.zeros((rows, cols), dtype=landcover.dtype)
    landcover_on_dem[inside] = landcover[lc_row[inside], lc_col[inside]]

    stats_rows = []
    id_image = Image.new("L", (cols, rows), 0)
    id_draw = ImageDraw.Draw(id_image)
    for order, feature in enumerate(geojson.get("features", []), start=1):
        props = feature.get("properties") or {}
        polygons = _geometry_polygons(feature.get("geometry") or {})
        mask_image = Image.new("L", (cols, rows), 0)
        mask_draw = ImageDraw.Draw(mask_image)
        for rings in polygons:
            for ring in rings:
                points = []
                for lon, lat in ring:
                    points.append(((float(lon) - west) / sx, (north - float(lat)) / sy))
                if len(points) >= 3:
                    mask_draw.polygon(points, fill=1)
                    id_draw.polygon(points, fill=order)
        mask = np.asarray(mask_image) == 1
        cells = int(mask.sum())
        row: dict[str, Any] = {
            "id": order,
            "Code": props.get("Code", ""),
            "Name": props.get("Name", ""),
            "in_dem": cells > 0,
            "cells": cells,
            "area_km2": round(cells * cell_area_km2, 4),
            "mean_slope_deg": None,
            "max_slope_deg": None,
            "mean_accum_cells": None,
            "max_accum_cells": None,
            "channel_cells": 0,
            "landcover_majority": "",
            "landcover_nodata_pct": None,
            "沟比降": props.get("沟比降", ""),
            "主沟长": props.get("主沟长", ""),
            "规模": props.get("规模", ""),
            "频率": props.get("频率", ""),
            "类型": props.get("类型", ""),
            "解译Time": props.get("解译Time", ""),
            "影像Time": props.get("影像Time", ""),
            "承灾体": props.get("承灾体", ""),
            "行政区": props.get("行政区", ""),
        }
        if cells:
            s = slope[mask]
            a = accumulation[mask]
            lc = landcover_on_dem[mask]
            row.update(
                {
                    "mean_slope_deg": round(float(s.mean()), 3),
                    "max_slope_deg": round(float(s.max()), 3),
                    "mean_accum_cells": round(float(a.mean()), 1),
                    "max_accum_cells": int(a.max()),
                    "channel_cells": int(channel[mask].sum()),
                    "landcover_nodata_pct": round(float((lc == 0).mean() * 100), 2),
                }
            )
            valid_lc = lc[lc != 0]
            if valid_lc.size:
                values, counts = np.unique(valid_lc, return_counts=True)
                row["landcover_majority"] = int(values[np.argmax(counts)])
        stats_rows.append(row)

    stats_path = out / "tpdc06_gully_overlay_stats.csv"
    pd.DataFrame(stats_rows).to_csv(stats_path, index=False, encoding="utf-8-sig")
    id_path = out / "tpdc06_gully_id_mask.tif"
    _write_geotiff(id_path, np.asarray(id_image), mode="L", tags=tags, nodata=255)

    in_dem = [r for r in stats_rows if r["in_dem"]]
    summary = {
        "dataset": "TPDC-06 历史沟域 × DEM/坡度/汇流/土地覆盖",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "gullies_total": len(stats_rows),
        "gullies_in_dem": len(in_dem),
        "cell_area_km2": round(cell_area_km2, 6),
        "total_cells_in_dem": sum(r["cells"] for r in in_dem),
        "mean_slope_deg_in_dem": round(float(np.mean([r["mean_slope_deg"] for r in in_dem])), 3) if in_dem else None,
        "channel_cells_in_dem": sum(r["channel_cells"] for r in in_dem),
        "channel_source": channel_source,
        "channel_threshold_cells": threshold,
        "notes": [
            "84 个沟域多边形不是 84 次独立事件；本表只做空间登记叠加",
            "GeoJSON 坐标为 CGCS2000 近似 WGS84；与 DEM 叠加以像元中心为准",
            "土地覆盖 0=nodata，majority 只在 1–10 中统计，但无官方图例",
            "土地覆盖按最近邻采样到 DEM 网格（全县 30 m → 核心沟谷 30 m）",
            "沟道统计优先使用 batch 3 的填洼 D8；没有时退回 batch 2 的未填洼层",
            "in_dem=False 表示该沟域完全落在 DEM 实际范围之外",
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
            store.rel(store.data_dir / "processed" / "tpdc07_dem" / "flow_accumulation_cells.tif"),
            store.rel(store.data_dir / "processed" / "tpdc05_landcover" / "jilong_LUCD_2023.tif"),
        ],
        "outputs": [
            {"path": store.rel(stats_path), "bytes": stats_path.stat().st_size, "sha256": _sha256(stats_path)},
            {"path": store.rel(id_path), "bytes": id_path.stat().st_size, "sha256": _sha256(id_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest
