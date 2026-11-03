"""Fake HTTP only: no account access, live TLS or provider quality evidence."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import traceback

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_adapters import ProviderRequest, ProviderAdapterError
from provider_http import HttpProviderSend


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks=(b'{}',), wait=None):
        self.chunks, self.wait, self.closed = chunks, wait, False
        self.iterations = 0

    async def __aiter__(self):
        self.iterations += 1
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


@pytest.mark.parametrize('status,headers,chunks,code', [
    (302, {'location':'https://evil.test'},(b'{}',), 'provider_http_failed'),
    (429,{},(b'secret-response',), 'provider_http_rate_limited'),
    (200,{'content-type':'text/html'},(b'{}',), 'provider_http_failed'),
    (200,{'content-encoding':'gzip'},(b'{}',), 'provider_http_failed'),
    (200,{'content-length':'101'},(b'{}',), 'provider_http_failed'),
    (200,{'content-length':'invalid'},(b'{}',), 'provider_http_failed'),
    (200,{},(b'x'*60,b'y'*60), 'provider_http_failed')])
def test_response_guards_close_and_sanitize(status, headers, chunks, code):
    stream, calls = Stream(chunks), []
    def handler(row):
        calls.append(row)
        return httpx.Response(status, headers={'content-type':'application/json', **headers}, stream=stream)
    async def run():
        async with HttpProviderSend({'openai':'fake-key'}, transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^' + code + '$') as error:
                await invoke(send)
            assert error.value.__cause__ is None
    asyncio.run(run())
    assert stream.closed and len(calls) == 1


@pytest.mark.parametrize('status,code', [(401, 'provider_http_auth_failed'),
    (403, 'provider_http_auth_failed'), (429, 'provider_http_rate_limited'),
    (500, 'provider_http_server_failed'), (503, 'provider_http_server_failed'),
    (599, 'provider_http_server_failed'), (400, 'provider_http_failed'),
    (404, 'provider_http_failed'), (499, 'provider_http_failed'),
    (600, 'provider_http_failed')])
def test_status_categories_do_not_read_body_or_retry(status, code):
    private = 'synthetic-private-marker'
    stream, calls = Stream((private.encode(),)), []
    def handler(row):
        calls.append(row)
        return httpx.Response(status, headers={'content-type': 'text/private',
            'content-encoding': 'gzip', 'content-length': 'invalid',
            'x-private': private}, stream=stream)
    async def run():
        async with HttpProviderSend({'openai': private},
                transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^' + code + '$') as error:
                await invoke(send)
            assert error.value.__cause__ is None and error.value.__context__ is None
            assert private not in repr(send) + repr(error.value)
            assert private not in ''.join(traceback.format_exception(error.value))
    asyncio.run(run())
    assert stream.closed and stream.iterations == 0 and len(calls) == 1


def test_adapter_error_from_transport_is_sanitized_without_context():
    calls = []
    def handler(row):
        calls.append(row)
        raise ProviderAdapterError('synthetic-private-marker')
    async def run():
        async with HttpProviderSend({'openai': 'synthetic-private-marker'},
                transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^provider_http_failed$') as error:
                await invoke(send)
            assert error.value.__cause__ is None and error.value.__context__ is None
            assert 'synthetic-private-marker' not in ''.join(traceback.format_exception(error.value))
    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize('fault', ['stream', 'close'])
def test_private_response_faults_are_sanitized_and_not_retried(fault):
    class FaultyStream(Stream):
        async def __aiter__(self):
            if fault == 'stream':
                raise httpx.ReadError('synthetic-private-marker')
            async for chunk in super().__aiter__():
                yield chunk

        async def aclose(self):
            self.closed = True
            if fault == 'close':
                raise ProviderAdapterError('synthetic-private-marker')
    stream, calls = FaultyStream(), []
    def handler(row):
        calls.append(row)
        return httpx.Response(429 if fault == 'close' else 200,
            headers={'content-type': 'application/json'}, stream=stream)
    async def run():
        async with HttpProviderSend({'openai': 'synthetic-private-marker'},
                transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^provider_http_failed$') as error:
                await invoke(send)
            assert error.value.__cause__ is None and error.value.__context__ is None
            assert 'synthetic-private-marker' not in ''.join(traceback.format_exception(error.value))
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


class PacingClock:
    def __init__(self):
        self.now = 100.0
        self.delays = []

    def read(self):
        return self.now

    async def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay


def production_sender_with_fake_client(monkeypatch, clock, calls, handler=None):
    """Exercise transport=None without opening a network connection."""
    from types import SimpleNamespace
    import provider_http
    actual = httpx.AsyncClient

    def default_handler(row):
        calls.append((str(row.url), clock.now))
        return httpx.Response(200, headers={'content-type': 'application/json'}, stream=Stream())

    def client(**options):
        assert options['transport'] is None
        options['transport'] = httpx.MockTransport(handler or default_handler)
        return actual(**options)

    monkeypatch.setattr(provider_http.httpx, 'AsyncClient', client)
    monkeypatch.setattr(provider_http, 'time', SimpleNamespace(monotonic=clock.read))
    send = HttpProviderSend({'cohere': 'synthetic-key', 'openai': 'synthetic-key'})
    assert send._pacer is not None
    send._pacer._clock = clock.read
    send._pacer._sleep = clock.sleep
    return send


def test_production_branch_spaces_eleven_cohere_calls_without_waiting_in_real_time(monkeypatch):
    clock, calls = PacingClock(), []
    send = production_sender_with_fake_client(monkeypatch, clock, calls)

    async def run():
        async with send:
            await invoke(send, request('cohere'), deadline=clock.now + 25)
            await invoke(send, request('openai'), deadline=clock.now + 25)
            for _ in range(10):
                await invoke(send, request('cohere'), deadline=clock.now + 25)
        assert send._client.is_closed

    asyncio.run(run())
    cohere = [at for url, at in calls if url == 'https://api.cohere.com/v2/rerank']
    assert len(calls) == 12 and len(cohere) == 11
    assert all(right - left >= 6.1 for left, right in zip(cohere, cohere[1:]))
    assert cohere[-1] - cohere[0] >= 61
    assert calls[0][1] == calls[1][1]  # OpenAI has no added pacing delay.


@pytest.mark.parametrize('late_wakeup', [False, True])
def test_production_pacing_never_sends_after_insufficient_or_overslept_deadline(monkeypatch, late_wakeup):
    clock, calls = PacingClock(), []
    send = production_sender_with_fake_client(monkeypatch, clock, calls)

    async def run():
        async with send:
            await invoke(send, request('cohere'), deadline=clock.now + 25)
            if late_wakeup:
                async def sleep(delay):
                    clock.now += 30
                send._pacer._sleep = sleep
            with pytest.raises(ProviderAdapterError, match='^deadline_exceeded$'):
                await invoke(send, request('cohere'), deadline=125 if late_wakeup else 105)
            assert send._pacer._last_cohere == 100
            assert not send._inflight

    asyncio.run(run())
    assert len(calls) == 1


def test_production_pacing_cancellation_leaves_no_second_send(monkeypatch):
    clock, calls = PacingClock(), []
    send = production_sender_with_fake_client(monkeypatch, clock, calls)

    async def run():
        entered = asyncio.Event()

        async def sleep(delay):
            entered.set()
            await asyncio.Event().wait()

        async with send:
            await invoke(send, request('cohere'), deadline=125)
            send._pacer._sleep = sleep
            task = asyncio.create_task(invoke(send, request('cohere'), deadline=125))
            await entered.wait()
            with pytest.raises(ProviderAdapterError, match='^concurrent_dispatch$'):
                await invoke(send, request('openai'), deadline=125)
            task.cancel('synthetic-private-cancellation')
            with pytest.raises(asyncio.CancelledError) as error:
                await task
            assert error.value.args == ()
            assert not send._inflight and send._pacer._last_cohere == 100
        assert send._client.is_closed

    asyncio.run(run())
    assert len(calls) == 1


def test_mock_transport_does_not_create_production_pacer():
    send = HttpProviderSend({'cohere': 'synthetic-key'}, transport=httpx.MockTransport(lambda row: None))
    assert send._pacer is None


def test_untrusted_adapter_exception_stringifier_is_never_called():
    class HostileError(ProviderAdapterError):
        def __str__(self):
            pytest.fail('Untrusted exception stringifier called')

    def handler(row):
        raise HostileError('synthetic-private-detail')

    async def run():
        async with HttpProviderSend({'openai': 'synthetic-key'},
                transport=httpx.MockTransport(handler)) as send:
            with pytest.raises(ProviderAdapterError, match='^provider_http_failed$') as error:
                await invoke(send)
            assert error.value.__context__ is None and error.value.__cause__ is None

    asyncio.run(run())


def test_delayed_first_dispatch_still_spaces_eleven_actual_dispatches(monkeypatch):
    clock, calls = PacingClock(), []
    def handler(row):
        if not calls:
            clock.now += 10
        calls.append(clock.now)
        return httpx.Response(200, headers={'content-type': 'application/json'}, stream=Stream())
    send = production_sender_with_fake_client(monkeypatch, clock, calls, handler)
    async def run():
        async with send:
            for _ in range(11):
                assert await invoke(send, request('cohere'), deadline=clock.now + 25) == b'{}'
    asyncio.run(run())
    assert len(calls) == 11
    assert all(right - left >= 6.1 for left, right in zip(calls, calls[1:]))
    assert calls[-1] - calls[0] >= 61


def test_stream_cleanup_holds_inflight_and_anchors_next_dispatch(monkeypatch):
    clock, calls = PacingClock(), []
    entered, release = asyncio.Event(), asyncio.Event()
    class ClosingStream(Stream):
        async def aclose(self):
            entered.set()
            await release.wait()
            clock.now += 10
            await super().aclose()
    stream = ClosingStream()
    def handler(row):
        calls.append(clock.now)
        return httpx.Response(200, headers={'content-type': 'application/json'},
            stream=stream if len(calls) == 1 else Stream())
    send = production_sender_with_fake_client(monkeypatch, clock, calls, handler)
    finishes = []
    actual_finish = send._pacer.finish
    def finish(provider):
        assert send._inflight and stream.closed
        finishes.append(clock.now)
        actual_finish(provider)
    send._pacer.finish = finish
    async def run():
        async with send:
            task = asyncio.create_task(invoke(send, request('cohere'), deadline=125))
            await entered.wait()
            assert not task.done() and finishes == []
            with pytest.raises(ProviderAdapterError, match='^concurrent_dispatch$'):
                await invoke(send, request('cohere'), deadline=125)
            release.set()
            assert await task == b'{}'
            assert finishes == [110]
            assert await invoke(send, request('cohere'), deadline=150) == b'{}'
    asyncio.run(run())
    assert len(calls) == 2 and calls[1] - finishes[0] >= 6.1


@pytest.mark.parametrize('fault', ['status', 'network', 'stream', 'timeout', 'cancel'])
def test_started_failures_finalize_and_space_next_dispatch(monkeypatch, fault):
    clock, calls, finishes = PacingClock(), [], []
    entered = asyncio.Event()
    class FaultStream(Stream):
        async def __aiter__(self):
            if fault == 'stream':
                raise httpx.ReadError('synthetic-private-fault')
            if fault in ('timeout', 'cancel'):
                entered.set()
                await asyncio.Event().wait()
            yield b'{}'
        async def aclose(self):
            clock.now += 10
            await super().aclose()
    stream = FaultStream()
    def handler(row):
        calls.append(clock.now)
        if len(calls) == 1 and fault == 'network':
            clock.now += 10
            raise httpx.ConnectError('synthetic-private-fault', request=row)
        return httpx.Response(429 if len(calls) == 1 and fault == 'status' else 200,
            headers={'content-type': 'application/json'}, stream=stream if len(calls) == 1 else Stream())
    send = production_sender_with_fake_client(monkeypatch, clock, calls, handler)
    actual_finish = send._pacer.finish
    def finish(provider):
        assert send._inflight
        finishes.append(clock.now)
        actual_finish(provider)
    send._pacer.finish = finish
    async def run():
        async with send:
            if fault == 'cancel':
                task = asyncio.create_task(invoke(send, request('cohere'), deadline=125))
                await entered.wait()
                task.cancel('synthetic-private-cancellation')
                with pytest.raises(asyncio.CancelledError) as error:
                    await task
                assert error.value.args == ()
                assert error.value.__context__ is None and error.value.__cause__ is None
            else:
                code = ('provider_http_rate_limited' if fault == 'status' else
                    'deadline_exceeded' if fault == 'timeout' else 'provider_http_failed')
                with pytest.raises(ProviderAdapterError, match='^' + code + '$') as error:
                    await invoke(send, request('cohere'),
                        deadline=clock.now + (.01 if fault == 'timeout' else 25))
                assert error.value.__context__ is None and error.value.__cause__ is None
            assert finishes == [110] and not send._inflight
            assert await invoke(send, request('cohere'), deadline=150) == b'{}'
    asyncio.run(run())
    assert len(calls) == 2 and calls[1] - finishes[0] >= 6.1
    assert fault == 'network' or stream.closed


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('fixed', [False, True])
def test_finish_fault_sanitized_and_cancellation_wins(monkeypatch, cancel, fixed):
    clock, calls = PacingClock(), []
    entered = asyncio.Event()
    async def wait():
        entered.set()
        await asyncio.Event().wait()
    stream = Stream(wait=wait if cancel else None)
    def handler(row):
        calls.append(clock.now)
        return httpx.Response(200, headers={'content-type': 'application/json'}, stream=stream)
    send = production_sender_with_fake_client(monkeypatch, clock, calls, handler)
    finishes = []
    def finish(provider):
        assert send._inflight and stream.closed
        finishes.append(provider)
        if fixed:
            raise ProviderAdapterError('provider_pacing_invalid')
        raise RuntimeError('synthetic-private-finalization')
    send._pacer.finish = finish
    async def run():
        async with send:
            if cancel:
                task = asyncio.create_task(invoke(send, request('cohere'), deadline=125))
                await entered.wait()
                task.cancel('synthetic-private-cancellation')
                with pytest.raises(asyncio.CancelledError) as error:
                    await task
                assert error.value.args == ()
            else:
                code = 'provider_pacing_invalid' if fixed else 'provider_http_failed'
                with pytest.raises(ProviderAdapterError, match='^' + code + '$') as error:
                    await invoke(send, request('cohere'), deadline=125)
            assert error.value.__context__ is None and error.value.__cause__ is None
            assert 'synthetic-private' not in ''.join(traceback.format_exception(error.value))
            assert not send._inflight
    asyncio.run(run())
    assert finishes == ['cohere'] and len(calls) == 1


@pytest.mark.parametrize('cancel', [False, True])
def test_failed_wait_does_not_finalize_or_send(monkeypatch, cancel):
    clock, calls = PacingClock(), []
    send = production_sender_with_fake_client(monkeypatch, clock, calls)
    finishes = []
    async def wait(provider, *, deadline):
        if cancel:
            raise asyncio.CancelledError('synthetic-private-wait')
        raise ProviderAdapterError('provider_pacing_failed')
    send._pacer.wait = wait
    send._pacer.finish = lambda provider: finishes.append(provider)
    async def run():
        async with send:
            if cancel:
                with pytest.raises(asyncio.CancelledError) as error:
                    await invoke(send, request('cohere'), deadline=125)
                assert error.value.args == ()
            else:
                with pytest.raises(ProviderAdapterError, match='^provider_pacing_failed$'):
                    await invoke(send, request('cohere'), deadline=125)
            assert not send._inflight
    asyncio.run(run())
    assert calls == [] and finishes == []


def test_late_response_cleanup_finalizes_but_cannot_return_success(monkeypatch):
    clock, calls, finishes = PacingClock(), [], []
    class LateClose(Stream):
        async def aclose(self):
            clock.now += 30
            await super().aclose()
    stream = LateClose()
    def handler(row):
        calls.append(clock.now)
        return httpx.Response(200, headers={'content-type': 'application/json'}, stream=stream)
    send = production_sender_with_fake_client(monkeypatch, clock, calls, handler)
    actual_finish = send._pacer.finish
    def finish(provider):
        assert stream.closed and send._inflight
        finishes.append(clock.now)
        actual_finish(provider)
    send._pacer.finish = finish
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError, match='^deadline_exceeded$'):
                await invoke(send, request('cohere'), deadline=125)
            assert not send._inflight
    asyncio.run(run())
    assert calls == [100] and finishes == [130]
