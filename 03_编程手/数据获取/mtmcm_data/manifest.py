from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


@dataclass
class ManifestEntry:
    run_id: str
    source_id: str
    source_name: str
    kind: str
    url: str
    method: str = "GET"
    status: int | None = None
    fetched_at: str = ""
    sha256: str = ""
    bytes: int = 0
    content_type: str = ""
    raw_path: str = ""
    parser: str = ""
    from_cache: bool = False
    elapsed_ms: int = 0
    questions: list[str] = field(default_factory=list)
    notes: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Manifest:
    """JSONL manifest：一行一个请求，便于审计和后续转 CSV。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: ManifestEntry) -> None:
        line = json.dumps(entry.as_dict(), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def latest_by_source(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for entry in self.read_all():
            sid = entry.get("source_id", "")
            if not sid:
                continue
            prev = latest.get(sid)
            if prev is None or (entry.get("fetched_at", "") >= prev.get("fetched_at", "")):
                latest[sid] = entry
        return latest

    def entries_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return [e for e in self.read_all() if e.get("run_id") == run_id]


def summarise(entries: Iterable[ManifestEntry]) -> dict[str, int]:
    counts = {"ok": 0, "failed": 0, "cached": 0, "total": 0}
    for entry in entries:
        counts["total"] += 1
        if entry.error:
            counts["failed"] += 1
        elif entry.from_cache:
            counts["cached"] += 1
        else:
            counts["ok"] += 1
    return counts
