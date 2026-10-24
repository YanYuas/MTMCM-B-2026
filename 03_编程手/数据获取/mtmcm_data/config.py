from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parents[1]
CONFIG_PATH = APP_ROOT / "config" / "sources.json"
DATA_DIR = APP_ROOT / "data"


@dataclass(frozen=True)
class Source:
    """一个数据来源的不可变配置。"""

    id: str
    name: str
    kind: str
    url: str = ""
    parser: str = ""
    metadata_id: str = ""
    method: str = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    selectors: dict[str, str] = field(default_factory=dict)
    questions: tuple[str, ...] = ()
    notes: str = ""
    local_mirror: str = ""
    manual_snapshot: str = ""
    allow_blocked: bool = False
    enabled: bool = True
    respect_robots: bool = True
    min_interval_sec: float = 1.0
    cache_ttl_sec: int = 86400
    timeout_sec: float = 30.0
    retries: int = 3
    max_bytes: int = 52_428_800
    study_area: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], defaults: dict[str, Any]) -> "Source":
        merged: dict[str, Any] = {**defaults, **raw}
        questions = merged.get("questions") or ()
        return cls(
            id=str(merged["id"]),
            name=str(merged.get("name", merged["id"])),
            kind=str(merged["kind"]),
            url=str(merged.get("url", "")),
            parser=str(merged.get("parser", "")),
            metadata_id=str(merged.get("metadata_id", "")),
            method=str(merged.get("method", "GET")).upper(),
            params=dict(merged.get("params") or {}),
            headers={str(k): str(v) for k, v in (merged.get("headers") or {}).items()},
            selectors={str(k): str(v) for k, v in (merged.get("selectors") or {}).items()},
            questions=tuple(str(q) for q in questions),
            notes=str(merged.get("notes", "")),
            local_mirror=str(merged.get("local_mirror", "")),
            manual_snapshot=str(merged.get("manual_snapshot", "")),
            allow_blocked=bool(merged.get("allow_blocked", False)),
            enabled=bool(merged.get("enabled", True)),
            respect_robots=bool(merged.get("respect_robots", True)),
            min_interval_sec=float(merged.get("min_interval_sec", 1.0)),
            cache_ttl_sec=int(merged.get("cache_ttl_sec", 86400)),
            timeout_sec=float(merged.get("timeout_sec", 30.0)),
            retries=int(merged.get("retries", 3)),
            max_bytes=int(merged.get("max_bytes", 52_428_800)),
            study_area={str(k): float(v) for k, v in (merged.get("study_area") or {}).items()},
        )

    @property
    def local_mirror_path(self) -> Path | None:
        if not self.local_mirror:
            return None
        p = Path(self.local_mirror)
        return p if p.is_absolute() else WORKSPACE_ROOT / p

    @property
    def manual_snapshot_path(self) -> Path | None:
        if not self.manual_snapshot:
            return None
        p = Path(self.manual_snapshot)
        return p if p.is_absolute() else APP_ROOT / p


@dataclass(frozen=True)
class Config:
    user_agent: str
    defaults: dict[str, Any]
    sources: tuple[Source, ...]

    def get(self, source_id: str) -> Source:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(f"未知来源: {source_id}")

    def select(self, ids: list[str] | None = None, include_disabled: bool = False) -> list[Source]:
        chosen = list(self.sources)
        if ids:
            wanted = set(ids)
            chosen = [s for s in chosen if s.id in wanted]
            missing = wanted - {s.id for s in chosen}
            if missing:
                raise KeyError(f"未知来源: {', '.join(sorted(missing))}")
        if not include_disabled:
            chosen = [s for s in chosen if s.enabled]
        return chosen


def load_config(path: Path | str = CONFIG_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到配置文件: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    defaults = dict(raw.get("defaults") or {})
    sources = tuple(Source.from_dict(item, defaults) for item in raw.get("sources", []))
    if not sources:
        raise ValueError("配置里没有任何 sources")
    ids = [s.id for s in sources]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"source id 重复: {', '.join(dup)}")
    return Config(
        user_agent=str(raw.get("user_agent", "MTMCM-DataCrawler/1.0")),
        defaults=defaults,
        sources=sources,
    )
