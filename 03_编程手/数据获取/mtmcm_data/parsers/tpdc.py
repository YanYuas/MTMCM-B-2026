from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..config import Source, WORKSPACE_ROOT


def _ctx(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return payload.get("context") or {}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _year(metadata: dict[str, Any]) -> str:
    for key in ("tsPublish", "tsCreated", "startTime"):
        value = _clean(metadata.get(key))
        if len(value) >= 4 and value[:4].isdigit():
            return value[:4]
    return "n.d."


def _title_time_hint(title: str) -> str:
    """标题里常带时间范围；只作为提示，不冒充元数据 start/end。"""
    if not title:
        return ""
    m = re.search(r"[（(](\d{4})\s*[—–-]\s*(\d{4})\s*年?[）)]", title)
    if m:
        return f"{m.group(1)}–{m.group(2)}"
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _author_names(authors: list[dict[str, Any]], *, english: bool = False) -> list[str]:
    names: list[str] = []
    for author in authors:
        name = _clean(author.get("nameEn" if english else "name"))
        if name:
            names.append(name)
    return names


def _short_authors(names: list[str], limit: int = 3) -> str:
    if not names:
        return ""
    if len(names) <= limit:
        return "，".join(names)
    return "，".join(names[:limit]) + "，等"


def _short_authors_en(names: list[str], limit: int = 3) -> str:
    if not names:
        return ""
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + ", et al."


def build_citation_cn(metadata: dict[str, Any], authors: list[dict[str, Any]]) -> str:
    names = _author_names(authors)
    who = _short_authors(names) or _clean(metadata.get("realName")) or "国家青藏高原科学数据中心"
    title = _clean(metadata.get("title")) or "未命名数据集"
    year = _year(metadata)
    doi = _clean(metadata.get("doi"))
    cstr = _clean(metadata.get("cstr"))
    if doi:
        tail = f"DOI: {doi}."
    elif cstr:
        tail = f"CSTR: {cstr}."
    else:
        tail = ""
    return f"{who}. {title}[DS]. 国家青藏高原科学数据中心, {year}. {tail}".strip()


def build_citation_en(metadata: dict[str, Any], google: dict[str, Any] | None, authors: list[dict[str, Any]]) -> str:
    creator = (google or {}).get("creator") or []
    names = [_clean(c.get("name")) for c in creator if _clean(c.get("name"))]
    who = _short_authors_en(names) or _short_authors_en(_author_names(authors, english=True))
    title = _clean(metadata.get("titleEn")) or _clean(metadata.get("title")) or "Untitled dataset"
    year = _year(metadata)
    doi = _clean(metadata.get("doi"))
    tail = f"https://doi.org/{doi}" if doi else (_clean(metadata.get("url")) or "")
    return f"{who}. {title} [Dataset]. National Tibetan Plateau Data Center, {year}. {tail}".strip()


def _local_mirror_info(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        display_path = path.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    except ValueError:
        display_path = path.as_posix()
    info: dict[str, Any] = {
        "path": display_path,
        "exists": path.exists(),
    }
    if path.exists():
        info["size_bytes"] = path.stat().st_size
        # 268 MB 的 RAR 只记录大小，避免每次抓元数据都重算；需要时用 verify 单独核。
        if path.stat().st_size <= 64 * 1024 * 1024:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(block)
            info["sha256"] = h.hexdigest()
        else:
            info["sha256"] = ""
            info["sha256_note"] = "文件超过 64 MiB，未在元数据抓取阶段计算；可用 verify 单独核。"
    return info


def normalize(
    detail: dict[str, Any] | None,
    google: dict[str, Any] | None,
    source: Source,
    *,
    local_mirror_path: Path | None = None,
) -> dict[str, Any]:
    context = _ctx(detail)
    metadata = context.get("metadataVO") or {}
    authors = context.get("authorVOList") or []
    google_ctx = _ctx(google)

    west = metadata.get("west")
    east = metadata.get("east")
    south = metadata.get("south")
    north = metadata.get("north")
    bbox = None
    is_point = False
    if all(v is not None for v in (west, east, south, north)):
        try:
            bbox = {
                "west": float(west),
                "east": float(east),
                "south": float(south),
                "north": float(north),
            }
            is_point = abs(float(east) - float(west)) < 1e-9 and abs(float(north) - float(south)) < 1e-9
        except (TypeError, ValueError):
            bbox = None

    keywords: list[str] = []
    for key in ("keywords",):
        values = google_ctx.get(key)
        if isinstance(values, list):
            keywords.extend(_clean(v) for v in values if _clean(v))
    for key in ("themeList", "keywordStandVOList", "placeKeywordVOList", "temporalKeywordVOList"):
        for item in context.get(key) or []:
            if not isinstance(item, dict):
                continue
            value = _clean(item.get("name") or item.get("keyword") or item.get("enName") or item.get("keywordEn"))
            if value:
                keywords.append(value)
    # 去重保序
    keywords = list(dict.fromkeys(keywords))

    related = []
    for item in context.get("relatedDataList") or []:
        if isinstance(item, dict):
            related.append({"id": _clean(item.get("id")), "title": _clean(item.get("title"))})

    literature = []
    for item in context.get("literatureVOList") or []:
        if isinstance(item, dict):
            literature.append(
                {
                    "title": _clean(item.get("title")),
                    "reference": _clean(item.get("reference")),
                    "year": _clean(item.get("year")),
                    "doi": _clean(item.get("doi")),
                }
            )

    mirror = _local_mirror_info(local_mirror_path)
    result = {
        "source_id": source.id,
        "source_name": source.name,
        "kind": source.kind,
        "questions": list(source.questions),
        "notes": source.notes,
        "metadata_id": source.metadata_id,
        "landing_url": source.url,
        "title": _clean(metadata.get("title")),
        "title_en": _clean(metadata.get("titleEn")),
        "doi": _clean(metadata.get("doi")),
        "doi_url": f"https://doi.org/{_clean(metadata.get('doi'))}" if _clean(metadata.get("doi")) else "",
        "cstr": _clean(metadata.get("cstr")),
        "authors": [
            {
                "name": _clean(a.get("name")),
                "name_en": _clean(a.get("nameEn")),
                "unit": _clean(a.get("unit")),
                "unit_en": _clean(a.get("unitEn")),
                "email": _clean(a.get("email")),
                "orcid": _clean(a.get("orcid")),
            }
            for a in authors
            if isinstance(a, dict)
        ],
        "publisher": _clean((google_ctx.get("publisher") or {}).get("name")) or "国家青藏高原科学数据中心",
        "date_published": _clean(google_ctx.get("datePublished")),
        "year": _year(metadata),
        "description": _clean(metadata.get("description")),
        "instructions": _clean(metadata.get("instructions")),
        "use_terms": _clean(metadata.get("useTerms")),
        "license_code": _clean(metadata.get("license")),
        "share_type": _clean(metadata.get("shareType")),
        "share_policy": _clean(metadata.get("sharePolicy")),
        "status": metadata.get("status"),
        "time_coverage": {
            "start": _clean(metadata.get("startTime")) or None,
            "end": _clean(metadata.get("endTime")) or None,
            "resolution": _clean(metadata.get("temporalResolution")) or None,
            "title_hint": _title_time_hint(_clean(metadata.get("title"))),
            "note": "元数据未给出时间范围" if not metadata.get("startTime") and not metadata.get("endTime") else "",
        },
        "spatial_coverage": {
            "bbox": bbox,
            "is_point": is_point,
            "resolution": _clean(metadata.get("spatialResolution")) or None,
            "crs": _clean(metadata.get("crs")) or None,
            "projection": _clean(metadata.get("projection")) or None,
        },
        "keywords": keywords,
        "related_data": related,
        "literature": literature,
        "citation_cn": build_citation_cn(metadata, authors),
        "citation_en": build_citation_en(metadata, google_ctx, authors),
        "local_mirror": mirror,
        "download_status": "local_mirror_present" if mirror.get("exists") else "metadata_only",
        "raw_files": [
            "raw 目录下保留 detail JSON 与 GoogleJson 原始响应",
        ],
        "recorded_at": _clean(metadata.get("tsUpdated")) or None,
        "description_source": "TPDC metadataView/detail + metadataView/getGoogleJson",
    }
    return result
