from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import json
import logging
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("mtmcm_data.http")


class FetchError(RuntimeError):
    """抓取失败；带上可写入 manifest 的上下文。"""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        status: int | None = None,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        fetched_at: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.fetched_at = fetched_at or utc_now()


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    fetched_at: str
    from_cache: bool
    elapsed_ms: int
    sha256: str

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    def text(self, encoding: str | None = None) -> str:
        return decode_body(self.body, self.headers, encoding)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _charset_from_headers(headers: dict[str, str]) -> str | None:
    ctype = headers.get("content-type", "")
    m = re.search(r"charset=([\w\-]+)", ctype, re.I)
    return m.group(1) if m else None


def _charset_from_html(body: bytes) -> str | None:
    head = body[:8192].decode("ascii", errors="ignore")
    m = re.search(r"<meta[^>]+charset=[\"']?([\w\-]+)", head, re.I)
    if m:
        return m.group(1)
    m = re.search(r"content=[\"'][^\"']*charset=([\w\-]+)", head, re.I)
    return m.group(1) if m else None


def _normalise_encoding(enc: str | None) -> str:
    if not enc:
        return "utf-8"
    enc = enc.lower()
    if enc in {"gb2312", "gbk", "gb_2312-80"}:
        return "gb18030"
    return enc


def decode_body(body: bytes, headers: dict[str, str] | None = None, encoding: str | None = None) -> str:
    headers = headers or {}
    enc = encoding or _charset_from_headers(headers) or _charset_from_html(body)
    enc = _normalise_encoding(enc)
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def build_url(url: str, params: dict[str, Any] | None = None) -> str:
    if not params:
        return url
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, str(v)) for v in value)
        else:
            query.append((key, str(value)))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query, doseq=True), parts.fragment)
    )


