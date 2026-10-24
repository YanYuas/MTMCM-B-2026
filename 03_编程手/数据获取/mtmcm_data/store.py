from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import APP_ROOT, DATA_DIR
from .http import Response


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "source"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024, max_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    remaining = max_bytes
    with path.open("rb") as fh:
        while True:
            size = chunk_size if remaining is None else min(chunk_size, remaining)
            if size <= 0:
                break
            block = fh.read(size)
            if not block:
                break
            h.update(block)
            if remaining is not None:
                remaining -= len(block)
    return h.hexdigest()


class Store:
    """统一管理 raw / meta / tables / reports 的落盘。"""

    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.meta_dir = self.data_dir / "meta"
        self.table_dir = self.data_dir / "tables"
        self.report_dir = self.data_dir / "reports"
        self.run_dir = self.data_dir / "runs"
        self.error_dir = self.meta_dir / "errors"
        for folder in (self.raw_dir, self.meta_dir, self.table_dir, self.report_dir, self.run_dir, self.error_dir):
            folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(APP_ROOT.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def raw_path(self, source_id: str, response: Response) -> Path:
        ext = guess_extension(response.content_type, response.final_url or response.url)
        stamp = _utc_stamp()
        digest = (response.sha256 or "")[:8]
        folder = self.raw_dir / _safe_id(source_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{stamp}_{digest}{ext}"

    # ------------------------------------------------------------------ write
    def save_raw(self, source_id: str, response: Response) -> Path:
        path = self.raw_path(source_id, response)
        self._atomic_write_bytes(path, response.body)
        return path

    def save_json(self, relative_path: str | Path, obj: Any) -> Path:
        path = self.data_dir / relative_path if not Path(relative_path).is_absolute() else Path(relative_path)
        payload = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self._atomic_write_bytes(path, payload)
        return path

    def save_meta(self, source_id: str, obj: dict[str, Any], subdir: str = "") -> Path:
        folder = self.meta_dir / subdir if subdir else self.meta_dir
        folder.mkdir(parents=True, exist_ok=True)
        return self.save_json(folder.relative_to(self.data_dir) / f"{_safe_id(source_id)}.json", obj)

    def save_error(self, source_id: str, obj: dict[str, Any]) -> Path:
        self.error_dir.mkdir(parents=True, exist_ok=True)
        return self.save_json(self.error_dir.relative_to(self.data_dir) / f"{_safe_id(source_id)}.json", obj)

    def save_table(self, source_id: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> Path:
        path = self.table_dir / f"{_safe_id(source_id)}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            self._atomic_write_bytes(path, b"")
            return path
        names = fieldnames or list(rows[0].keys())
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=names, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(path)
        return path

    def save_run(self, run_id: str, summary: dict[str, Any]) -> Path:
        return self.save_json(self.run_dir.relative_to(self.data_dir) / f"{run_id}.json", summary)

    # ------------------------------------------------------------------- read
    def read_json(self, path: str | Path) -> Any:
        p = Path(path)
        if not p.is_absolute():
            p = self.data_dir / p
        return json.loads(p.read_text(encoding="utf-8"))

    def list_meta(self, subdir: str = "") -> list[Path]:
        folder = self.meta_dir / subdir if subdir else self.meta_dir
        return sorted(folder.glob("*.json")) if folder.exists() else []

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)


def guess_extension(content_type: str, url: str = "") -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "application/json": ".json",
        "application/ld+json": ".json",
        "text/csv": ".csv",
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "application/octet-stream": "",
    }
    if ctype in mapping:
        return mapping[ctype]
    guessed = mimetypes.guess_extension(ctype, strict=False)
    if guessed:
        return guessed
    suffix = Path(url.split("?", 1)[0]).suffix
    return suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix or "") else ".bin"


def count_rows(rows: Iterable[dict[str, Any]]) -> int:
    return sum(1 for _ in rows)
