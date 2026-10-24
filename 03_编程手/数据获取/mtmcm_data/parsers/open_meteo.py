from __future__ import annotations

from typing import Any

from ..config import Source


def parse(payload: dict[str, Any], source: Source) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    variables = [key for key in hourly.keys() if key != "time"]
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(times):
        row: dict[str, Any] = {"time": timestamp}
        for variable in variables:
            values = hourly.get(variable) or []
            row[variable] = values[index] if index < len(values) else None
        rows.append(row)

    units = {
        key: ("未标注" if value == "undefined" else value)
        for key, value in (payload.get("hourly_units") or {}).items()
    }
    meta = {
        "source_id": source.id,
        "source_name": source.name,
        "kind": source.kind,
        "questions": list(source.questions),
        "notes": source.notes,
        "url": source.url,
        "params": source.params,
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "elevation_m": payload.get("elevation"),
        "timezone": payload.get("timezone"),
        "timezone_abbreviation": payload.get("timezone_abbreviation"),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
        "generationtime_ms": payload.get("generationtime_ms"),
        "variables": variables,
        "units": units,
        "row_count": len(rows),
        "time_start": times[0] if times else None,
        "time_end": times[-1] if times else None,
        "parser": "open_meteo",
        "caveat": "再分析/预报产品，不是站点实测；网格点海拔与站点海拔可能不同。",
    }
    return meta, rows