class HttpClient:
    """带缓存、限速、重试、robots 检查的 HTTP 客户端。"""

    def __init__(
        self,
        *,
        cache_dir: Path,
        user_agent: str,
        defaults: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
        refresh: bool = False,
        offline: bool = False,
        insecure: bool = False,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.defaults = defaults or {}
        self.logger = logger or LOGGER
        self.refresh = refresh
        self.offline = offline
        self.cookies = http.cookiejar.CookieJar()
        handlers: list[Any] = [urllib.request.HTTPCookieProcessor(self.cookies)]
        if insecure:
            context = ssl._create_unverified_context()
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self.opener = urllib.request.build_opener(*handlers)
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | bool] = {}
        self._last_request: dict[str, float] = {}

    # ------------------------------------------------------------------ cache
    def _cache_paths(self, source_id: str, key: str) -> tuple[Path, Path]:
        folder = self.cache_dir / source_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{key}.json", folder / f"{key}.body"

    def _load_cache(self, source_id: str, key: str, ttl: int, offline: bool) -> Response | None:
        if ttl == 0:
            return None
        meta_path, body_path = self._cache_paths(source_id, key)
        if not meta_path.exists() or not body_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(meta["fetched_at"])
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - fetched).total_seconds()
        except Exception:
            return None
        if not offline and ttl > 0 and age > ttl:
            return None
        body = body_path.read_bytes()
        return Response(
            url=meta.get("url", ""),
            final_url=meta.get("final_url", meta.get("url", "")),
            status=int(meta.get("status", 200)),
            headers=dict(meta.get("headers") or {}),
            body=body,
            fetched_at=meta.get("fetched_at", ""),
            from_cache=True,
            elapsed_ms=0,
            sha256=meta.get("sha256") or sha256_bytes(body),
        )

    def _save_cache(self, source_id: str, key: str, response: Response) -> None:
        meta_path, body_path = self._cache_paths(source_id, key)
        _atomic_write_bytes(body_path, response.body)
        meta = {
            "url": response.url,
            "final_url": response.final_url,
            "status": response.status,
            "headers": response.headers,
            "fetched_at": response.fetched_at,
            "sha256": response.sha256,
            "bytes": len(response.body),
        }
        _atomic_write_bytes(
            meta_path,
            json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    # ----------------------------------------------------------------- robots
    def _robots_allowed(self, url: str, respect: bool) -> bool:
        if not respect:
            return True
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            return True
        base = f"{parts.scheme}://{parts.netloc}"
        if base in self._robots_cache:
            parser = self._robots_cache[base]
        else:
            parser = self._fetch_robots(base)
            self._robots_cache[base] = parser
        if parser is True:
            return True
        if parser is False:
            return False
        return parser.can_fetch(self.user_agent, url)

    def _fetch_robots(self, base: str) -> urllib.robotparser.RobotFileParser | bool:
        robots_url = base + "/robots.txt"
        try:
            req = urllib.request.Request(robots_url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read(512_000)
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(decode_body(raw, {"content-type": resp.headers.get("content-type", "")}).splitlines())
            return parser
        except urllib.error.HTTPError as exc:
            # 404 = 没有 robots 文件；401/403 保守地视为禁止。
            return False if exc.code in {401, 403} else True
        except Exception:
            # robots 读不到时不阻塞公开元数据抓取，但记录在日志里。
            self.logger.debug("robots.txt 读取失败: %s", robots_url, exc_info=True)
            return True

    # --------------------------------------------------------------- rate limit
    def _respect_rate_limit(self, url: str, interval: float) -> None:
        host = urllib.parse.urlsplit(url).netloc
        last = self._last_request.get(host)
        now = time.monotonic()
        if last is not None:
            wait = interval - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    # ---------------------------------------------------------------- requests
    def fetch(
        self,
        source_id: str,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
        cache_ttl: int | None = None,
        respect_robots: bool | None = None,
        max_bytes: int | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        min_interval_sec: float | None = None,
        refresh: bool | None = None,
        cache: bool = True,
    ) -> Response:
        method = method.upper()
        full_url = build_url(url, params)
        body, content_type = _prepare_body(json_body=json_body, data=data)

        ttl = int(self.defaults.get("cache_ttl_sec", 86400) if cache_ttl is None else cache_ttl)
        max_bytes = int(self.defaults.get("max_bytes", 52_428_800) if max_bytes is None else max_bytes)
        timeout = float(self.defaults.get("timeout_sec", 30.0) if timeout is None else timeout)
        retries = int(self.defaults.get("retries", 3) if retries is None else retries)
        respect = bool(self.defaults.get("respect_robots", True) if respect_robots is None else respect_robots)
        interval = float(
            self.defaults.get("min_interval_sec", 1.0) if min_interval_sec is None else min_interval_sec
        )

        body_hash = sha256_bytes(body)[:16] if body else "nobody"
        key = sha256_bytes(f"{source_id}\n{method}\n{full_url}\n{body_hash}".encode("utf-8"))[:24]

        if cache and not (self.refresh if refresh is None else refresh):
            cached = self._load_cache(source_id, key, ttl, self.offline)
            if cached is not None:
                self.logger.debug("cache hit %s %s", source_id, full_url)
                return cached
        if self.offline:
            raise FetchError("离线模式且缓存未命中", url=full_url)

        if not self._robots_allowed(full_url, respect):
            raise FetchError("robots.txt 禁止抓取", url=full_url, status=0)

        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            # 明确要求 identity，避免 urllib 不自动解压导致乱码。
            "Accept-Encoding": "identity",
        }
        if content_type:
            request_headers["Content-Type"] = content_type
        if headers:
            request_headers.update(headers)

        last_error: FetchError | None = None
        for attempt in range(retries + 1):
            self._respect_rate_limit(full_url, interval)
            started = time.monotonic()
            req = urllib.request.Request(full_url, data=body or None, headers=request_headers, method=method)
            try:
                with self.opener.open(req, timeout=timeout) as resp:
                    raw = resp.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raise FetchError(f"响应超过 max_bytes={max_bytes}", url=full_url, status=resp.status)
                    raw = _maybe_decompress(raw, resp.headers.get("Content-Encoding", ""))
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    response = Response(
                        url=full_url,
                        final_url=resp.geturl(),
                        status=resp.status,
                        headers={k.lower(): v for k, v in resp.headers.items()},
                        body=raw,
                        fetched_at=utc_now(),
                        from_cache=False,
                        elapsed_ms=elapsed_ms,
                        sha256=sha256_bytes(raw),
                    )
                if cache:
                    self._save_cache(source_id, key, response)
                return response
            except urllib.error.HTTPError as exc:
                raw = _safe_read(exc, max_bytes)
                headers_l = {k.lower(): v for k, v in (exc.headers or {}).items()}
                err = FetchError(
                    f"HTTP {exc.code}: {exc.reason}",
                    url=full_url,
                    status=exc.code,
                    headers=headers_l,
                    body=raw,
                )
                last_error = err
                if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                    delay = _retry_delay(attempt, exc.headers.get("Retry-After") if exc.headers else None)
                    self.logger.warning("HTTP %s，%.1fs 后重试 (%s/%s): %s", exc.code, delay, attempt + 1, retries, full_url)
                    time.sleep(delay)
                    continue
                raise err from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                err = FetchError(f"网络错误: {exc}", url=full_url, status=None)
                last_error = err
                if attempt < retries:
                    delay = _retry_delay(attempt, None)
                    self.logger.warning("网络错误，%.1fs 后重试 (%s/%s): %s", delay, attempt + 1, retries, full_url)
                    time.sleep(delay)
                    continue
                raise err from exc
        raise last_error or FetchError("未知抓取失败", url=full_url)


def _prepare_body(*, json_body: Any | None, data: Any | None) -> tuple[bytes, str]:
    if json_body is not None:
        return json.dumps(json_body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
    if data is None:
        return b"", ""
    if isinstance(data, bytes):
        return data, "application/octet-stream"
    if isinstance(data, str):
        return data.encode("utf-8"), "application/x-www-form-urlencoded; charset=utf-8"
    if isinstance(data, dict):
        return urllib.parse.urlencode(data, doseq=True).encode("utf-8"), "application/x-www-form-urlencoded; charset=utf-8"
    raise TypeError(f"不支持的 data 类型: {type(data)!r}")


def _safe_read(exc: urllib.error.HTTPError, max_bytes: int) -> bytes:
    try:
        return exc.read(max_bytes + 1)[:max_bytes]
    except Exception:
        return b""


def _maybe_decompress(raw: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    if encoding == "gzip":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return raw
    return raw


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(20.0, (2**attempt) + random.uniform(0.0, 0.4))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
