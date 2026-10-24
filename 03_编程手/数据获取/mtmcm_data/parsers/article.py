from __future__ import annotations

import hashlib
import re
import urllib.parse
from typing import Any

from lxml import html as lxml_html

from ..config import Source


_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff]")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")


def clean_text(text: str) -> str:
    text = _PRIVATE_USE.sub("", text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _first_text(doc: Any, xpath: str) -> str:
    if not xpath:
        return ""
    try:
        values = doc.xpath(xpath)
    except Exception:
        return ""
    for value in values:
        if hasattr(value, "itertext"):
            text = "".join(value.itertext())
        else:
            text = str(value)
        text = clean_text(text)
        if text:
            return text
    return ""


def _absolute(base: str, href: str) -> str:
    if not href:
        return ""
    return urllib.parse.urljoin(base, href.strip())


def _largest_text_block(doc: Any) -> Any | None:
    """选择包含最多正文 <p> 文本的 div，作为没有选择器时的兜底。"""
    best = None
    best_len = 0
    for node in doc.xpath("//div"):
        text_len = sum(len(clean_text("".join(p.itertext()))) for p in node.xpath(".//p"))
        if text_len > best_len:
            best = node
            best_len = text_len
    return best if best_len >= 80 else None


def parse(html_text: str, source: Source) -> dict[str, Any]:
    doc = lxml_html.document_fromstring(html_text or "<html></html>")
    for bad in doc.xpath("//script|//style|//noscript|//iframe|//svg"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)

    selectors = source.selectors or {}
    title = _first_text(doc, selectors.get("title", ""))
    if not title:
        title = _first_text(doc, "//meta[@property='og:title']/@content") or _first_text(doc, "//title/text()")
    published = _first_text(doc, selectors.get("published", ""))
    if not published:
        for xp in (
            "//meta[@name='PubDate']/@content",
            "//meta[@name='publishdate']/@content",
            "//meta[@property='article:published_time']/@content",
            "//time/@datetime",
        ):
            published = _first_text(doc, xp)
            if published:
                break

    content_node = None
    content_xpath = selectors.get("content", "")
    if content_xpath:
        nodes = doc.xpath(content_xpath)
        if nodes:
            content_node = nodes[0]
    if content_node is None:
        content_node = _largest_text_block(doc)

    paragraphs: list[str] = []
    if content_node is not None:
        for p in content_node.xpath(".//p"):
            text = clean_text("".join(p.itertext()))
            if text:
                paragraphs.append(text)
        if not paragraphs:
            text = clean_text("".join(content_node.itertext()))
            paragraphs = [line for line in text.splitlines() if line]

    text = "\n".join(paragraphs)
    link_root = content_node if content_node is not None else doc
    links = []
    for href in link_root.xpath(".//a[@href]/@href")[:200]:
        absolute = _absolute(source.url, href)
        if absolute.startswith(("http://", "https://")) and absolute not in links:
            links.append(absolute)
    images = []
    for src in link_root.xpath(".//img[@src]/@src")[:100]:
        absolute = _absolute(source.url, src)
        if absolute.startswith(("http://", "https://")) and absolute not in images:
            images.append(absolute)

    return {
        "source_id": source.id,
        "source_name": source.name,
        "kind": source.kind,
        "questions": list(source.questions),
        "notes": source.notes,
        "url": source.url,
        "title": title,
        "published_at": published,
        "text": text,
        "paragraph_count": len(paragraphs),
        "char_count": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "links": links,
        "images": images,
        "extraction": {
            "content_selector": content_xpath if content_xpath and content_node is not None else "fallback:largest_div",
            "title_selector": selectors.get("title", ""),
        },
    }
