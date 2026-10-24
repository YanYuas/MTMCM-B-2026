from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path


def _basename(name: str) -> str:
    return os.path.basename(name.replace("\\", "/"))


def expand_zip_names(source: bytes | Path | str, *, max_depth: int = 3) -> tuple[set[str], list[str]]:
    """展开 ZIP（含嵌套 ZIP）里的文件名，返回 (basename 集合, 嵌套 ZIP 名列表)。

    只用于“下载 ZIP 与本地附件是否等价”的核对；不写盘、不执行任何内容。
    """
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        data = Path(source).read_bytes()
    names: set[str] = set()
    nested: list[str] = []

    def walk(payload: bytes, depth: int) -> None:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                base = _basename(info.filename)
                if info.filename.lower().endswith(".zip") and depth < max_depth:
                    nested.append(base)
                    try:
                        walk(archive.read(info), depth + 1)
                    except (zipfile.BadZipFile, OSError):
                        names.add(base)
                else:
                    names.add(base)

    walk(data, 0)
    return names, nested
