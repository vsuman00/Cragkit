"""Streaming and lifecycle checks with an injected HTTPX-shaped client."""
import asyncio

import pytest

from cragkit.errors import DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.qdrant import HttpxQdrantTransport


class Response:
    def __init__(self, chunks=(), *, status=200, headers=None):
        self.chunks = chunks
        self.status_code = status
        self.headers = {} if headers is None else headers
        self.closed = False
        self.entered = asyncio.Event()
        self.block = False

    async def __aenter__(self):
        self.entered.set()
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def aiter_raw(self, *, chunk_size):
        assert chunk_size == 16384
        if self.block:
            await asyncio.Event().wait()
        for chunk in self.chunks:
            yield chunk


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response

    async def aclose(self):
        self.closed = True


def test_endpoint_del_control_is_rejected_before_client_creation():
    with pytest.raises(InvalidRequest):
        HttpxQdrantTransport('https://example.invalid\x7f')


def test_stream_exact_bound_explicit_headers_and_borrowed_ownership():
    async def scenario():
        response = Response([b'{', b'}'])
        client = Client(response)
        transport = HttpxQdrantTransport('https://example.invalid', api_key='PRIVATE_TEST_TOKEN', client=client)
        assert 'PRIVATE_TEST_TOKEN' not in repr(transport)
        result = await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 1,
                                         max_response_bytes=2)
        assert result == b'{}' and response.closed
        kwargs = client.calls[0][2]
        assert kwargs['headers']['Accept-Encoding'] == 'identity'
        assert kwargs['headers']['api-key'] == 'PRIVATE_TEST_TOKEN'
        assert kwargs['follow_redirects'] is False
        await transport.close()
        await transport.close()
        assert not client.closed
        with pytest.raises(InvalidRequest):
            await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 1)
    asyncio.run(scenario())


@pytest.mark.parametrize('response', [Response([b'123']), Response([], headers={'content-length': '3'}),
    Response([], headers={'content-length': 'invalid'}), Response([], headers={'content-encoding': 'gzip'}),
    Response([], status=302), Response([], status=503)])
def test_reject_overflow_encoding_status_and_close_response(response):
    async def scenario():
        client = Client(response)
        transport = HttpxQdrantTransport('https://example.invalid', client=client)
        with pytest.raises(ProviderUnavailable) as caught:
            await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 1,
                                    max_response_bytes=2)
        assert response.closed and len(client.calls) == 1
        assert str(caught.value) == 'Provider is unavailable.'
    asyncio.run(scenario())


@pytest.mark.parametrize('endpoint', ['https://user:secret@example.invalid', 'https://example.invalid?secret=x',
    'https://example.invalid/#secret', 'https://example.invalid/base', '//example.invalid',
    'ftp://example.invalid', 'https://example.invalid:bad', 'https://example.invalid\\@other.invalid',
    'https://example.invalid/\n'])
def test_bad_endpoints(endpoint):
    with pytest.raises(InvalidRequest):
        HttpxQdrantTransport(endpoint)


@pytest.mark.parametrize('endpoint', ['http://example.invalid', 'http://192.168.1.1', 'http://0.0.0.0', 'http://localhost:6333', 'http://127.0.0.2:6333'])
def test_plaintext_requires_loopback(endpoint):
    with pytest.raises(UnsupportedCapability):
        HttpxQdrantTransport(endpoint, allow_loopback_http=True)


def test_loopback_http_explicit_only():
    for endpoint in ('http://127.0.0.1:6333', 'http://[::1]:6333'):
        with pytest.raises(UnsupportedCapability):
            HttpxQdrantTransport(endpoint)
        assert HttpxQdrantTransport(endpoint, allow_loopback_http=True)


@pytest.mark.parametrize('path', ['//evil.invalid', 'https://evil.invalid/', '/a/../b', '/a/%2e%2e/b',
    '/?secret=x', '/#secret', '/%2f%2fevil.invalid', '/a\\b', '/a%00'])
def test_path_validation_before_client(path):
    async def scenario():
        client = Client(Response())
        transport = HttpxQdrantTransport('https://example.invalid', client=client)
        with pytest.raises(InvalidRequest):
            await transport.request('GET', path, deadline=asyncio.get_running_loop().time() + 1)
        assert client.calls == []
    asyncio.run(scenario())


def test_deadline_cancellation_concurrency_and_close_settle_stream():
    async def scenario():
        response = Response()
        response.block = True
        client = Client(response)
        transport = HttpxQdrantTransport('https://example.invalid', client=client)
        task = asyncio.create_task(transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 2))
        await response.entered.wait()
        with pytest.raises(ProviderUnavailable):
            await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 1)
        await transport.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert response.closed and not client.closed
        response2 = Response()
        response2.block = True
        transport2 = HttpxQdrantTransport('https://example.invalid', client=Client(response2))
        with pytest.raises(DeadlineExceeded):
            await transport2.request('GET', '/', deadline=asyncio.get_running_loop().time() + .01)
        assert response2.closed
    asyncio.run(scenario())


def test_expired_deadline_invalid_body_and_bounds_no_io():
    async def scenario():
        client = Client(Response())
        transport = HttpxQdrantTransport('https://example.invalid', client=client)
        with pytest.raises(DeadlineExceeded):
            await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() - 1)
        for kwargs in ({'body': b'x' * 262145}, {'max_response_bytes': True}, {'body': 'bad'}):
            with pytest.raises(InvalidRequest):
                await transport.request('POST', '/', deadline=asyncio.get_running_loop().time() + 1, **kwargs)
        assert client.calls == []
    asyncio.run(scenario())


def test_arbitrary_client_error_is_redacted_and_no_retry():
    async def scenario():
        class Broken(Client):
            def stream(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise RuntimeError('PRIVATE_URI_AND_QUERY')
        client = Broken(Response())
        transport = HttpxQdrantTransport('https://example.invalid', client=client)
        with pytest.raises(ProviderUnavailable) as caught:
            await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 1)
        assert 'PRIVATE' not in str(caught.value)
        assert caught.value.__suppress_context__
        assert len(client.calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('error_class', [DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability])
def test_injected_client_mutated_typed_errors_are_redacted(error_class):
    async def scenario():
        error = error_class()
        error.args = ('PRIVATE_CLIENT_CANARY',)
        error.code = 'PRIVATE_CODE'
        class Broken(Client):
            def stream(self, *args, **kwargs):
                raise error
        transport = HttpxQdrantTransport('https://example.invalid', client=Broken(Response()))
        with pytest.raises(error_class) as caught:
            await transport.request('GET', '/', deadline=asyncio.get_running_loop().time() + 1)
        assert caught.value is not error
        assert caught.value.code == error_class.code
        assert 'PRIVATE' not in str(caught.value)
        assert caught.value.__suppress_context__ is True
    asyncio.run(scenario())


def test_explicit_api_key_length_boundary_before_any_io():
    client = Client(Response())
    assert HttpxQdrantTransport('https://example.invalid', api_key='x' * 4096, client=client)
    with pytest.raises(InvalidRequest):
        HttpxQdrantTransport('https://example.invalid', api_key='x' * 4097, client=client)
    assert client.calls == []
