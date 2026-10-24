from __future__ import annotations

import csv
import io
import json
import re
import struct
import subprocess
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .audit import EVENT_TIME, read_station_rows, window_stats
from .config import Source, WORKSPACE_ROOT, load_config
from .dbf import read_dbf
from .store import Store


try:  # 审计依赖，运行时缺失则优雅降级
    import numpy as np
    import pandas as pd
    from PIL import Image
except Exception:  # pragma: no cover - 环境缺依赖时仍可生成说明
    np = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]


ATTACH_DIR = WORKSPACE_ROOT / "05_辅助文档" / "题目附件" / "附件"
TPDC_IDS = {
    "tpdc_01_hourly": "（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip",
    "tpdc_02_temp": "（2）2005-2025年吉隆县及周边县市逐日平均气温数据.zip",
    "tpdc_03_glacier_rar": "（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar",
    "tpdc_04_glacier_nc": "（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip",
    "tpdc_05_landcover": "（5）西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）.zip",
    "tpdc_06_disaster_points": "（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip",
    "tpdc_07_dem": "（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip",
    "tpdc_08_population": "（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip",
}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _zip_member(zip_path: Path, suffixes: tuple[str, ...]) -> tuple[str, bytes] | None:
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if name.lower().endswith(suffixes):
                return name, archive.read(name)
    return None


def _dbf_records(data: bytes) -> tuple[list[dict[str, str]], list[str]]:
    records, fields, _ = read_dbf(data)
    return records, [name for name, _, _ in fields]


def _shp_header(data: bytes) -> dict[str, Any]:
    shape_type = struct.unpack("<i", data[32:36])[0]
    bbox = struct.unpack("<4d", data[36:68])
    return {
        "shape_type": shape_type,
        "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
    }


def _tiff_profile(data: bytes, *, unique: bool = False) -> dict[str, Any]:
    image = Image.open(io.BytesIO(data))
    tags = image.tag_v2
    width, height = image.size
    scale = tags.get(33550) or (None, None, None)
    tie = tags.get(33922) or (0, 0, 0, None, None, 0)
    nodata_raw = tags.get(42113)
    info: dict[str, Any] = {
        "width": width,
        "height": height,
        "mode": image.mode,
        "pixel_size_deg": (scale[0], scale[1]),
        "origin": (tie[3], tie[4]),
        "nodata": nodata_raw,
        "bbox": {
            "west": tie[3],
            "north": tie[4],
            "east": tie[3] + scale[0] * width if scale[0] else None,
            "south": tie[4] - scale[1] * height if scale[1] else None,
        },
    }
    if np is not None:
        arr = np.asarray(image)
        nodata = None
        try:
            nodata = float(nodata_raw) if nodata_raw is not None else None
        except (TypeError, ValueError):
            nodata = None
        if unique:
            values, counts = np.unique(arr, return_counts=True)
            info["classes"] = [
                {"value": int(v), "count": int(c)} for v, c in zip(values, counts)
            ]
            info["class_count"] = len(values)
        else:
            numeric = arr.astype("float64")
            if nodata is not None:
                valid = numeric[numeric != nodata]
                info["nodata_count"] = int((numeric == nodata).sum())
            else:
                valid = numeric.reshape(-1)
                info["nodata_count"] = 0
            if valid.size:
                info["min"] = float(valid.min())
                info["max"] = float(valid.max())
                info["mean"] = round(float(valid.mean()), 2)
                info["valid_count"] = int(valid.size)
    return info


def _hdf5_hints(data: bytes) -> dict[str, Any]:
    strings = [s.decode("ascii", "ignore") for s in re.findall(rb"[ -~]{4,}", data)]
    unique: list[str] = []
    for text in strings:
        if text not in unique:
            unique.append(text)
    joined = "\n".join(unique)
    variables = sorted(
        set(
            re.findall(
                r"(?:climatological_[a-z_]+|vx_amplitude|vy_amplitude|velocity_amplitude|"
                r"dem_30m\.tif|slope_30m\.tif|thickness_30m\.tif|[a-z_]*velocity[a-z_]*)",
                joined,
            )
        )
    )
    crs = ""
    m = re.search(r'PROJCS\["([^"]+)"', joined)
    if m:
        crs = m.group(1)
        if "UTM zone 45N" in crs:
            crs += "（EPSG:32645）"
    geo = ""
    for text in unique:
        if re.match(r"^[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+$", text):
            geo = text
            break
    return {
        "format": "HDF5 / NetCDF4" if data.startswith(b"\x89HDF") else "unknown",
        "variables_hint": variables,
        "crs_hint": crs,
        "geotransform_hint": geo,
        "strings_count": len(unique),
    }


