"""Fake HTTP only: no account access, live TLS or provider quality evidence."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_adapters import ProviderRequest, ProviderAdapterError
from provider_http import HttpProviderSend


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks=(b'{}',), wait=None):
        self.chunks, self.wait, self.closed = chunks, wait, False

    async def __aiter__(self):
        if self.wait is not None:
            await self.wait()
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def request(provider='openai'):
    model = 'text-embedding-3-small' if provider == 'openai' else 'rerank-v5.0-fast'
    return ProviderRequest(provider, model, json.dumps({'model': model}).encode(), 'a'*64)


async def invoke(send, row=None, **kwargs):
    return await send(row or request(), deadline=kwargs.pop('deadline', time.monotonic()+2),
                      max_response_bytes=kwargs.pop('max_response_bytes', 100), **kwargs)


@pytest.mark.parametrize('provider,url', [('openai','https://api.openai.com/v1/embeddings'),
    ('cohere','https://api.cohere.com/v2/rerank')])
def test_fixed_routes_auth_snapshot_and_response_closure(provider, url):
    stream = Stream()
    keys = {provider:'fake-original-key'}
    def handler(row):
        assert str(row.url) == url and row.method == 'POST'
        assert row.headers['authorization'] == 'Bearer fake-original-key'
        assert row.headers['accept-encoding'] == 'identity'
        return httpx.Response(200, headers={'content-type':'application/json'}, stream=stream)
    send = HttpProviderSend(keys, transport=httpx.MockTransport(handler))
    keys[provider] = 'changed'
    async def run():
        async with send:
            assert await invoke(send, request(provider)) == b'{}'
        assert send._client.is_closed
        await send.aclose()
    asyncio.run(run())
    assert stream.closed and 'fake-original-key' not in repr(send)


@pytest.mark.parametrize('keys', [{}, {'unknown':'fake'}, {'cohere':'sk-wrong-provider'},
    {'openai':''}, {'openai':'bad\nkey'}, {'openai':None}])
def test_invalid_keys(keys):
    with pytest.raises(ProviderAdapterError):
        HttpProviderSend(keys)


@pytest.mark.parametrize('mutation', ['class','provider','model','body','duplicate','replay','deadline',
    'huge_deadline','limit','boolean_limit','body_cap','past'])
def test_invalid_input_never_dispatches(mutation):
    calls = []
    send = HttpProviderSend({'openai':'fake'}, transport=httpx.MockTransport(lambda r:calls.append(r)))
    row, options = request(), {}
    if mutation == 'class': row = object()
    if mutation == 'provider': row = replace(row, provider='cohere')
    if mutation == 'model': row = replace(row, model='wrong')
    if mutation == 'body': row = replace(row, body=b'[]')
    if mutation == 'duplicate': row = replace(row, body=b'{"model":"x","model":"text-embedding-3-small"}')
    if mutation == 'replay': row = replace(row, replay_key='invalid')
    if mutation == 'deadline': options['deadline'] = float('nan')
    if mutation == 'huge_deadline': options['deadline'] = 10**1000
    if mutation == 'limit': options['max_response_bytes'] = 2097153
    if mutation == 'boolean_limit': options['max_response_bytes'] = True
    if mutation == 'body_cap': row = replace(row, body=b' '*65537)
    if mutation == 'past': options['deadline'] = time.monotonic()-1
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError): await invoke(send, row, **options)
    asyncio.run(run())
    assert calls == []


@pytest.mark.parametrize('status,headers,chunks', [(302, {'location':'https://evil.test'},(b'{}',)),
    (429,{},(b'secret-response',)), (200,{'content-type':'text/html'},(b'{}',)),
    (200,{'content-encoding':'gzip'},(b'{}',)), (200,{'content-length':'101'},(b'{}',)),
    (200,{'content-length':'invalid'},(b'{}',)), (200,{},(b'x'*60,b'y'*60))])
def test_response_guards_close_and_sanitize(status, headers, chunks):
    stream, calls = Stream(chunks), []
    def handler(row):
        calls.append(row)
        return httpx.Response(status, headers={'content-type':'application/json', **headers}, stream=stream)
    async def run():
        async with HttpProviderSend({'openai':'fake-key'}, transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^provider_http_failed$') as error:
                await invoke(send)
            assert error.value.__cause__ is None
    asyncio.run(run())
    assert stream.closed and len(calls) == 1


def test_whole_stream_deadline_cancellation_and_concurrent_refusal():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait():
            entered.set()
            await release.wait()
        streams = []
        def handler(row):
            stream = Stream(wait=wait); streams.append(stream)
            return httpx.Response(200, headers={'content-type':'application/json'}, stream=stream)
        async with HttpProviderSend({'openai':'fake'}, transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='deadline_exceeded'):
                await invoke(send, deadline=time.monotonic()+.02)
            assert streams[-1].closed
            entered.clear()
            task = asyncio.create_task(invoke(send))
            await entered.wait()
            with pytest.raises(ProviderAdapterError, match='concurrent_dispatch'):
                await invoke(send)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert streams[-1].closed
            release.set()
            assert await invoke(send) == b'{}'
    asyncio.run(run())


def test_network_failure_is_fixed_and_not_retried():
    calls=[]
    def handler(row):
        calls.append(row)
        raise httpx.ConnectError('fake-key private body', request=row)
    async def run():
        async with HttpProviderSend({'openai':'fake-key'},transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^provider_http_failed$') as error:
                await invoke(send)
            assert error.value.__context__ is None and error.value.__cause__ is None
    asyncio.run(run())
    assert len(calls)==1


def test_client_options_ignore_environment_ca_and_proxy(monkeypatch):
    import provider_http
    actual = httpx.AsyncClient
    options = []
    def factory(**kwargs):
        options.append(kwargs)
        return actual(**kwargs)
    monkeypatch.setattr(provider_http.httpx,'AsyncClient',factory)
    monkeypatch.setenv('SSL_CERT_FILE','/nonexistent/private-ca')
    monkeypatch.setenv('HTTPS_PROXY','https://private.invalid')
    async def run():
        send = HttpProviderSend({'openai':'fake'})
        with pytest.raises(ProviderAdapterError): await invoke(send)
        async with send: pass
        with pytest.raises(ProviderAdapterError): await send.__aenter__()
        with pytest.raises(ProviderAdapterError): await invoke(send)
    asyncio.run(run())
    assert options[0]['verify'] is True and options[0]['trust_env'] is False
    assert options[0]['follow_redirects'] is False and options[0]['timeout'] is None
    assert options[0]['limits'].max_connections == 1


def test_malformed_json_uses_http_code_without_retained_exception():
    async def run():
        async with HttpProviderSend({'openai':'fake'}, transport=httpx.MockTransport(
                lambda row: pytest.fail('invalid body dispatched'))) as send:
            with pytest.raises(ProviderAdapterError, match='^provider_http_invalid$') as error:
                await invoke(send, replace(request(), body=b'{private invalid JSON'))
            assert error.value.__context__ is None and error.value.__cause__ is None
    asyncio.run(run())


def test_client_close_failure_has_no_credential_bearing_context():
    class FaultyClose(httpx.MockTransport):
        async def aclose(self):
            raise httpx.ConnectError('fake-key private close failure')
    async def run():
        send = HttpProviderSend({'openai': 'fake-key'}, transport=FaultyClose(lambda row: None))
        await send.__aenter__()
        with pytest.raises(ProviderAdapterError, match='^provider_http_close_failed$') as error:
            await send.aclose()
        assert error.value.__cause__ is None and error.value.__context__ is None
        with pytest.raises(ProviderAdapterError):
            await invoke(send)
    asyncio.run(run())
