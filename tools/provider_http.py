"""Fixed evaluation HTTP destinations; credentials are supplied explicitly."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import math
import re
import time

import httpx

from provider_adapters import ProviderAdapterError, ProviderRequest, _json
from evaluation_pacing import EvaluationPacer

_ROUTES = {
    'openai': ('text-embedding-3-small', 'https://api.openai.com/v1/embeddings', 65536),
    'cohere': ('rerank-v5.0-fast', 'https://api.cohere.com/v2/rerank', 300000),
}


def _invalid():
    raise ProviderAdapterError('provider_http_invalid')


class HttpProviderSend:
    """One explicitly owned client, one operation, no credential discovery."""
    def __init__(self, keys, *, transport=None):
        if not isinstance(keys, Mapping):
            _invalid()
        self._keys = dict(keys)
        if not self._keys or any(provider not in _ROUTES or type(key) is not str
                or not 1 <= len(key) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key)
                or (provider == 'cohere' and key.startswith('sk-'))
                for provider, key in self._keys.items()):
            _invalid()
        self._transport = transport
        self._pacer = EvaluationPacer() if transport is None else None
        self._client = None
        self._closed = False
        self._inflight = False

    async def __aenter__(self):
        if self._closed or self._client is not None:
            _invalid()
        # HTTPX 0.28.1 verify=True + trust_env=False selects certifi explicitly,
        # ignoring SSL_CERT_FILE, SSL_CERT_DIR and environment proxy settings.
        self._client = httpx.AsyncClient(verify=True, trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            transport=self._transport, timeout=None)
        return self

    async def aclose(self):
        self._closed = True
        failed = False
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                failed = True
        if failed:
            raise ProviderAdapterError('provider_http_close_failed')

    async def __aexit__(self, *args):
        await self.aclose()

    async def __call__(self, request, *, deadline, max_response_bytes):
        if (self._closed or self._client is None or type(request) is not ProviderRequest
                or type(deadline) not in (int, float) or type(max_response_bytes) is not int
                or not 0 < max_response_bytes <= 2097152):
            _invalid()
        try:
            valid_deadline = math.isfinite(deadline)
        except OverflowError:
            valid_deadline = False
        if not valid_deadline or type(request.provider) is not str or request.provider not in self._keys:
            _invalid()
        model, url, body_limit = _ROUTES[request.provider]
        if (request.model != model or type(request.replay_key) is not str
                or re.fullmatch('[0-9a-fA-F]{64}', request.replay_key) is None):
            _invalid()
        invalid_body = False
        try:
            payload = _json(request.body, body_limit)
        except ProviderAdapterError:
            invalid_body = True
        if invalid_body:
            _invalid()
        if type(payload) is not dict or payload.get('model') != model:
            _invalid()
        if self._inflight:
            raise ProviderAdapterError('concurrent_dispatch')
        if time.monotonic() >= deadline:
            raise ProviderAdapterError('deadline_exceeded')
        self._inflight = True
        failure = None
        result = None
        started = False
        cancelled = False
        try:
            try:
                async with asyncio.timeout(deadline - time.monotonic()):
                    if self._pacer is not None:
                        await self._pacer.wait(request.provider, deadline=deadline)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError()
                    if time.monotonic() >= deadline:
                        raise ProviderAdapterError('deadline_exceeded')
                    started = True
                    async with self._client.stream('POST', url, content=request.body, headers={
                            'Authorization': 'Bearer ' + self._keys[request.provider],
                            'Content-Type': 'application/json', 'Accept': 'application/json',
                            'Accept-Encoding': 'identity'}) as response:
                        if response.status_code != 200:
                            if response.status_code in (401, 403):
                                code = 'provider_http_auth_failed'
                            elif response.status_code == 429:
                                code = 'provider_http_rate_limited'
                            elif 500 <= response.status_code <= 599:
                                code = 'provider_http_server_failed'
                            else:
                                code = 'provider_http_failed'
                            raise ProviderAdapterError(code)
                        content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                        encoding = response.headers.get('content-encoding', 'identity').strip().lower()
                        length = response.headers.get('content-length')
                        if (content_type != 'application/json'
                                or encoding != 'identity' or (length is not None and
                                (not length.isascii() or not length.isdecimal() or int(length) > max_response_bytes))):
                            raise ProviderAdapterError('provider_http_failed')
                        chunks, size = [], 0
                        async for chunk in response.aiter_raw():
                            size += len(chunk)
                            if size > max_response_bytes:
                                raise ProviderAdapterError('provider_http_failed')
                            chunks.append(chunk)
                        if time.monotonic() >= deadline:
                            raise ProviderAdapterError('deadline_exceeded')
                        result = b''.join(chunks)
            except asyncio.CancelledError:
                cancelled = True
            except TimeoutError:
                failure = 'deadline_exceeded'
            except ProviderAdapterError as error:
                code = (error.args[0] if type(error) is ProviderAdapterError and len(error.args) == 1
                        and type(error.args[0]) is str else None)
                failure = code if code in {
                    'provider_http_auth_failed', 'provider_http_rate_limited',
                    'provider_http_server_failed', 'provider_http_failed',
                    'provider_pacing_invalid', 'provider_pacing_failed', 'concurrent_dispatch',
                    'deadline_exceeded'} else 'provider_http_failed'
            except Exception:
                failure = 'provider_http_failed'
            if started and self._pacer is not None:
                try:
                    self._pacer.finish(request.provider)
                except asyncio.CancelledError:
                    cancelled = True
                except ProviderAdapterError as error:
                    code = (error.args[0] if type(error) is ProviderAdapterError
                            and len(error.args) == 1 and type(error.args[0]) is str else None)
                    failure = code if code in {
                        'provider_pacing_invalid', 'provider_pacing_failed',
                        'concurrent_dispatch', 'deadline_exceeded'} else 'provider_http_failed'
                except Exception:
                    failure = 'provider_http_failed'
            # Decide outcomes outside all handlers, without retaining private
            # transport/cleanup/finalization exceptions. Cancellation wins.
            if cancelled or asyncio.current_task().cancelling():
                raise asyncio.CancelledError()
            if failure is not None:
                raise ProviderAdapterError(failure)
            if time.monotonic() >= deadline:
                raise ProviderAdapterError('deadline_exceeded')
            return result
        finally:
            self._inflight = False
