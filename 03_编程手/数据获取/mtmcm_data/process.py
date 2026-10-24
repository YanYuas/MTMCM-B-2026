from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
import struct
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import WORKSPACE_ROOT, load_config
from .dbf import read_dbf
from .store import Store


try:
    import numpy as np
    import pandas as pd
    from PIL import Image, TiffImagePlugin
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    TiffImagePlugin = None  # type: ignore[assignment]


ATTACH_DIR = WORKSPACE_ROOT / "05_辅助文档" / "题目附件" / "附件"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _var_parts(column: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)\(([^)]*)\)$", column)
    if not m:
        return column, ""
    return m.group(1), m.group(2)


def _gzip_csv(frame: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, compression="gzip", encoding="utf-8")


def _source_zip(source_id: str) -> Path:
    source = load_config().get(source_id)
    path = source.local_mirror_path
    if path is None or not path.exists():
        raise FileNotFoundError(f"{source_id} 本地附件不存在")
    return path


TPDC01_VARS = {
    "MET": ["Ta_2m", "RH_2m", "WS_10m", "Precip"],
    "RADM": ["Rsd", "Rld"],
    "SOIL": ["VWC_0.4m", "soilT_0.4m"],
    "FLUX": ["H", "LE", "USTAR"],
}


def process_tpdc01(store: Store) -> dict[str, Any]:
    zip_path = _source_zip("tpdc_01_hourly")
    out = store.data_dir / "processed" / "tpdc01_hourly"
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    qc_present: set[str] = set()
    qc_columns: dict[str, str] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(n for n in archive.namelist() if n.lower().endswith(".csv")):
            base = Path(name).name
            prefix = base.split("_")[0]
            if prefix not in TPDC01_VARS:
                continue
            frame = pd.read_csv(archive.open(name), encoding="utf-8-sig")
            if "Timestamp" not in frame:
                continue
            timestamp = pd.to_datetime(frame["Timestamp"], errors="coerce")
            for var in TPDC01_VARS[prefix]:
                column = next((c for c in frame.columns if _var_parts(c)[0] == var), None)
                if column is None:
                    continue
                _, unit = _var_parts(column)
                value = pd.to_numeric(frame[column], errors="coerce")
                missing = value.eq(9999.9) | value.isna()
                qc_col = next((c for c in frame.columns if c.lower() == f"qc_{var}".lower()), None)
                if qc_col is not None:
                    qc_present.add(var)
                    qc_columns[var] = qc_col
                    qc = pd.to_numeric(frame[qc_col], errors="coerce").astype("Int64")
                else:
                    qc = pd.Series(pd.NA, index=frame.index, dtype="Int64")
                part = pd.DataFrame(
                    {
                        "timestamp": timestamp,
                        "source_file": base,
                        "variable": var,
                        "value": value.mask(missing),
                        "unit": unit,
                        "qc_flag": qc,
                        "missing_flag": missing.astype("int8"),
                        "qc_missing": (qc == 8).fillna(False).astype("int8"),
                        "qc_suspect": qc.isin([1, 2]).fillna(False).astype("int8"),
                    }
                )
                frames.append(part)
    if not frames:
        raise RuntimeError("TPDC-01 没有可处理变量")
    long = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "variable"], kind="stable")
    long_path = out / "tpdc01_key_vars_long.csv.gz"
    _gzip_csv(long, long_path)

    summary = (
        long.groupby(["variable", "unit"], dropna=False)
        .agg(
            rows=("value", "size"),
            missing=("missing_flag", "sum"),
            qc_missing=("qc_missing", "sum"),
            qc_suspect=("qc_suspect", "sum"),
            valid=("missing_flag", lambda s: int((s == 0).sum())),
            min=("value", "min"),
            max=("value", "max"),
        )
        .reset_index()
    )
    summary["missing_rate_pct"] = (summary["missing"] / summary["rows"] * 100).round(2)
    summary_path = out / "tpdc01_missing_by_variable.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    descriptions = {
        "Ta_2m": "2 m air temperature",
        "RH_2m": "2 m relative humidity",
        "WS_10m": "10 m wind speed",
        "Precip": "precipitation",
        "Rsd": "downward shortwave radiation",
        "Rld": "downward longwave radiation",
        "VWC_0.4m": "0.4 m volumetric water content",
        "soilT_0.4m": "0.4 m soil temperature",
        "H": "sensible heat flux",
        "LE": "latent heat flux",
        "USTAR": "friction velocity",
    }
    dictionary = pd.DataFrame(
        [
            {
                "variable": var,
                "unit": unit,
                "description": descriptions.get(var, ""),
                "qc_column": qc_columns.get(var, ""),
                "qc_available": var in qc_present,
                "source_type": next((k for k, v in TPDC01_VARS.items() if var in v), ""),
            }
            for var, unit in summary[["variable", "unit"]].drop_duplicates().itertuples(index=False)
        ]
    )
    dict_path = out / "tpdc01_variable_dictionary.csv"
    dictionary.to_csv(dict_path, index=False, encoding="utf-8-sig")

    manifest = {
        "dataset": "TPDC-01 逐小时综合观测",
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": int(len(long)),
        "variables": sorted(long["variable"].unique().tolist()),
        "time_start": str(long["timestamp"].min()),
        "time_end": str(long["timestamp"].max()),
        "rules": [
            "9999.9 与 NaN 均标记 missing_flag=1，value 置空，不补零",
            "QC=8 标记 qc_missing=1；QC=1/2 标记 qc_suspect=1",
            "保留原始 timestamp（UTC+8，不转 UTC）",
            "长表：一行 = 时间 × 变量",
        ],
        "outputs": [
            {"path": store.rel(long_path), "bytes": long_path.stat().st_size, "sha256": _sha256(long_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
            {"path": store.rel(dict_path), "bytes": dict_path.stat().st_size, "sha256": _sha256(dict_path)},
        ],
    }
    manifest_path = out / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest


def process_tpdc02(store: Store) -> dict[str, Any]:
    zip_path = _source_zip("tpdc_02_temp")
    out = store.data_dir / "processed" / "tpdc02_temp"
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(n for n in archive.namelist() if n.lower().endswith(".xlsx")):
            frame = pd.read_excel(archive.open(name))
            if "时间" not in frame:
                continue
            frame["date"] = pd.to_datetime(frame["时间"], errors="coerce")
            long = frame.melt(id_vars=["date"], value_vars=[c for c in frame.columns if c != "时间" and c != "date"], var_name="county", value_name="temp_c")
            long["source_file"] = Path(name).name
            frames.append(long)
    if not frames:
        raise RuntimeError("TPDC-02 没有可处理表格")
    long = pd.concat(frames, ignore_index=True).sort_values(["date", "county"], kind="stable")
    long_path = out / "tpdc02_temp_long.csv.gz"
    _gzip_csv(long, long_path)

    wide = long.pivot_table(index="date", columns="county", values="temp_c", aggfunc="first").reset_index()
    wide_path = out / "tpdc02_temp_wide.csv.gz"
    _gzip_csv(wide, wide_path)

    summary = (
        long.groupby("county")
        .agg(rows=("temp_c", "size"), missing=("temp_c", lambda s: int(s.isna().sum())), min=("temp_c", "min"), max=("temp_c", "max"))
        .reset_index()
    )
    summary["missing_rate_pct"] = (summary["missing"] / summary["rows"] * 100).round(2)
    summary_path = out / "tpdc02_coverage_by_county.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    manifest = {
        "dataset": "TPDC-02 逐日平均气温",
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows_long": int(len(long)),
        "rows_wide": int(len(wide)),
        "time_start": str(long["date"].min()),
        "time_end": str(long["date"].max()),
        "rules": [
            "按县拆长表：一行 = 日期 × 县",
            "不做小时插值；2025 只有 214 天，年度趋势需排除或标注",
            "保留原始日期，不填补缺失日",
        ],
        "outputs": [
            {"path": store.rel(long_path), "bytes": long_path.stat().st_size, "sha256": _sha256(long_path)},
            {"path": store.rel(wide_path), "bytes": wide_path.stat().st_size, "sha256": _sha256(wide_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def _dbf_records(data: bytes) -> tuple[list[dict[str, str]], list[tuple[str, str, int]]]:
    records, fields, _ = read_dbf(data)
    return records, fields


def _shp_polygons(data: bytes) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    pos = 100
    while pos + 8 <= len(data):
        _, content_len_words = struct.unpack(">ii", data[pos : pos + 8])
        pos += 8
        content = data[pos : pos + content_len_words * 2]
        pos += content_len_words * 2
        if len(content) < 4:
            break
        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type == 0:
            features.append({"type": "Polygon", "coordinates": []})
            continue
        if shape_type not in (5, 15, 25):
            features.append({"type": "Polygon", "coordinates": []})
            continue
        num_parts, num_points = struct.unpack("<ii", content[36:44])
        parts = struct.unpack("<" + "i" * num_parts, content[44 : 44 + 4 * num_parts])
        pts_off = 44 + 4 * num_parts
        points = struct.unpack("<" + "d" * (2 * num_points), content[pts_off : pts_off + 16 * num_points])
        rings: list[list[list[float]]] = []
        for i, start in enumerate(parts):
            end = parts[i + 1] if i + 1 < num_parts else num_points
            ring = [[points[2 * j], points[2 * j + 1]] for j in range(start, end)]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            rings.append(ring)
        if len(rings) == 1:
            geometry = {"type": "Polygon", "coordinates": rings}
        else:
            geometry = {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
        features.append(geometry)
    return features


def process_tpdc06(store: Store) -> dict[str, Any]:
    zip_path = _source_zip("tpdc_06_disaster_points")
    out = store.data_dir / "processed" / "tpdc06_points"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        shp = next((archive.read(n) for n in archive.namelist() if n.lower().endswith(".shp")), None)
        dbf = next((archive.read(n) for n in archive.namelist() if n.lower().endswith(".dbf")), None)
        prj = next((archive.read(n) for n in archive.namelist() if n.lower().endswith(".prj")), None)
    if shp is None or dbf is None:
        raise RuntimeError("TPDC-06 缺少 SHP/DBF")
    records, fields = _dbf_records(dbf)
    geometries = _shp_polygons(shp)
    features = []
    for index, record in enumerate(records):
        geometry = geometries[index] if index < len(geometries) else {"type": "Polygon", "coordinates": []}
        features.append(
            {
                "type": "Feature",
                "id": index + 1,
                "geometry": geometry,
                "properties": {k: v for k, v in record.items()},
            }
        )
    collection = {
        "type": "FeatureCollection",
        "name": "TPDC-06 吉隆县历史灾点（沟域多边形）",
        "crs_note": "坐标来自 SHP，标注为 CGCS2000；GeoJSON 按 WGS84 近似使用，差异 < 1 m。",
        "event_time_note": "属性中的 解译Time/影像Time 不是灾害发生时间；本数据不能做事件级概率校准。",
        "features": features,
    }
    geojson_path = out / "tpdc06_points.geojson"
    _write_json(geojson_path, collection)

    field_rows = []
    for name, ftype, length in fields:
        values = [r.get(name, "") for r in records]
        non_empty = [v for v in values if v not in ("", None)]
        note = ""
        if "解译" in name:
            note = "解译日期，不是事件发生时间"
        elif "影像" in name:
            note = "影像日期，不是事件发生时间"
        field_rows.append(
            {
                "field": name,
                "type": ftype,
                "length": length,
                "non_empty": len(non_empty),
                "example": non_empty[0] if non_empty else "",
                "note": note,
            }
        )
    fields_path = out / "tpdc06_fields.csv"
    pd.DataFrame(field_rows).to_csv(fields_path, index=False, encoding="utf-8-sig")

    bbox = struct.unpack("<4d", shp[36:68])
    manifest = {
        "dataset": "TPDC-06 历史灾点（沟域多边形）",
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "features": len(features),
        "fields": len(fields),
        "crs": (prj or b"").decode("utf-8", "replace")[:300],
        "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
        "has_event_time": False,
        "time_fields": [f for f in [x[0] for x in fields] if "Time" in f],
        "rules": [
            "属性与几何按记录序号一一对应",
            "解译Time/影像Time 不是事件发生时间",
            "84 个沟域不是 84 次独立事件；只能做空间登记标签",
            "GeoJSON 坐标按 WGS84 近似使用（原为 CGCS2000）",
        ],
        "outputs": [
            {"path": store.rel(geojson_path), "bytes": geojson_path.stat().st_size, "sha256": _sha256(geojson_path)},
            {"path": store.rel(fields_path), "bytes": fields_path.stat().st_size, "sha256": _sha256(fields_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def _raster_from_zip(zip_path: Path, suffix: str) -> tuple[Any, dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as archive:
        name = next((n for n in archive.namelist() if n.lower().endswith(suffix)), None)
        if name is None:
            raise FileNotFoundError(f"{zip_path.name} 中没有 {suffix}")
        data = archive.read(name)
    image = Image.open(io.BytesIO(data))
    array = np.asarray(image)
    tags = {
        33550: tuple(image.tag_v2.get(33550) or (None, None, None)),
        33922: tuple(image.tag_v2.get(33922) or (0, 0, 0, None, None, 0)),
        34735: tuple(image.tag_v2.get(34735) or ()),
        42113: image.tag_v2.get(42113),
    }
    return array, tags


def _write_geotiff(path: Path, array: Any, *, mode: str, tags: dict[str, Any], nodata: Any) -> None:
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    if tags.get(33550) and tags[33550][0] is not None:
        ifd[33550] = tuple(tags[33550])
    if tags.get(33922) and tags[33922][3] is not None:
        ifd[33922] = tuple(tags[33922])
    if tags.get(34735):
        ifd[34735] = tuple(tags[34735])
    ifd[42113] = str(nodata)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array, mode=mode).save(
        path,
        format="TIFF",
        tiffinfo=ifd,
        compression="tiff_lzw",
    )


def _d8_accumulation(dem: Any, dx_m: float, dy_m: float) -> tuple[Any, Any, int]:
    rows, cols = dem.shape
    offsets = [
        (-1, 0, dy_m),
        (1, 0, dy_m),
        (0, -1, dx_m),
        (0, 1, dx_m),
        (-1, -1, math.hypot(dx_m, dy_m)),
        (-1, 1, math.hypot(dx_m, dy_m)),
        (1, -1, math.hypot(dx_m, dy_m)),
        (1, 1, math.hypot(dx_m, dy_m)),
    ]
    best = np.zeros((rows, cols), dtype="float64")
    receiver = np.arange(rows * cols, dtype="int64").reshape(rows, cols)
    direction = np.zeros((rows, cols), dtype="uint8")
    for code, (di, dj, distance) in enumerate(offsets, start=1):
        i0, i1 = max(0, -di), min(rows, rows - di)
        j0, j1 = max(0, -dj), min(cols, cols - dj)
        if i0 >= i1 or j0 >= j1:
            continue
        source = dem[i0:i1, j0:j1]
        target = dem[i0 + di : i1 + di, j0 + dj : j1 + dj]
        drop = (source - target) / distance
        sub_best = best[i0:i1, j0:j1]
        sub_recv = receiver[i0:i1, j0:j1]
        sub_dir = direction[i0:i1, j0:j1]
        mask = drop > sub_best
        sub_best[mask] = drop[mask]
        flat = (np.arange(i0, i1)[:, None] * cols + np.arange(j0, j1)[None, :])[mask]
        sub_recv[mask] = flat + di * cols + dj
        sub_dir[mask] = code
    accumulation = np.ones(rows * cols, dtype="int64")
    receiver_flat = receiver.ravel()
    order = np.argsort(-dem.ravel(), kind="stable")
    for index in order:
        target = receiver_flat[index]
        if target != index:
            accumulation[target] += accumulation[index]
    return direction, accumulation.reshape(rows, cols).astype("float32"), int((direction == 0).sum())


def process_tpdc05(store: Store) -> dict[str, Any]:
    zip_path = _source_zip("tpdc_05_landcover")
    out = store.data_dir / "processed" / "tpdc05_landcover"
    out.mkdir(parents=True, exist_ok=True)
    array, tags = _raster_from_zip(zip_path, "2023.tif")
    mask = (array == 0).astype("uint8")

    # 不直接拷贝原始 TIFF（可能 90+ MB）；用 LZW 重写为带 nodata 的 2023 栅格。
    original = out / "jilong_LUCD_2023.tif"
    _write_geotiff(original, array, mode="L", tags=tags, nodata=0)
    mask_path = out / "jilong_LUCD_2023_nodata_mask.tif"
    _write_geotiff(mask_path, mask, mode="L", tags=tags, nodata=255)

    values, counts = np.unique(array, return_counts=True)
    total = int(array.size)
    valid_total = int((array != 0).sum())
    rows = []
    for value, count in zip(values, counts):
        code = int(value)
        rows.append(
            {
                "class_code": code,
                "count": int(count),
                "pct_total": round(int(count) / total * 100, 4),
                "pct_valid": round(int(count) / valid_total * 100, 4) if valid_total and code != 0 else 0.0,
                "note": "nodata" if code == 0 else "无官方图例；保留原始编码",
            }
        )
    class_path = out / "tpdc05_class_counts_2023.csv"
    pd.DataFrame(rows).to_csv(class_path, index=False, encoding="utf-8-sig")

    bbox = {
        "west": tags[33922][3],
        "north": tags[33922][4],
        "east": tags[33922][3] + tags[33550][0] * array.shape[1],
        "south": tags[33922][4] - tags[33550][1] * array.shape[0],
    }
    manifest = {
        "dataset": "TPDC-05 土地覆盖（2023）",
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "year": 2023,
        "shape": list(array.shape),
        "crs": "EPSG:4326",
        "bbox": bbox,
        "pixel_size_deg": [tags[33550][0], tags[33550][1]],
        "nodata": 0,
        "class_count": len(values),
        "valid_pixels": valid_total,
        "rules": [
            "0 为 nodata，不当作土地覆盖类别",
            "1–10 保留原始编码；附件无官方图例",
            "掩膜：1=nodata，0=有效",
        ],
        "outputs": [
            {"path": store.rel(original), "bytes": original.stat().st_size, "sha256": _sha256(original)},
            {"path": store.rel(mask_path), "bytes": mask_path.stat().st_size, "sha256": _sha256(mask_path)},
            {"path": store.rel(class_path), "bytes": class_path.stat().st_size, "sha256": _sha256(class_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def process_tpdc07(store: Store) -> dict[str, Any]:
    zip_path = _source_zip("tpdc_07_dem")
    out = store.data_dir / "processed" / "tpdc07_dem"
    out.mkdir(parents=True, exist_ok=True)
    dem, tags = _raster_from_zip(zip_path, ".tif")
    dem = dem.astype("float32")
    nodata = float(tags.get(42113)) if tags.get(42113) is not None else None
    valid = dem if nodata is None else dem[dem != nodata]
    # 原始 DEM 已是核心沟谷范围，no further clip; copy original bytes.
    with zipfile.ZipFile(zip_path) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".tif"))
        dem_path = out / "dem_core_30m.tif"
        dem_path.write_bytes(archive.read(name))

    sx, sy = float(tags[33550][0]), float(tags[33550][1])
    lat = float(tags[33922][4]) - sy * dem.shape[0] / 2
    dx_m = sx * 111320.0 * math.cos(math.radians(lat))
    dy_m = sy * 110574.0
    dzdy, dzdx = np.gradient(dem, dy_m, dx_m)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype("float32")
    direction, accumulation, sinks = _d8_accumulation(dem, dx_m, dy_m)
    channel_threshold = 1000
    channel = (accumulation >= channel_threshold).astype("uint8")

    slope_path = out / "slope_deg.tif"
    _write_geotiff(slope_path, slope, mode="F", tags=tags, nodata=-9999)
    acc_path = out / "flow_accumulation_cells.tif"
    _write_geotiff(acc_path, accumulation, mode="F", tags=tags, nodata=-9999)
    dir_path = out / "flow_direction_d8.tif"
    _write_geotiff(dir_path, direction, mode="L", tags=tags, nodata=255)
    channel_path = out / "channel_mask_acc1000.tif"
    _write_geotiff(channel_path, channel, mode="L", tags=tags, nodata=255)

    channel_slope = slope[channel == 1]
    stats = [
        {"metric": "dem_min_m", "value": round(float(valid.min()), 2), "note": "有效像元"},
        {"metric": "dem_max_m", "value": round(float(valid.max()), 2), "note": "有效像元"},
        {"metric": "dem_mean_m", "value": round(float(valid.mean()), 2), "note": "有效像元"},
        {"metric": "slope_mean_deg", "value": round(float(slope.mean()), 3), "note": "全图"},
        {"metric": "slope_max_deg", "value": round(float(slope.max()), 3), "note": "全图"},
        {"metric": "flow_accum_max_cells", "value": int(accumulation.max()), "note": "未填洼 D8"},
        {"metric": "flow_accum_p99_cells", "value": round(float(np.percentile(accumulation, 99)), 1), "note": "未填洼 D8"},
        {"metric": "sink_cells", "value": sinks, "note": "D8 无下游的单元；未填洼"},
        {"metric": "channel_threshold_cells", "value": channel_threshold, "note": "channel_mask = accum >= 阈值"},
        {"metric": "channel_cells", "value": int(channel.sum()), "note": "channel_mask=1"},
        {"metric": "channel_slope_mean_deg", "value": round(float(channel_slope.mean()), 3) if channel_slope.size else None, "note": "沟道像元坡度均值"},
        {"metric": "channel_slope_median_deg", "value": round(float(np.median(channel_slope)), 3) if channel_slope.size else None, "note": "沟道像元坡度中位数"},
        {"metric": "pixel_dx_m", "value": round(dx_m, 2), "note": "按中心纬度估算"},
        {"metric": "pixel_dy_m", "value": round(dy_m, 2), "note": "按中心纬度估算"},
    ]
    stats_path = out / "tpdc07_terrain_stats.csv"
    pd.DataFrame(stats).to_csv(stats_path, index=False, encoding="utf-8-sig")

    bbox = {
        "west": tags[33922][3],
        "north": tags[33922][4],
        "east": tags[33922][3] + sx * dem.shape[1],
        "south": tags[33922][4] - sy * dem.shape[0],
    }
    manifest = {
        "dataset": "TPDC-07 DEM 派生地形（核心沟谷）",
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shape": list(dem.shape),
        "crs": "EPSG:4326",
        "bbox": bbox,
        "pixel_size_deg": [sx, sy],
        "pixel_size_m": [round(dx_m, 2), round(dy_m, 2)],
        "nodata": nodata,
        "sink_cells": sinks,
        "channel_threshold_cells": channel_threshold,
        "d8_codes": {"1": "N", "2": "S", "3": "W", "4": "E", "5": "NW", "6": "NE", "7": "SW", "8": "SE", "0": "sink/undefined"},
        "rules": [
            "DEM 已是核心沟谷范围，未再裁剪",
            "坡度用 np.gradient（米制间距，中心纬度近似）",
            "D8 未填洼；sink 单元 accumulation 终止，统计中报告 sink 数",
            "channel_mask = flow_accumulation >= 1000 cells；阈值可调",
            "原始 DEM 只读，派生层可重建",
        ],
        "outputs": [
            {"path": store.rel(dem_path), "bytes": dem_path.stat().st_size, "sha256": _sha256(dem_path)},
            {"path": store.rel(slope_path), "bytes": slope_path.stat().st_size, "sha256": _sha256(slope_path)},
            {"path": store.rel(acc_path), "bytes": acc_path.stat().st_size, "sha256": _sha256(acc_path)},
            {"path": store.rel(dir_path), "bytes": dir_path.stat().st_size, "sha256": _sha256(dir_path)},
            {"path": store.rel(channel_path), "bytes": channel_path.stat().st_size, "sha256": _sha256(channel_path)},
            {"path": store.rel(stats_path), "bytes": stats_path.stat().st_size, "sha256": _sha256(stats_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def build_processed(store: Store, *, batch: str = "1") -> dict[str, Any]:
    if pd is None or np is None or Image is None or TiffImagePlugin is None:
        raise RuntimeError("缺少 pandas/numpy/Pillow；请安装 requirements.txt")
    if batch not in {"1", "2", "3", "4", "5", "6", "7", "8", "all"}:
        raise ValueError("batch 只能是 1–8 或 all")
    results: list[dict[str, Any]] = []
    if batch in {"1", "all"}:
        results.extend([process_tpdc01(store), process_tpdc02(store), process_tpdc06(store)])
    if batch in {"2", "all"}:
        results.extend([process_tpdc05(store), process_tpdc07(store)])
    if batch in {"3", "all"}:
        from .spatial import process_main_channel

        results.append(process_main_channel(store))
    if batch in {"4", "all"}:
        from .spatial import process_gully_overlay

        results.append(process_gully_overlay(store))
    if batch in {"5", "all"}:
        from .spatial import process_channel_sensitivity

        results.append(process_channel_sensitivity(store))
    if batch in {"6", "all"}:
        from .susceptibility import process_susceptibility

        results.append(process_susceptibility(store))
    if batch in {"7", "all"}:
        from .events import process_event_catalog

        results.append(process_event_catalog(store))
    if batch in {"8", "all"}:
        from .glacier import process_tpdc03, process_tpdc04, process_tpdc08

        results.extend([process_tpdc03(store), process_tpdc04(store), process_tpdc08(store)])
    processed = store.data_dir / "processed"
    all_datasets: list[str] = []
    all_outputs: list[dict[str, Any]] = []
    for manifest_path in sorted(processed.glob("*/manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("dataset"):
            all_datasets.append(payload["dataset"])
        all_outputs.extend(payload.get("outputs") or [])
    manifest = {
        "batch": batch,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "datasets": all_datasets,
        "outputs": all_outputs,
        "notes": [
            "原始附件只读；processed 层可由 python -m mtmcm_data process --batch 1/2/all 重建",
            "缺失值不补零；QC=8 标记缺失；解译/影像时间不是事件时间",
        ],
    }
    _write_json(processed / "manifest.json", manifest)
    readme = [
        "# data/processed 基线",
        "",
        "> 由 `python -m mtmcm_data process --batch 1-8/all` 生成；原始附件只读。",
        "",
        "## 第一批（batch 1）",
        "",
        "- `tpdc01_hourly/tpdc01_key_vars_long.csv.gz`：时间×变量长表，含 `qc_flag`/`missing_flag`/`qc_missing`/`qc_suspect`；",
        "- `tpdc01_hourly/tpdc01_missing_by_variable.csv` + `tpdc01_variable_dictionary.csv`；",
        "- `tpdc02_temp/tpdc02_temp_long.csv.gz`：日期×县长表；`tpdc02_temp_wide.csv.gz`：宽表；",
        "- `tpdc06_points/tpdc06_points.geojson`：84 个沟域多边形 + 属性；`tpdc06_fields.csv`：字段字典。",
        "",
        "## 第二批（batch 2）",
        "",
        "- `tpdc05_landcover/jilong_LUCD_2023.tif`：2023 土地覆盖（LZW 重写，nodata=0）；",
        "- `tpdc05_landcover/jilong_LUCD_2023_nodata_mask.tif`：1=nodata，0=有效；",
        "- `tpdc05_landcover/tpdc05_class_counts_2023.csv`：类别计数（0=nodata）；",
        "- `tpdc07_dem/dem_core_30m.tif`：核心沟谷 DEM；",
        "- `tpdc07_dem/slope_deg.tif`：坡度（度）；",
        "- `tpdc07_dem/flow_accumulation_cells.tif`：D8 汇流累积（cells）；",
        "- `tpdc07_dem/flow_direction_d8.tif`：D8 流向（1–8，0=sink）；",
        "- `tpdc07_dem/channel_mask_acc1000.tif`：沟道掩膜（accum≥1000 cells）；",
        "- `tpdc07_dem/tpdc07_terrain_stats.csv`：地形统计。",
        "",
        "## 第三批（batch 3）",
        "",
        "- `tpdc07_channel/main_channel_profile.csv`：主流路纵剖面（距离/原始高程/路由高程/水力坡度/汇流）；",
        "- `tpdc07_channel/main_channel.geojson`：主流路 LineString；",
        "- `tpdc07_channel/main_channel_mask.tif`：主流路栅格；",
        "- `tpdc07_channel/dem_filled_30m.tif`、`flow_direction_filled_d8.tif`、`flow_accumulation_filled.tif`：填洼+epsilon 后的 D8 层；",
        "- `tpdc07_channel/main_channel_summary.json`：长度/落差/比降/源汇点/填洼前后 sink 数。",
        "",
        "## 第四批（batch 4）",
        "",
        "- `spatial_baseline/tpdc06_gully_overlay_stats.csv`：84 个沟域 × DEM/坡度/汇流/土地覆盖；",
        "- `spatial_baseline/tpdc06_gully_id_mask.tif`：沟域 ID 栅格（1–84，0=outside）；",
        "- `spatial_baseline/summary.json`：in_dem 数量、总像元、平均坡度等。",
        "",
        "## 第五批（batch 5）",
        "",
        "- `tpdc07_channel_sensitivity/main_channel_sensitivity_runs.csv`：3 个阈值 × 3 种填洼模式的 9 次主流路；",
        "- `tpdc07_channel_sensitivity/main_channel_sensitivity.geojson`：各次主流路 LineString；",
        "- `tpdc07_channel_sensitivity/summary.json`：长度/比降范围与推荐参数。",
        "",
        "## 第六批（batch 6）",
        "",
        "- `q2_susceptibility/q2_susceptibility_score.tif`：WOE 相对易发性分数；",
        "- `q2_susceptibility/q2_susceptibility_class.tif`：1–5 分级（背景 20/40/60/80 分位）；",
        "- `q2_susceptibility/q2_woe_bins.csv`：坡度/高程/汇流/土地覆盖的分箱 WOE；",
        "- `q2_susceptibility/q2_gully_scores.csv`：84 个沟域的均分与背景百分位；",
        "- `q2_susceptibility/summary.json`：全局/空间块 AUC、沟域百分位。",
        "",
        "## 第七批（batch 7）",
        "",
        "- `event_catalog/event_catalog.csv`：已确认事件（2026-08-26、2025-07-08、2002-05-23 区域 GLOF、2015 地震背景）；",
        "- `event_catalog/event_rainfall_windows.csv`：站点/Open-Meteo/NASA/CHIRPS 的事件窗口降水；",
        "- `event_catalog/chirps_daily_values.csv`：CHIRPS 独立日降水（0.05°）；",
        "- `event_catalog/event_rainfall_hourly.csv.gz`：事件窗口逐小时降水；",
        "- `event_catalog/evidence_register.csv`：证据登记（来源/访问日期/置信度）；",
        "- `event_catalog/event_catalog.md`：事件目录与“非降雨触发”结论。",
        "",
        "## 第八批（batch 8）",
        "",
        "- `tpdc03_glacier/tpdc03_tiles.csv`：168 个 TIFF 的逐幅统计；",
        "- `tpdc03_glacier/tpdc03_period_summary.csv`：4 个时段 × dhdt/dhdt_err × UTM/GCS 加权统计；",
        "- `tpdc04_glacier/*.tif`：10 个 NetCDF 变量的 UTM45N GeoTIFF；",
        "- `tpdc04_glacier/tpdc04_variables.csv`：变量/范围/均值/单位；",
        "- `tpdc08_population/tpdc08_population.csv`、GeoJSON、字段表：县级人口双口径。",
        "",
        "## 关键约束",
        "",
        "- TPDC-01 的 `9999.9`/`QC=8` 已标缺失，未补零；",
        "- TPDC-02 的 2025 只有 214 天，年度趋势需排除或标注；",
        "- TPDC-06 的 `解译Time`/`影像Time` 不是事件发生时间；84 个沟域不是 84 次事件；",
        "- TPDC-05 的 0 是 nodata，不是类别；1–10 无官方图例；",
        "- batch 2 的 D8 未填洼；batch 3 主流路用填洼+epsilon D8，两者不能混用；",
        "- batch 6 的 WOE 是相对易发性，不是概率；空间块 AUC 较弱，不能外推；",
        "- batch 7 只确认 2 个本地泥石流事件 + 1 个区域 GLOF 类比；2026/2025 均为冰崩/冰湖溃决触发，不是降雨触发；",
        "- batch 8 的 dhdt 单位未在附件给出；TPDC-04 冰厚为估算、速度为气候态；TPDC-08 只有县级；",
        "- 原始附件只读；派生层可由脚本重建。",
        "",
        "## 复现",
        "",
        "```powershell",
        "python -m mtmcm_data process --batch all",
        "```",
        "",
    ]
    (processed / "README.md").write_text("\n".join(readme), encoding="utf-8")
    return manifest
