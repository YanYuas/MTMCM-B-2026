from __future__ import annotations

import hashlib
import json
import re
import struct
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import WORKSPACE_ROOT, load_config
from .store import Store


try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore[assignment]


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
    _, _, _, _, nrec, hlen, rlen = struct.unpack("<BBBBIHH", data[:12])
    fields: list[tuple[str, str, int]] = []
    pos = 32
    while data[pos] != 0x0D:
        fd = data[pos : pos + 32]
        raw = fd[:11].split(b"\x00")[0]
        name = None
        for enc in ("utf-8", "gb18030", "gbk", "latin-1"):
            try:
                name = raw.decode(enc).strip()
                break
            except UnicodeDecodeError:
                continue
        fields.append((name or "?", chr(fd[11]), fd[16]))
        pos += 32
    records: list[dict[str, str]] = []
    for index in range(nrec):
        rec = data[hlen + index * rlen : hlen + (index + 1) * rlen]
        if len(rec) < rlen:
            break
        values: dict[str, str] = {}
        off = 1
        for name, _, length in fields:
            raw = rec[off : off + length]
            off += length
            for enc in ("utf-8", "gb18030", "gbk", "latin-1"):
                try:
                    values[name] = raw.decode(enc).strip()
                    break
                except UnicodeDecodeError:
                    continue
        records.append(values)
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


def build_processed(store: Store, *, batch: str = "1") -> dict[str, Any]:
    if pd is None:
        raise RuntimeError("缺少 pandas；请安装 requirements.txt")
    if batch != "1":
        raise NotImplementedError("当前只实现第一批（TPDC-01/02/06）；DEM/土地覆盖为第二批")
    results = [process_tpdc01(store), process_tpdc02(store), process_tpdc06(store)]
    processed = store.data_dir / "processed"
    manifest = {
        "batch": "1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "datasets": [r["dataset"] for r in results],
        "outputs": [o for r in results for o in r.get("outputs", [])],
        "notes": [
            "原始附件只读；processed 层可由 python -m mtmcm_data process --batch 1 重建",
            "缺失值不补零；QC=8 标记缺失；解译/影像时间不是事件时间",
        ],
    }
    _write_json(processed / "manifest.json", manifest)
    readme = [
        "# data/processed 第一批基线",
        "",
        "> 由 `python -m mtmcm_data process --batch 1` 生成；原始附件只读。",
        "",
        "## 内容",
        "",
        "- `tpdc01_hourly/tpdc01_key_vars_long.csv.gz`：时间×变量长表，含 `qc_flag`/`missing_flag`/`qc_missing`/`qc_suspect`；",
        "- `tpdc01_hourly/tpdc01_missing_by_variable.csv`：按变量缺测率汇总；",
        "- `tpdc02_temp/tpdc02_temp_long.csv.gz`：日期×县长表；`tpdc02_temp_wide.csv.gz`：宽表；",
        "- `tpdc06_points/tpdc06_points.geojson`：84 个沟域多边形 + 属性；",
        "- `tpdc06_points/tpdc06_fields.csv`：字段字典；",
        "- 每个数据集目录下有 `manifest.json`（源文件 sha256、规则、输出 sha256）。",
        "",
        "## 关键约束",
        "",
        "- TPDC-01 的 `9999.9`/`QC=8` 已标缺失，未补零；",
        "- TPDC-02 的 2025 只有 214 天，年度趋势需排除或标注；",
        "- TPDC-06 的 `解译Time`/`影像Time` 不是事件发生时间；84 个沟域不是 84 次事件；",
        "- 第二批（TPDC-05 土地覆盖、TPDC-07 DEM 派生层）尚未生成。",
        "",
        "## 复现",
        "",
        "```powershell",
        "python -m mtmcm_data process --batch 1",
        "```",
        "",
    ]
    (processed / "README.md").write_text("\n".join(readme), encoding="utf-8")
    return manifest
