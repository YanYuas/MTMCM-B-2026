from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from .config import load_config
from .dbf import read_dbf
from .process import _sha256, _shp_polygons, _write_geotiff, _write_json
from .store import Store


ROOT = Path(__file__).resolve().parents[1]


def _seven_zip() -> str:
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        return found
    fallback = Path(r"D:\Scoop\shims\7z.exe")
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError("找不到 7z；请安装 7-Zip 或把 7z 加入 PATH")


def _extract_rar(rar: Path, out: Path) -> None:
    if any(out.rglob("*.tif")):
        return
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_seven_zip(), "x", "-y", f"-o{out}", str(rar)],
        check=True,
        capture_output=True,
        text=True,
    )


def process_tpdc03(store: Store) -> dict[str, Any]:
    source = load_config().get("tpdc_03_glacier_rar")
    rar = source.local_mirror_path
    if rar is None or not rar.exists():
        raise FileNotFoundError("TPDC-03 RAR 不存在")
    raw_dir = store.data_dir / "raw" / "tpdc03_extracted"
    _extract_rar(rar, raw_dir)
    out = store.data_dir / "processed" / "tpdc03_glacier"
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for path in sorted(raw_dir.rglob("*.tif")):
        match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", path.name + "_" + str(path.parent))
        period = f"{match.group(1)}..{match.group(2)}" if match else "unknown"
        lowered = str(path).lower()
        variable = "dhdt_err" if "dhdt_err" in lowered else "dhdt"
        parent_name = path.parent.name.lower()
        crs = "UTM" if "utm" in parent_name else "GCS"
        image = Image.open(path)
        array = np.asarray(image).astype("float64")
        nodata = image.tag_v2.get(42113)
        try:
            nodata_value = float(nodata) if nodata is not None else None
        except Exception:
            nodata_value = None
        valid = np.isfinite(array)
        if nodata_value is not None:
            valid &= array != nodata_value
        values = array[valid]
        tags = image.tag_v2
        bbox = None
        if tags.get(33550) and tags.get(33922) and tags[33922][3] is not None:
            sx, sy = tags[33550][:2]
            west, north = tags[33922][3], tags[33922][4]
            bbox = {
                "west": round(float(west), 6),
                "north": round(float(north), 6),
                "east": round(float(west + sx * array.shape[1]), 6),
                "south": round(float(north - sy * array.shape[0]), 6),
            }
        rows.append(
            {
                "path": str(path.relative_to(raw_dir)),
                "period": period,
                "variable": variable,
                "crs_folder": crs,
                "width": int(array.shape[1]),
                "height": int(array.shape[0]),
                "valid_pixels": int(values.size),
                "min": round(float(values.min()), 5) if values.size else None,
                "max": round(float(values.max()), 5) if values.size else None,
                "mean": round(float(values.mean()), 6) if values.size else None,
                "sum": float(values.sum()) if values.size else 0.0,
                "nodata": nodata_value,
                "bbox": json.dumps(bbox, ensure_ascii=False) if bbox else "",
            }
        )
    if not rows:
        raise RuntimeError("TPDC-03 解压后没有 TIFF")
    tiles = pd.DataFrame(rows)
    tiles_path = out / "tpdc03_tiles.csv"
    tiles.to_csv(tiles_path, index=False, encoding="utf-8-sig")
    grouped = (
        tiles.groupby(["period", "variable", "crs_folder"], dropna=False)
        .agg(tiles=("path", "size"), valid_pixels=("valid_pixels", "sum"), sum_value=("sum", "sum"), min=("min", "min"), max=("max", "max"))
        .reset_index()
    )
    grouped["weighted_mean"] = (grouped["sum_value"] / grouped["valid_pixels"]).round(6)
    grouped = grouped.drop(columns=["sum_value"])
    summary_path = out / "tpdc03_period_summary.csv"
    grouped.to_csv(summary_path, index=False, encoding="utf-8-sig")
    manifest = {
        "dataset": "TPDC-03 冰川表面高程变化（2000–2020）",
        "source_rar": store.rel(rar),
        "source_sha256": _sha256(rar),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tiles": len(rows),
        "periods": sorted(tiles["period"].unique().tolist()),
        "variables": sorted(tiles["variable"].unique().tolist()),
        "crs_folders": sorted(tiles["crs_folder"].unique().tolist()),
        "rules": [
            "全量解压到 data/raw/tpdc03_extracted（不入库）",
            "逐 TIFF 读取标签/有效像元；不把 nodata 计入统计",
            "dhdt 与 dhdt_err 分开统计；UTM/GCS 分幅保留原文件夹标记",
            "均值按有效像元加权；年代际产品，不能外推为事件瞬时状态",
        ],
        "outputs": [
            {"path": store.rel(tiles_path), "bytes": tiles_path.stat().st_size, "sha256": _sha256(tiles_path)},
            {"path": store.rel(summary_path), "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def _h5_geotags(gt: Any) -> dict[int, Any]:
    # GeoTransform: x0, pixel_width, 0, y0, 0, -pixel_height（UTM45N）
    values = [float(x) for x in str(gt).split()]
    x0, dx, _, y0, _, dy = values[:6]
    geokeys = (
        1, 1, 0, 4,
        1024, 0, 1, 1,
        1025, 0, 1, 1,
        3072, 0, 1, 32645,
        3076, 0, 1, 9001,
    )
    return {
        33550: (abs(dx), abs(dy), 0.0),
        33922: (0.0, 0.0, 0.0, x0, y0, 0.0),
        34735: geokeys,
    }


def process_tpdc04(store: Store) -> dict[str, Any]:
    source = load_config().get("tpdc_04_glacier_nc")
    zip_path = source.local_mirror_path
    if zip_path is None or not zip_path.exists():
        raise FileNotFoundError("TPDC-04 ZIP 不存在")
    raw_dir = store.data_dir / "raw" / "tpdc04_extracted"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        name = next((n for n in archive.namelist() if n.lower().endswith(".nc")), None)
        if name is None:
            raise FileNotFoundError("TPDC-04 ZIP 中没有 .nc")
        nc_path = raw_dir / Path(name).name
        nc_path.write_bytes(archive.read(name))

    sys.path.insert(0, str(ROOT / ".deps"))
    try:
        import h5py
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("TPDC-04 需要 h5py；请安装 h5py>=3.10") from exc

    out = store.data_dir / "processed" / "tpdc04_glacier"
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    written: list[Path] = []
    with h5py.File(nc_path, "r") as handle:
        global_attrs = {k: str(v) for k, v in handle.attrs.items()}
        gt = None
        if "spatial_ref" in handle:
            gt = handle["spatial_ref"].attrs.get("GeoTransform")
        tags = _h5_geotags(gt) if gt else {}
        for name, dataset in handle.items():
            if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 2:
                continue
            array = np.asarray(dataset, dtype="float64")
            fill = dataset.attrs.get("_FillValue")
            valid = np.isfinite(array)
            if fill is not None and np.isfinite(fill):
                valid &= array != float(fill)
            values = array[valid]
            rows.append(
                {
                    "variable": name,
                    "shape": "x".join(str(x) for x in array.shape),
                    "dtype": str(dataset.dtype),
                    "valid_pixels": int(values.size),
                    "min": round(float(values.min()), 4) if values.size else None,
                    "max": round(float(values.max()), 4) if values.size else None,
                    "mean": round(float(values.mean()), 4) if values.size else None,
                    "units": str(dataset.attrs.get("units", "")),
                    "long_name": str(dataset.attrs.get("long_name", "")),
                }
            )
            if tags:
                tif = out / f"{name}.tif"
                _write_geotiff(tif, np.where(valid, array, -9999).astype("float32"), mode="F", tags=tags, nodata=-9999)
                written.append(tif)

    variables_path = out / "tpdc04_variables.csv"
    pd.DataFrame(rows).to_csv(variables_path, index=False, encoding="utf-8-sig")
    attrs_path = out / "tpdc04_attrs.json"
    _write_json(attrs_path, global_attrs)
    thickness = next((r for r in rows if r["variable"] == "thickness"), None)
    volume_km3 = None
    if thickness and thickness["mean"] is not None:
        volume_km3 = round(float(thickness["mean"]) * int(thickness["valid_pixels"]) * 900.0 / 1e9, 5)
    summary = {
        "dataset": "TPDC-04 冰川地形/冰厚/表面速度",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "crs": "EPSG:32645（WGS 84 / UTM zone 45N）",
        "shape": [int(handle_shape) for handle_shape in rows[0]["shape"].split("x")] if rows else [],
        "variables": [r["variable"] for r in rows],
        "thickness_volume_km3": volume_km3,
        "rules": [
            "用 h5py 读取 NetCDF4/HDF5 数组；不再只读字符串",
            "NaN/_FillValue 标为无效；GeoTIFF 输出用 -9999 表示无效",
            "冰厚来自 Farinotti et al. 2019 估算；速度为 2014–2024 气候态，不是事件瞬时值",
            "GeoTransform 来自 spatial_ref；UTM45N，30 m",
        ],
        "outputs": [{"path": store.rel(p), "bytes": p.stat().st_size, "sha256": _sha256(p)} for p in [variables_path, attrs_path, *written]],
    }
    summary_path = out / "summary.json"
    _write_json(summary_path, summary)
    manifest = {**summary, "source_file": store.rel(nc_path)}
    _write_json(out / "manifest.json", manifest)
    return manifest


def process_tpdc08(store: Store) -> dict[str, Any]:
    source = load_config().get("tpdc_08_population")
    zip_path = source.local_mirror_path
    if zip_path is None or not zip_path.exists():
        raise FileNotFoundError("TPDC-08 ZIP 不存在")
    with zipfile.ZipFile(zip_path) as archive:
        shp = next((archive.read(n) for n in archive.namelist() if n.lower().endswith(".shp")), None)
        dbf = next((archive.read(n) for n in archive.namelist() if n.lower().endswith(".dbf")), None)
        prj = next((archive.read(n) for n in archive.namelist() if n.lower().endswith(".prj")), None)
    if shp is None or dbf is None:
        raise RuntimeError("TPDC-08 缺少 SHP/DBF")
    records, fields, encoding = read_dbf(dbf)
    geometries = _shp_polygons(shp)
    out = store.data_dir / "processed" / "tpdc08_population"
    out.mkdir(parents=True, exist_ok=True)

    population_path = out / "tpdc08_population.csv"
    pd.DataFrame(records).to_csv(population_path, index=False, encoding="utf-8-sig")
    field_rows = []
    for name, ftype, length in fields:
        values = [r.get(name, "") for r in records]
        non_empty = [v for v in values if v not in ("", None)]
        field_rows.append({"field": name, "type": ftype, "length": length, "non_empty": len(non_empty), "example": non_empty[0] if non_empty else ""})
    fields_path = out / "tpdc08_fields.csv"
    pd.DataFrame(field_rows).to_csv(fields_path, index=False, encoding="utf-8-sig")

    features = []
    for index, record in enumerate(records):
        geometry = geometries[index] if index < len(geometries) else {"type": "Polygon", "coordinates": []}
        features.append({"type": "Feature", "id": index + 1, "geometry": geometry, "properties": {k: v for k, v in record.items()}})
    geojson_path = out / "tpdc08_population.geojson"
    _write_json(
        geojson_path,
        {
            "type": "FeatureCollection",
            "name": "TPDC-08 吉隆县第七次人口普查",
            "crs_note": "原 SHP 为 GCS_WGS_1984；GeoJSON 按 WGS84 使用。",
            "features": features,
        },
    )
    record = records[0] if records else {}
    summary = {
        "dataset": "TPDC-08 吉隆县第七次人口普查",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_zip": store.rel(zip_path),
        "source_sha256": _sha256(zip_path),
        "records": len(records),
        "fields": len(fields),
        "encoding": encoding,
        "crs": (prj or b"").decode("utf-8", "replace")[:300],
        "合计": record.get("合计"),
        "人口数": record.get("人口数"),
        "male": record.get("男"),
        "female": record.get("女"),
        "urban": record.get("城镇人"),
        "rural": record.get("乡村人"),
        "households": record.get("户数"),
        "notes": [
            "县级单一 polygon；无居民点，不能按面积均摊到沟道",
            "‘合计’与‘人口数’口径不同，引用时必须写明用哪一个",
        ],
        "outputs": [
            {"path": store.rel(population_path), "bytes": population_path.stat().st_size, "sha256": _sha256(population_path)},
            {"path": store.rel(fields_path), "bytes": fields_path.stat().st_size, "sha256": _sha256(fields_path)},
            {"path": store.rel(geojson_path), "bytes": geojson_path.stat().st_size, "sha256": _sha256(geojson_path)},
        ],
    }
    _write_json(out / "summary.json", summary)
    _write_json(out / "manifest.json", {**summary, "source_file": store.rel(zip_path)})
    return summary