def _rar_profile(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["7z", "l", "-sccUTF-8", "-ba", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"7z 不可用: {exc}"}
    lines = [line for line in result.stdout.splitlines() if ".tif" in line.lower()]
    names = [line.split()[-1] for line in lines]
    periods = sorted(set(re.findall(r"rgi60_(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})", "\n".join(names))))
    return {
        "tif_count": len(lines),
        "periods": periods,
        "sample": names[:3],
        "error": result.stderr.strip()[:200] if result.returncode != 0 else "",
    }


def _csv_profile(zip_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"files": 0, "rows": 0, "by_type": {}, "time_min": None, "time_max": None}
    key_vars = {
        "MET": ["Ta_2m(degree C)", "Precip(mm)"],
        "SOIL": ["VWC_0.4m(m3/m3)"],
        "RADM": ["Rsd(W/m2)"],
        "FLUX": ["H(W/m2)"],
    }
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(n for n in archive.namelist() if n.lower().endswith(".csv"))
        result["files"] = len(names)
        for name in names:
            frame = pd.read_csv(io.BytesIO(archive.read(name)), encoding="utf-8-sig")
            result["rows"] += len(frame)
            prefix = Path(name).name.split("_")[0]
            result["by_type"].setdefault(prefix, 0)
            result["by_type"][prefix] += len(frame)
            times = pd.to_datetime(frame["Timestamp"], errors="coerce")
            if times.notna().any():
                tmin, tmax = times.min(), times.max()
                if result["time_min"] is None or tmin < result["time_min"]:
                    result["time_min"] = tmin
                if result["time_max"] is None or tmax > result["time_max"]:
                    result["time_max"] = tmax
    # 关键变量缺测率
    missing: dict[str, Any] = {}
    for prefix, columns in key_vars.items():
        frames = []
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                if Path(name).name.startswith(prefix) and name.lower().endswith(".csv"):
                    frames.append(pd.read_csv(io.BytesIO(archive.read(name)), encoding="utf-8-sig"))
        if not frames:
            continue
        frame = pd.concat(frames, ignore_index=True)
        times = pd.to_datetime(frame.get("Timestamp"), errors="coerce") if "Timestamp" in frame else None
        for column in columns:
            if column not in frame:
                continue
            series = pd.to_numeric(frame[column], errors="coerce")
            valid = (series != 9999.9) & series.notna()
            miss = int((~valid).sum())
            missing[column] = {
                "rows": len(frame),
                "missing": miss,
                "missing_rate_pct": round(miss / len(frame) * 100, 2),
                "min": None if series[valid].empty else float(series[valid].min()),
                "max": None if series[valid].empty else float(series[valid].max()),
            }
            if prefix == "MET" and times is not None and valid.any():
                result.setdefault("valid_time", {})
                result["valid_time"][column] = {
                    "start": str(times[valid].min()),
                    "end": str(times[valid].max()),
                }
    result["missing"] = missing
    return result


def _xlsx_profile(zip_path: Path) -> dict[str, Any]:
    files = 0
    rows = 0
    years: list[dict[str, Any]] = []
    missing = 0
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(n for n in archive.namelist() if n.lower().endswith(".xlsx"))
        files = len(names)
        for name in names:
            frame = pd.read_excel(io.BytesIO(archive.read(name)))
            rows += len(frame)
            missing += int(frame.isna().sum().sum())
            years.append(
                {
                    "file": Path(name).name,
                    "rows": len(frame),
                    "start": str(frame["时间"].min()),
                    "end": str(frame["时间"].max()),
                }
            )
    return {"files": files, "rows": rows, "missing": missing, "years": years}


def _station_event_window(zip_path: Path) -> dict[str, Any]:
    rows = read_station_rows(zip_path)
    stats = window_stats(
        rows,
        column="Precip(mm)",
        start=EVENT_TIME - timedelta(hours=72),
        end=EVENT_TIME,
    )
    return stats


def build_existing_audit(store: Store) -> tuple[Path, Path, list[dict[str, Any]]]:
    if pd is None or Image is None or np is None:
        raise RuntimeError("缺少 pandas/numpy/Pillow；请先安装 requirements.txt 中的审计依赖")

    profiles: dict[str, dict[str, Any]] = {}

    # TPDC-01
    zip01 = ATTACH_DIR / TPDC_IDS["tpdc_01_hourly"]
    p01 = _csv_profile(zip01)
    p01["event_window"] = _station_event_window(zip01)
    profiles["tpdc_01_hourly"] = p01

    # TPDC-02
    profiles["tpdc_02_temp"] = _xlsx_profile(ATTACH_DIR / TPDC_IDS["tpdc_02_temp"])

    # TPDC-03
    profiles["tpdc_03_glacier_rar"] = _rar_profile(ATTACH_DIR / TPDC_IDS["tpdc_03_glacier_rar"])

    # TPDC-04
    nc = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_04_glacier_nc"], (".nc",))
    nc_info = _hdf5_hints(nc[1]) if nc else {}
    profiles["tpdc_04_glacier_nc"] = {
        "member": Path(nc[0]).name if nc else None,
        "bytes": len(nc[1]) if nc else 0,
        **nc_info,
    }

    # TPDC-05
    lc: list[dict[str, Any]] = []
    with zipfile.ZipFile(ATTACH_DIR / TPDC_IDS["tpdc_05_landcover"]) as archive:
        for name in sorted(n for n in archive.namelist() if n.lower().endswith(".tif")):
            info = _tiff_profile(archive.read(name), unique=True)
            info["name"] = Path(name).name
            lc.append(info)
    profiles["tpdc_05_landcover"] = {"rasters": lc}

    # TPDC-06
    shp06 = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_06_disaster_points"], (".shp",))
    dbf06 = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_06_disaster_points"], (".dbf",))
    prj06 = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_06_disaster_points"], (".prj",))
    records06, fields06 = _dbf_records(dbf06[1]) if dbf06 else ([], [])
    event_fields06 = [f for f in fields06 if "Time" in f and "解译" not in f and "影像" not in f]
    profiles["tpdc_06_disaster_points"] = {
        "records": len(records06),
        "fields": fields06,
        "shp": _shp_header(shp06[1]) if shp06 else None,
        "crs": _decode(prj06[1])[:300] if prj06 else "",
        "has_event_time": bool(event_fields06),
        "event_time_fields": event_fields06,
        "interpretation_field": next((f for f in fields06 if "解译" in f), ""),
    }

    # TPDC-07
    dem = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_07_dem"], (".tif",))
    profiles["tpdc_07_dem"] = _tiff_profile(dem[1]) if dem else {}

    # TPDC-08
    dbf08 = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_08_population"], (".dbf",))
    shp08 = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_08_population"], (".shp",))
    prj08 = _zip_member(ATTACH_DIR / TPDC_IDS["tpdc_08_population"], (".prj",))
    records08, fields08 = _dbf_records(dbf08[1]) if dbf08 else ([], [])
    profiles["tpdc_08_population"] = {
        "records": len(records08),
        "fields": fields08,
        "shp": _shp_header(shp08[1]) if shp08 else None,
        "crs": _decode(prj08[1])[:300] if prj08 else "",
        "first_record": records08[0] if records08 else {},
    }

    rows: list[dict[str, Any]] = []
    lines: list[str] = [
        "# 已有赛题数据治理审计（先内后外）",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "> 目标：先把赛题附件里的 8 组数据做成“可追溯、可复核、可建模”的基线，再决定外部补充。",
        "> 原则：原始附件只读；缺测不补零；不强行重采样；所有质量标记进入数据卡与模型不确定性。",
        "",
        "## 0. 先给结论",
        "",
        "- 8 组数据**都能读**，但成熟度不同：TPDC-01/02/05/06/07/08 可以直接进入清洗；TPDC-03 需按需解压；TPDC-04 是 HDF5/NetCDF4，需要 `xarray/netCDF4` 才能读数组。",
        "- 最大的质量问题不是“缺数据”，而是**标签/时点/口径**：TPDC-06 没有事件发生时间；TPDC-07 DEM 获取时点不明且实际范围只覆盖核心沟谷；TPDC-08 人口只有县级且存在不同统计口径。",
        "- 外部补充应排在“已有数据基线”之后；否则会重复、错配，甚至时间泄漏。",
        "",
        "## 1. 八组数据总览",
        "",
        "| 数据集 | 格式/文件 | 规模 | 时间 | 空间/CRS | 关键质量问题 | 治理动作 |",
        "|---|---|---|---|---|---|---|",
    ]

    def add_row(dataset: str, fmt: str, scale: str, time: str, space: str, quality: str, action: str) -> None:
        rows.append(
            {
                "dataset": dataset,
                "format": fmt,
                "scale": scale,
                "time": time,
                "space": space,
                "quality": quality,
                "action": action,
            }
        )
        lines.append(f"| {dataset} | {fmt} | {scale} | {time} | {space} | {quality} | {action} |")

    p = profiles["tpdc_01_hourly"]
    miss = p.get("missing", {})
    valid_ta = (p.get("valid_time") or {}).get("Ta_2m(degree C)") or {}
    add_row(
        "TPDC-01 逐小时观测",
        "24 CSV（MET/RADM/SOIL/FLUX）",
        f"{p['files']} 文件 / {p['rows']} 行",
        f"网格 {p['time_min']} → {p['time_max']}；有效 {valid_ta.get('start', '?')} → {valid_ta.get('end', '?')}",
        "单点 28.86N/85.29E/4140m",
        f"MET/SOIL 缺测约 {miss.get('Ta_2m(degree C)', {}).get('missing_rate_pct', '?')}%；FLUX 约 {miss.get('H(W/m2)', {}).get('missing_rate_pct', '?')}%；2026-08-27 后基本缺测",
        "保留 9999.9/QC=8 为缺失；按变量算缺测率；事件窗口单独核对",
    )

    p = profiles["tpdc_02_temp"]
    y2025 = next((y for y in p["years"] if "2025" in y["file"]), None)
    add_row(
        "TPDC-02 逐日气温",
        "21 XLSX（5 县）",
        f"{p['files']} 文件 / {p['rows']} 行",
        f"2005-01-01 → 2025-08-02；2025 仅 {y2025['rows'] if y2025 else '?'} 天",
        "五县；84.45–86.16E, 28.26–29.32N",
        "2025 不完整；日尺度不能直接解释小时触发",
        "按县/日对齐；2025 只做背景，不做年度趋势",
    )

    p = profiles["tpdc_03_glacier_rar"]
    add_row(
        "TPDC-03 冰川变化",
        "RAR（TIFF 分幅）",
        f"{p.get('tif_count', '?')} 个 TIFF；{len(p.get('periods') or [])} 个时段",
        "2000–2020（4 个 5 年时段）",
        "200 km 周围；UTM/GCS 分幅",
        "268.9 MB；年代际产品；默认未下载",
        "只解压需要的时段/分幅；记录 dhdt 与 err 两套",
    )

    p = profiles["tpdc_04_glacier_nc"]
    add_row(
        "TPDC-04 冰川地形/冰厚/速度",
        "HDF5 / NetCDF4",
        f"{p.get('bytes', 0) / 1e6:.2f} MB；{p.get('strings_count', '?')} 个字符串",
        "冰崩前地形/冰厚；速度 2014–2024 气候态",
        "30 m；UTM45N（EPSG:32645）",
        "无 h5py/netCDF4 时只能读字符串；冰厚估算、速度气候态",
        "用 xarray 读取变量/维度；把冰厚/速度作为情景参数",
    )

    p = profiles["tpdc_05_landcover"]
    rasters = p.get("rasters") or []
    first = rasters[0] if rasters else {}
    add_row(
        "TPDC-05 土地覆盖",
        "4 GeoTIFF",
        f"{len(rasters)} 期；{first.get('width')}×{first.get('height')}",
        "2020–2023",
        "30 m；EPSG:4326",
        "0 为 nodata；1–10 无图例；2023 与 2026 事件有时间差",
        "保留原编码；0 不当类别；需要时补图例/重分类",
    )

    p = profiles["tpdc_06_disaster_points"]
    add_row(
        "TPDC-06 历史灾点",
        "SHP + DBF + PRJ",
        f"{p.get('records')} 个多边形；{len(p.get('fields') or [])} 字段",
        "无事件发生时间；只有解译/影像时间",
        "GCS2000；85.01–85.48E, 28.26–29.00N",
        "84 个沟域≠84 次事件；登记偏差未知",
        "只做空间登记标签；不做事件级概率校准",
    )

    p = profiles["tpdc_07_dem"]
    bbox = p.get("bbox") or {}
    add_row(
        "TPDC-07 DEM",
        "GeoTIFF",
        f"{p.get('width')}×{p.get('height')}；{p.get('valid_count', '?')} 有效像元",
        "2026-08-26 灾害区；获取时点未说明",
        f"30 m；EPSG:4326；实际 {bbox.get('west'):.4f}–{bbox.get('east'):.4f}E, {bbox.get('south'):.4f}–{bbox.get('north'):.4f}N" if bbox.get("west") is not None else "30 m；EPSG:4326",
        f"元数据 bbox 84.45–86.16 与实际范围不一致；高程 {p.get('min'):.0f}–{p.get('max'):.0f} m；不能预设为灾前",
        "先核获取时点；只用实际覆盖区；做 30 m 分辨率敏感性",
    )

    p = profiles["tpdc_08_population"]
    rec = p.get("first_record") or {}
    add_row(
        "TPDC-08 人口普查",
        "SHP + DBF + PRJ",
        f"{p.get('records')} 个县多边形；{len(p.get('fields') or [])} 字段",
        "第七次人口普查（年度/普查口径）",
        "WGS84（.prj）；县多边形",
        f"合计 {rec.get('合计', '?')}；另有‘人口数’ {rec.get('人口数', '?')}（口径不同）；无居民点",
        "只做县级暴露背景；不按面积均匀分配到沟道",
    )

    # 逐数据集细节
    lines.extend(["", "## 2. 逐数据集细节", ""])

    p = profiles["tpdc_01_hourly"]
    valid_ta = (p.get("valid_time") or {}).get("Ta_2m(degree C)") or {}
    lines.extend(
        [
            "### 2.1 TPDC-01 逐小时观测",
            "",
            f"- 文件：{p['files']} 个 CSV；总行数 {p['rows']}；文件时间网格 {p['time_min']} → {p['time_max']}（UTC+8）。",
            f"- 有效观测（以 `Ta_2m` 计）：{valid_ta.get('start', '?')} → {valid_ta.get('end', '?')}；2026-08-27 之后基本缺测。",
            f"- 事件前 72 h 降水：{p['event_window']['valid']}/{p['event_window']['slots']} 有效，累计 {p['event_window']['sum']} mm。",
            "- 关键变量缺测率：",
            "",
            "| 变量 | 行数 | 缺测 | 缺测率 | 最小 | 最大 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for col, info in (p.get("missing") or {}).items():
        lines.append(
            f"| `{col}` | {info['rows']} | {info['missing']} | {info['missing_rate_pct']}% | "
            f"{info['min']} | {info['max']} |"
        )
    lines.extend(
        [
            "",
            "- 处理规则：`9999.9` 与 `QC=8` 一律标缺失，**不补零**；`Rsd` 出现负值（最小约 -175.6 W/m²）要按 QC 标记为可疑，不直接当有效辐射。",
            "- 2021/2026 的 `Precip` 分别有约 2,776/3,040 个 9999.9；2026 时间网格到 12-31，但有效观测止于 08-27，不能把后段当有效。",
            "",
        ]
    )

    p = profiles["tpdc_02_temp"]
    lines.extend(
        [
            "### 2.2 TPDC-02 逐日气温",
            "",
            f"- {p['files']} 个 XLSX，{p['rows']} 行，缺失值 {p['missing']}；列：时间 + 吉隆/聂拉木/萨嘎/定日/昂仁。",
            "- 2025 年只有 214 天（到 2025-08-02）；年度趋势必须排除 2025 或明确标注。",
            "- 处理规则：按县拆分长表；日期统一为 `YYYY-MM-DD`；不做小时插值。",
            "",
        ]
    )

    p = profiles["tpdc_03_glacier_rar"]
    lines.extend(
        [
            "### 2.3 TPDC-03 冰川变化 RAR",
            "",
            f"- {p.get('tif_count', '?')} 个 TIFF，{len(p.get('periods') or [])} 个时段：{', '.join(p.get('periods') or [])}。",
            "- 含 `dhdt` 与 `dhdt_err` 两套；不要只取 dhdt 而忽略误差。",
            "- 处理规则：按需解压到 `data/processed/glacier/`；先选研究区相交分幅；记录每个文件的时段与 CRS。",
            "",
        ]
    )

    p = profiles["tpdc_04_glacier_nc"]
    lines.extend(
        [
            "### 2.4 TPDC-04 冰川地形/冰厚/速度",
            "",
            f"- 格式：{p.get('format')}；文件 {p.get('member')}；{p.get('bytes', 0) / 1e6:.2f} MB。",
            f"- 变量线索：{', '.join(p.get('variables_hint') or []) or '需 xarray 读取'}。",
            f"- CRS 线索：{p.get('crs_hint') or 'UTM45N（EPSG:32645）'}。",
            "- 处理规则：用 `xarray` 读取维度/变量；冰厚为估算、速度为 2014–2024 气候态，只能作为情景参数。",
            "",
        ]
    )

    p = profiles["tpdc_05_landcover"]
    lines.extend(["### 2.5 TPDC-05 土地覆盖", ""])
    for raster in p.get("rasters") or []:
        classes = raster.get("classes") or []
        top = sorted(classes, key=lambda x: -x["count"])[:6]
        lines.append(
            f"- `{raster['name']}`：{raster['width']}×{raster['height']}，{raster['mode']}，nodata={raster.get('nodata')}；"
            f"类别数 {raster.get('class_count')}；主要取值 " + ", ".join(f"{x['value']}({x['count']})" for x in top)
        )
    lines.extend(
        [
            "",
            "- 处理规则：`0` 是 nodata，不是“无覆盖”类别；1–10 保留原编码，补图例后再重分类。",
            "",
        ]
    )

    p = profiles["tpdc_06_disaster_points"]
    lines.extend(
        [
            "### 2.6 TPDC-06 历史灾点",
            "",
            f"- {p.get('records')} 个多边形；{len(p.get('fields') or [])} 个字段；CRS：{p.get('crs') or 'GCS2000'}。",
            f"- 时间字段：{'有' if p.get('has_event_time') else '无事件发生时间'}；解译字段：{p.get('interpretation_field') or '—'}。",
            "- 处理规则：只做“登记沟域”空间标签；不能把多边形数量当独立灾害次数；不能做事件级 95% 覆盖率。",
            "",
        ]
    )

    p = profiles["tpdc_07_dem"]
    bbox = p.get("bbox") or {}
    lines.extend(
        [
            "### 2.7 TPDC-07 DEM",
            "",
            f"- {p.get('width')}×{p.get('height')}，{p.get('mode')}，nodata={p.get('nodata')}；有效像元 {p.get('valid_count')}，"
            f"高程 {p.get('min'):.1f}–{p.get('max'):.1f} m，均值 {p.get('mean')} m。",
            f"- 实际范围：{bbox.get('west'):.4f}–{bbox.get('east'):.4f}E, {bbox.get('south'):.4f}–{bbox.get('north'):.4f}N；"
            "元数据 bbox 84.45–86.16E 是更大的灾害区范围，**不能把实际 DEM 当全县 DEM**。",
            "- 处理规则：先核获取时点；做坡度/汇流前确认投影与分辨率；不要把 30 m 结果写成“高精度”。",
            "",
        ]
    )

    p = profiles["tpdc_08_population"]
    rec = p.get("first_record") or {}
    lines.extend(
        [
            "### 2.8 TPDC-08 人口普查",
            "",
            f"- {p.get('records')} 个县多边形；字段 {len(p.get('fields') or [])} 个；CRS：{p.get('crs') or 'GCS2000'}。",
            f"- 合计 {rec.get('合计', '?')}；男 {rec.get('男', '?')}、女 {rec.get('女', '?')}；城镇 {rec.get('城镇人', '?')}、乡村 {rec.get('乡村人', '?')}；户数 {rec.get('户数', '?')}。",
            f"- 注意：另有“人口数”字段 {rec.get('人口数', '?')}，与“合计”口径不同；论文必须说明用哪一个。",
            "- 处理规则：只做县级暴露背景；不按县面积均匀分配到沟道；不输出个位人数。",
            "",
        ]
    )

    # 治理流水线
    lines.extend(
        [
            "## 3. 已有数据的治理流水线（建议按顺序）",
            "",
            "1. **登记与冻结**：原始附件只读；记录文件名、大小、sha256、来源、许可、访问日期；生成 `manifest`。",
            "2. **格式/模式审计**：CSV 表头、XLSX sheet、TIFF 尺寸/波段/nodata、SHP 字段/CRS、NetCDF 变量/维度。",
            "3. **时空基准统一**：TPDC 统一 UTC+8；NASA LST 显式转换；空间保留原 CRS，叠加前再投影到 UTM45N。",
            "4. **缺失/异常处理**：9999.9/QC=8、fill_value、nodata、0 类别分别处理；不补零、不把 nodata 当类别。",
            "5. **质量标记**：为每个变量/图层生成 `missing_rate`、`qc_flag`、`resolution`、`representativeness`、`leakage_risk`。",
            "6. **派生层**：坡度、汇流累积、沟道纵比降、土地覆盖比例、人口暴露；派生层必须能从原始层+脚本重建。",
            "7. **冻结与交接**：`data/processed/<dataset>/` + `data_cards/` + `manifest`；建模手只读冻结层，不再改原始数据。",
            "",
            "## 4. 先内后外：外部补充的准入条件",
            "",
            "| 已有数据的缺口 | 外部补充 | 准入条件 |",
            "|---|---|---|",
            "| 站点单点、距口岸 65 km | Open-Meteo/NASA POWER 再分析 | 只能做空间代表性对照；必须标“再分析≠实测” |",
            "| 无事件发生时间（TPDC-06） | 文献/新闻/灾情目录 | 每条记录要有来源、日期、位置；不能把解译时间当发生时间 |",
            "| DEM 30 m、获取时点不明 | 高分辨率 DEM/灾前灾后影像 | 先确认时点；事件后影像不得用于灾前特征 |",
            "| 冰厚估算、速度气候态 | 冰川编目/冰厚产品 | 只作为情景参数；报告区间与来源 |",
            "| 县级人口、无居民点 | OSM/WorldPop/建筑数据 | 只做暴露分级；不输出个位人数 |",
            "",
            "> 结论：**先把已有 8 组数据做成“可追溯基线”，再补外部数据**。外部数据的价值是补“关键缺口”，不是增加数据量。",
            "",
            "## 5. 与爬虫数据质量的关系",
            "",
            "- 爬虫侧已做到：15 个来源、0 FAIL、5 WARN、1 BLOCKED；TPDC 7/8 数据文件已下载；8 个 TPDC 数据集有 RIS 引用。",
            "- 但“爬到了”不等于“已治理”：本报告第 1–3 节才是已有数据的治理清单；外部数据也必须走同一套质量标记。",
            "- 当前仍缺：TPDC-03 268.9 MB 未解压；TPDC-04 需 `xarray/netCDF4` 读取；高分辨率 DEM/灾前影像未补；历史灾点事件时间不存在于附件。",
            "",
        ]
    )

    report_dir = store.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / "existing_data_audit.md"
    csv_path = report_dir / "existing_data_audit.csv"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["dataset", "format", "scale", "time", "space", "quality", "action"])
        writer.writeheader()
        writer.writerows(rows)
    return md_path, csv_path, rows
