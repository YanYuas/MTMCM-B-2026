from __future__ import annotations

from typing import Any

from ..config import Source


def _iso_hour(stamp: str) -> str:
    # NASA POWER 小时键形如 2026082010（LST）。
    if len(stamp) == 10 and stamp.isdigit():
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[8:10]}:00:00"
    return stamp


def parse(payload: dict[str, Any], source: Source) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    properties = payload.get("properties") or {}
    parameter = properties.get("parameter") or {}
    units = {name: (info or {}).get("units", "") for name, info in (payload.get("parameters") or {}).items()}
    longnames = {name: (info or {}).get("longname", "") for name, info in (payload.get("parameters") or {}).items()}
    fill_value = (payload.get("header") or {}).get("fill_value")

    stamps: set[str] = set()
    for values in parameter.values():
        if isinstance(values, dict):
            stamps.update(values.keys())
    rows: list[dict[str, Any]] = []
    for stamp in sorted(stamps):
        row: dict[str, Any] = {"time": _iso_hour(stamp), "time_key": stamp}
        for name in sorted(parameter.keys()):
            value = (parameter.get(name) or {}).get(stamp)
            if fill_value is not None and value == fill_value:
                value = None
            row[name] = value
        rows.append(row)

    geometry = payload.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    meta = {
        "source_id": source.id,
        "source_name": source.name,
        "kind": source.kind,
        "questions": list(source.questions),
        "notes": source.notes,
        "url": source.url,
        "params": source.params,
        "latitude": coordinates[1] if len(coordinates) > 1 else source.params.get("latitude"),
        "longitude": coordinates[0] if coordinates else source.params.get("longitude"),
        "elevation_m": coordinates[2] if len(coordinates) > 2 else None,
        "time_standard": (payload.get("header") or {}).get("time_standard"),
        "sources": (payload.get("header") or {}).get("sources"),
        "fill_value": fill_value,
        "units": units,
        "longnames": longnames,
        "variables": sorted(parameter.keys()),
        "row_count": len(rows),
        "time_start": rows[0]["time"] if rows else None,
        "time_end": rows[-1]["time"] if rows else None,
        "parser": "nasa_power",
        "caveat": "NASA POWER 为再分析/同化产品，网格海拔与站点海拔不同；时间标准见 time_standard。",
    }
    return meta, rows
