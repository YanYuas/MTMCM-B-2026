from __future__ import annotations

import struct
from typing import Any


def _decode_with(raw: bytes, encoding: str, *, strict: bool = True) -> str:
    return raw.decode(encoding, errors="strict" if strict else "replace").strip()


def _choose_encoding(field_names: list[bytes]) -> str:
    """DBF 字段名/属性可能是 UTF-8（08）或 GBK（06）。

    不能逐值先试 UTF-8：GBK 的“小”(D0 A1) 恰好是合法 UTF-8，会被误解成西里尔字母。
    先看字段名：UTF-8 解码失败就退回 GB18030；两者都能解码时，选 CJK 字符更多的。
    """
    candidates: list[tuple[int, str]] = []
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            decoded = [_decode_with(name, encoding) for name in field_names]
        except UnicodeDecodeError:
            continue
        cjk = sum(1 for text in decoded for ch in text if "\u4e00" <= ch <= "\u9fff")
        candidates.append((cjk, encoding))
    if not candidates:
        return "latin-1"
    candidates.sort(key=lambda item: (-item[0], item[1] != "utf-8"))
    return candidates[0][1]


def read_dbf(data: bytes) -> tuple[list[dict[str, str]], list[tuple[str, str, int]], str]:
    _, _, _, _, nrec, hlen, rlen = struct.unpack("<BBBBIHH", data[:12])
    raw_names: list[bytes] = []
    fields: list[tuple[str, str, int]] = []
    pos = 32
    while data[pos] != 0x0D:
        fd = data[pos : pos + 32]
        raw_names.append(fd[:11].split(b"\x00")[0])
        fields.append(("", chr(fd[11]), fd[16]))
        pos += 32
    encoding = _choose_encoding(raw_names)
    fields = [
        (_decode_with(raw, encoding), ftype, length)
        for raw, (_, ftype, length) in zip(raw_names, fields)
    ]
    records: list[dict[str, str]] = []
    for index in range(nrec):
        rec = data[hlen + index * rlen : hlen + (index + 1) * rlen]
        if len(rec) < rlen:
            break
        values: dict[str, str] = {}
        off = 1
        for name, _, length in fields:
            values[name] = _decode_with(rec[off : off + length], encoding, strict=False)
            off += length
        records.append(values)
    return records, fields, encoding
