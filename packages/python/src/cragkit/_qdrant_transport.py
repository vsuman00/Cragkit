"""Optional HTTPX transport with explicit ownership and bounded streaming."""
from __future__ import annotations

import asyncio
import math
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from .errors import CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability


def safe_transport_error(error: CragkitError) -> CragkitError:
    """Never reuse mutable exception messages or trust unknown subclasses."""
    for error_class in (DeadlineExceeded, IntegrityViolation, InvalidRequest,
                        ProviderUnavailable, UnsupportedCapability):
        if type(error) is error_class:
            return error_class()
    return ProviderUnavailable()


def _endpoint(value: object, allow_loopback_http: object) -> str:
    if type(value) is not str or type(allow_loopback_http) is not bool:
        raise InvalidRequest()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value) or '\\' in value):
            raise InvalidRequest()
        _ = parsed.port
        if parsed.scheme == 'http':
            if not allow_loopback_http:
                raise UnsupportedCapability()
            loopback = parsed.hostname in ('127.0.0.1', '::1')
            if not loopback:
                raise UnsupportedCapability()
        return value.rstrip('/')
    except ValueError:
        raise InvalidRequest() from None


def _path(value: object) -> str:
    if type(value) is not str or not value.startswith('/') or value.startswith('//'):
        raise InvalidRequest()
    parsed = urlsplit(value)
    decoded = unquote(value)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or '\\' in decoded
            or any(part in ('.', '..') for part in decoded.split('/'))
            or any(ord(ch) <= 32 for ch in decoded) or decoded.startswith('//')):
        raise InvalidRequest()
    return value


def deadline_value(value: object) -> float:
    if type(value) not in (float, int):
        raise InvalidRequest()
    assert isinstance(value, (int, float))
    try:
        result = float(value)
        if not math.isfinite(result) or abs(result) > 9007199254740991:
            raise InvalidRequest()
        if result <= asyncio.get_running_loop().time():
            raise DeadlineExceeded()
        return result
    except OverflowError:
        raise InvalidRequest() from None


class HttpxQdrantTransport:
    """Own one lazy client, at most two connections, one operation and no queue.

    ``client`` is an optional borrowed HTTPX-compatible client for explicit injection;
    its owner must provide equivalent TLS/proxy/retry/redirect behavior. Close cancels
    active work and waits at most one second; injected clients are never closed.
    """
    bounded_responses = True
    cancellation_safe = True

    def __init__(self, endpoint: str, *, api_key: str | None = None,
                 allow_loopback_http: bool = False, client: Any = None) -> None:
        self._endpoint = _endpoint(endpoint, allow_loopback_http)
        if api_key is not None and (type(api_key) is not str or not api_key or len(api_key) > 4096 or
                                    any(ord(ch) < 33 or ord(ch) > 126 for ch in api_key)):
            raise InvalidRequest()
        self._api_key = api_key
        self._client = client
        self._owned = client is None
        self._closed = False
        self._active: asyncio.Task[Any] | None = None

    def __repr__(self) -> str:
        return 'HttpxQdrantTransport()'

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError:
                raise UnsupportedCapability() from None
            self._client = httpx.AsyncClient(
                trust_env=False, follow_redirects=False, verify=True,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
                transport=httpx.AsyncHTTPTransport(retries=0, verify=True,
                    limits=httpx.Limits(max_connections=2, max_keepalive_connections=2)),
            )
        return self._client

    async def request(self, method: str, path: str, *, body: bytes | None = None,
                      deadline: float, max_response_bytes: int = 1048576) -> bytes:
        if method not in ('GET', 'POST') or type(method) is not str:
            raise InvalidRequest()
        path = _path(path)
        if re.fullmatch(r'/(?:collections/[A-Za-z][A-Za-z0-9_-]{0,63}(?:/points/query)?|cluster)?', path) is None:
            raise InvalidRequest()
        if (method == 'GET' and body is not None or method == 'POST' and
                (not path.endswith('/points/query') or type(body) is not bytes)):
            raise InvalidRequest()
        end = deadline_value(deadline)
        if (type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 1048576
                or body is not None and (type(body) is not bytes or len(body) > 262144)):
            raise InvalidRequest()
        if self._closed:
            raise InvalidRequest()
        if self._active is not None:
            raise ProviderUnavailable()
        self._active = asyncio.current_task()
        try:
            async with asyncio.timeout_at(end):
                client = self._get_client()
                headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
                if body is not None:
                    headers['Content-Type'] = 'application/json'
                if self._api_key is not None:
                    headers['api-key'] = self._api_key
                async with client.stream(method, self._endpoint + path, content=body,
                                         headers=headers, timeout=max(0.001, end - asyncio.get_running_loop().time()),
                                         follow_redirects=False) as response:
                    if not 200 <= response.status_code < 300:
                        raise ProviderUnavailable()
                    encoding = response.headers.get('content-encoding', 'identity').lower().strip()
                    if encoding != 'identity':
                        raise ProviderUnavailable()
                    content_length = response.headers.get('content-length')
                    if content_length is not None:
                        if not content_length.isdecimal() or int(content_length) > max_response_bytes:
                            raise ProviderUnavailable()
                    result = bytearray()
                    async for chunk in response.aiter_raw(chunk_size=16384):
                        if type(chunk) is not bytes or len(result) + len(chunk) > max_response_bytes:
                            raise ProviderUnavailable()
                        result.extend(chunk)
                    deadline_value(end)
                    return bytes(result)
        except asyncio.CancelledError:
            raise
        except CragkitError as error:
            raise safe_transport_error(error) from None
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception:
            raise ProviderUnavailable() from None
        finally:
            self._active = None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        active = self._active
        if active is not None and active is not asyncio.current_task():
            active.cancel()
            done, _ = await asyncio.wait({active}, timeout=1)
            if not done:
                active.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        if self._owned and self._client is not None:
            try:
                async with asyncio.timeout(1):
                    await self._client.aclose()
            except (TimeoutError, Exception):
                raise ProviderUnavailable() from None
