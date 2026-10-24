from __future__ import annotations

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


def parse(payload: dict[str, Any], source: Source) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    products = payload.get("value") or []
    rows: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        content_date = product.get("ContentDate") or {}
        bbox = _extract_bbox(product.get("GeoFootprint"))
        size_bytes = product.get("ContentLength")
        rows.append(
            {
                "id": product.get("Id"),
                "name": product.get("Name"),
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
                "checksum": (product.get("Checksum") or [{}])[0].get("Value") if product.get("Checksum") else "",
            }
        )

    meta = {
        "source_id": source.id,
        "source_name": source.name,
        "kind": source.kind,
        "questions": list(source.questions),
        "notes": source.notes,
        "url": source.url,
        "params": source.params,
        "row_count": len(rows),
        "time_start": min((r["start"] for r in rows if r.get("start")), default=None),
        "time_end": max((r["end"] for r in rows if r.get("end")), default=None),
        "parser": "copernicus",
        "download_note": "本工具只取公开元数据；产品下载需要 Copernicus Data Space 账号/OAuth，不代填凭据。",
    }
    return meta, rows
