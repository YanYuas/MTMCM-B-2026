from __future__ import annotations

from collections import Counter
from typing import Any

from ..config import Source


def _extract_bbox(geometry: Any) -> dict[str, float] | None:
    """从 GeoJSON footprint 提取 bbox；兼容 Polygon / MultiPolygon。"""
    if not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return None
    points: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                points.append((float(node[0]), float(node[1])))
            else:
                for child in node:
                    walk(child)

    walk(coordinates)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {"west": min(xs), "south": min(ys), "east": max(xs), "north": max(ys)}


def _area(box: dict[str, float] | None) -> float:
    if not box:
        return 0.0
    return max(0.0, box["east"] - box["west"]) * max(0.0, box["north"] - box["south"])


def _intersection(a: dict[str, float] | None, b: dict[str, float] | None) -> dict[str, float] | None:
    if not a or not b:
        return None
    box = {
        "west": max(a["west"], b["west"]),
        "south": max(a["south"], b["south"]),
        "east": min(a["east"], b["east"]),
        "north": min(a["north"], b["north"]),
    }
    return box if box["east"] > box["west"] and box["north"] > box["south"] else None


def _product_type(name: str) -> str:
    for token in (name or "").split("_"):
        if token in {"MSIL1C", "MSIL2A", "GRDH", "GRDM", "SLC", "RAW"}:
            return token
    return ""


def parse(payload: dict[str, Any], source: Source) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    products = payload.get("value") or []
    rows: list[dict[str, Any]] = []
    study = {k: float(v) for k, v in (source.study_area or {}).items() if k in {"west", "south", "east", "north"}}
    for product in products:
        if not isinstance(product, dict):
            continue
        content_date = product.get("ContentDate") or {}
        bbox = _extract_bbox(product.get("GeoFootprint"))
        core = _intersection(bbox, study) if study else None
        size_bytes = product.get("ContentLength")
        name = product.get("Name") or ""
        rows.append(
            {
                "id": product.get("Id"),
                "name": name,
                "product_type": _product_type(name),
                "start": content_date.get("Start"),
                "end": content_date.get("End"),
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / 1e6, 2) if isinstance(size_bytes, (int, float)) else None,
                "online": product.get("Online"),
                "s3_path": product.get("S3Path"),
                "content_type": product.get("ContentType"),
                "bbox": (
                    f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}" if bbox else ""
                ),
                "bbox_west": bbox["west"] if bbox else None,
                "bbox_south": bbox["south"] if bbox else None,
                "bbox_east": bbox["east"] if bbox else None,
                "bbox_north": bbox["north"] if bbox else None,
                "core_overlap": core is not None,
                "overlap_fraction": round(_area(core) / _area(bbox), 4) if bbox and _area(bbox) > 0 else None,
                "checksum": (product.get("Checksum") or [{}])[0].get("Value") if product.get("Checksum") else "",
            }
        )

    type_counts = Counter(row["product_type"] for row in rows if row["product_type"])
    meta = {
        "source_id": source.id,
        "source_name": source.name,
        "kind": source.kind,
        "questions": list(source.questions),
        "notes": source.notes,
        "url": source.url,
        "params": source.params,
        "study_area": study or None,
        "row_count": len(rows),
        "core_overlap_count": sum(1 for row in rows if row["core_overlap"]),
        "product_types": dict(type_counts),
        "time_start": min((r["start"] for r in rows if r.get("start")), default=None),
        "time_end": max((r["end"] for r in rows if r.get("end")), default=None),
        "parser": "copernicus",
        "download_note": "本工具只取公开元数据；产品下载需要 Copernicus Data Space 账号/OAuth，不代填凭据。",
    }
    return meta, rows
