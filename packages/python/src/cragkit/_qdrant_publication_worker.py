"""Fixed native ordinary publication child and its private bounded control channel."""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import signal
import socket
import struct
import sys
from types import SimpleNamespace
from typing import Any
from weakref import WeakKeyDictionary

from ._qdrant_contract import QdrantConfig, parse_model
from ._qdrant_supervisor import ManagedQdrantSupervisor
from ._qdrant_transport import deadline_value
from .contracts import Limits, TrustedScope
from .errors import (DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable,
                     UnauthorizedScope, UnsupportedCapability, IndexNotReady)
from .execution import ExecutionLedger, BudgetExhausted

_VERSION = 1
_MAX_FRAME = 65536
_MAX_TOTAL = 1048576
_MAX_BOOT = 262144
_IDENTITY = {'instance_id', 'backend_namespace', 'storage_identity', 'supervisor_id', 'epoch',
             'credential_generation', 'recovery', 'sealed', 'alive'}
_CODES = {'DeadlineExceeded', 'IntegrityViolation', 'InvalidRequest', 'ProviderUnavailable',
          'UnauthorizedScope', 'UnsupportedCapability', 'IndexNotReady', 'BudgetExhausted', 'CancelledError'}
_CONTROLLERS: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()
_OWNED: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()
_HOSTS: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()
_HTTP: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()
_POISONED: set[Any] = set()


class _TerminalFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _code(error: BaseException) -> str:
    name = type(error).__name__
    return name if name in _CODES else 'ProviderUnavailable'


def _raise(code: str) -> None:
    kinds = {'DeadlineExceeded': DeadlineExceeded, 'IntegrityViolation': IntegrityViolation,
        'InvalidRequest': InvalidRequest, 'UnauthorizedScope': UnauthorizedScope,
        'UnsupportedCapability': UnsupportedCapability, 'BudgetExhausted': BudgetExhausted, 'IndexNotReady': IndexNotReady}
    raise kinds.get(code, ProviderUnavailable)()


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidRequest() from None


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise InvalidRequest()
    return value


def _integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise InvalidRequest()
    return value


def _decode(raw: bytes) -> Any:
    def pairs(items: Any) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise InvalidRequest()
            value[key] = item
        return value
    def constant(_: str) -> Any:
        raise InvalidRequest()
    def number(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise InvalidRequest()
        return result
    try:
        return json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                          parse_constant=constant, parse_float=number)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidRequest() from None


class _Channel:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer = reader, writer
        self.sent = self.received = self.sequence = 0
        self.pending = False
        self.closed = False

    async def send(self, value: Any, deadline: float) -> None:
        raw = _bytes(value)
        if self.closed or not 1 <= len(raw) <= _MAX_FRAME or self.sent + len(raw) + 4 > _MAX_TOTAL:
            raise InvalidRequest()
        self.sent += len(raw) + 4
        async with asyncio.timeout_at(deadline_value(deadline)):
            self.writer.write(struct.pack('!I', len(raw)) + raw)
            await self.writer.drain()

    async def receive(self, deadline: float) -> Any:
        if self.closed:
            raise ProviderUnavailable()
        try:
            async with asyncio.timeout_at(deadline_value(deadline)):
                length = struct.unpack('!I', await self.reader.readexactly(4))[0]
                if not 1 <= length <= _MAX_FRAME or self.received + length + 4 > _MAX_TOTAL:
                    raise InvalidRequest()
                self.received += length + 4
                return _decode(await self.reader.readexactly(length))
        except asyncio.IncompleteReadError:
            raise ProviderUnavailable() from None
        except TimeoutError:
            raise DeadlineExceeded() from None

    async def rpc(self, op: str, data: Any, deadline: float) -> Any:
        if self.pending or self.sequence >= 128:
            raise ProviderUnavailable()
        self.pending = True
        self.sequence += 1
        try:
            remaining = max(1, int((deadline_value(deadline) - asyncio.get_running_loop().time()) * 1000))
            await self.send(dict(v=1, id=self.sequence, op=op, remaining_ms=remaining, data=data), deadline)
            reply = await self.receive(deadline)
            if type(reply) is not dict or reply.get('v') != 1 or type(reply.get('v')) is not int or type(reply.get('id')) is not int or reply.get('id') != self.sequence:
                raise InvalidRequest()
            if type(reply.get('ok')) is not bool:
                raise InvalidRequest()
            if reply['ok']:
                return _object(reply, {'v', 'id', 'ok', 'data'})['data']
            code = _object(reply, {'v', 'id', 'ok', 'error'})['error']
            if type(code) is not str or code not in _CODES:
                raise InvalidRequest()
            _raise(code)
        except BaseException:
            self.closed = True
            self.writer.close()
            raise
        finally:
            self.pending = False

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.writer.close()
            try:
                async with asyncio.timeout(1):
                    await self.writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                # A reaped/killed peer may reset the already closing socket.
                pass


async def _send_boot(channel: _Channel, value: Any, deadline: float) -> None:
    raw = _bytes(value)
    if not 1 <= len(raw) <= _MAX_BOOT:
        raise InvalidRequest()
    await channel.send(dict(v=1, op='boot_begin', total=len(raw), sha256=hashlib.sha256(raw).hexdigest()), deadline)
    for offset in range(0, len(raw), 48000):
        await channel.send(dict(v=1, op='boot_chunk', offset=offset,
            data=base64.b64encode(raw[offset:offset + 48000]).decode('ascii')), deadline)
    await channel.send(dict(v=1, op='boot_end'), deadline)


async def _read_boot(channel: _Channel, deadline: float) -> Any:
    begin = _object(await channel.receive(deadline), {'v', 'op', 'total', 'sha256'})
    if type(begin['v']) is not int or begin['v'] != 1 or begin['op'] != 'boot_begin':
        raise InvalidRequest()
    total = _integer(begin['total'], 1, _MAX_BOOT)
    buffer = bytearray(total)
    offset = 0
    chunks = 0
    while offset < total:
        chunk = _object(await channel.receive(deadline), {'v', 'op', 'offset', 'data'})
        if type(chunk['v']) is not int or chunk['v'] != 1 or chunk['op'] != 'boot_chunk' or type(chunk['offset']) is not int or chunk['offset'] != offset or type(chunk['data']) is not str:
            raise InvalidRequest()
        try:
            raw = base64.b64decode(chunk['data'], validate=True)
        except (ValueError, UnicodeError):
            raise InvalidRequest() from None
        if base64.b64encode(raw).decode('ascii') != chunk['data']:
            raise InvalidRequest()
        chunks += 1
        if chunks > 6 or not 1 <= len(raw) <= 48000 or offset + len(raw) > total:
            raise InvalidRequest()
        buffer[offset:offset + len(raw)] = raw
        offset += len(raw)
    end = _object(await channel.receive(deadline), {'v', 'op'})
    if type(end['v']) is not int or end != {'v': 1, 'op': 'boot_end'} or hashlib.sha256(buffer).hexdigest() != begin['sha256']:
        raise InvalidRequest()
    return _decode(bytes(buffer))



def _native_bounds(value: Any) -> None:
    stack = [(value, 0)]
    nodes = budget = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 4096 or depth > 32:
            raise InvalidRequest()
        kind = type(item)
        if kind is dict:
            if len(item) > 4096:
                raise InvalidRequest()
            budget += 2 + len(item)
            for key, child in item.items():
                if type(key) is not str:
                    raise InvalidRequest()
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif kind is list:
            if len(item) > 4096:
                raise InvalidRequest()
            budget += 2 + len(item)
            stack.extend((child, depth + 1) for child in item)
        elif kind is str:
            if len(item) > _MAX_BOOT:
                raise InvalidRequest()
            try:
                # Six bytes per code unit bounds JSON escapes before serialization.
                budget += 2 + max(len(item.encode('utf-8', errors='strict')), 6 * len(item))
            except UnicodeError:
                raise InvalidRequest() from None
        elif kind is int:
            if not -9007199254740991 <= item <= 9007199254740991:
                raise InvalidRequest()
            budget += 18
        elif kind is float:
            if not math.isfinite(item) or abs(item) > 9007199254740991:
                raise InvalidRequest()
            budget += 32
        elif item is None or kind is bool:
            budget += 5
        else:
            raise InvalidRequest()
        if budget > _MAX_BOOT:
            raise InvalidRequest()

def _job(value: Any) -> dict[str, Any]:
    from ._postgres_pool import PoolConfig
    from .qdrant_publication import _reference
    _native_bounds(value)
    encoded = _bytes(value)
    if len(encoded) > _MAX_BOOT:
        raise InvalidRequest()
    raw = _decode(encoded)
    _object(raw, {'writer_pool', 'config', 'scope', 'reference', 'limits'})
    pool = dict(raw['writer_pool'])
    for key in ('sslrootcert', 'passfile'):
        path = pool.get(key)
        if type(path) is not str or len(path.encode('utf-8')) > 4096:
            raise InvalidRequest()
        pool[key] = Path(path)
    try:
        parsed_pool = PoolConfig.model_validate(pool)
        config = parse_model(QdrantConfig, raw['config'])
        scope = parse_model(TrustedScope, raw['scope'])
        limits = parse_model(Limits, raw['limits'])
    except Exception:
        raise InvalidRequest() from None
    return dict(writer_pool=parsed_pool.model_dump(mode='json'), config=config.model_dump(mode='json'),
        scope=scope.model_dump(mode='json'), reference=_reference(raw['reference']), limits=limits.model_dump(mode='json'))


def _identity(value: Any) -> dict[str, Any]:
    raw = _object(value, _IDENTITY)
    for key in _IDENTITY - {'epoch', 'recovery', 'sealed', 'alive'}:
        if type(raw[key]) is not str or not 1 <= len(raw[key].encode('utf-8')) <= 256:
            raise InvalidRequest()
    _integer(raw['epoch'], 1, 9007199254740991)
    if raw['recovery'] is not None or raw['sealed'] is not False or raw['alive'] is not True:
        raise ProviderUnavailable()
    return raw


def is_worker(value: Any) -> bool:
    return type(value) is OrdinaryWorkerController and value in _CONTROLLERS and not _CONTROLLERS[value].closed


def is_controller(value: Any) -> bool:
    return type(value) is ManagedQdrantSupervisor or is_worker(value)


async def controller_profile(controller: Any, config: Any, *, deadline: float) -> Any:
    if type(controller) is ManagedQdrantSupervisor:
        return controller.profile_binding(config)
    if is_worker(controller):
        return await controller.profile_binding(config, deadline=deadline)
    raise InvalidRequest()


async def controller_attempt(controller: Any, attempt: Any, *, deadline: float) -> Any:
    if type(controller) is ManagedQdrantSupervisor:
        return controller.attempt_binding(attempt)
    if is_worker(controller):
        return await controller.attempt_binding(attempt, deadline=deadline)
    raise InvalidRequest()


async def controller_issue(controller: Any, binding: Any, *, deadline: float) -> Any:
    if type(controller) is ManagedQdrantSupervisor:
        return controller.issue_attempt(binding, deadline=deadline)
    if is_worker(controller):
        return await controller.issue_attempt(binding, deadline=deadline)
    raise InvalidRequest()


@asynccontextmanager
async def controller_finalization(controller: Any, attempt: Any, *, deadline: float) -> Any:
    if type(controller) is ManagedQdrantSupervisor:
        async with controller.control_session():
            yield
    elif is_worker(controller):
        async with controller.finalization(attempt, deadline=deadline):
            yield
    else:
        raise InvalidRequest()


class _Attempt:
    pass


def _controller_state(value: Any) -> Any:
    if type(value) is not OrdinaryWorkerController or value not in _CONTROLLERS:
        raise InvalidRequest()
    return _CONTROLLERS[value]


class OrdinaryWorkerController:
    __slots__ = ('__weakref__',)

    @property
    def job(self) -> Any:
        return _decode(_bytes(_controller_state(self).job))

    def __reduce__(self) -> Any:
        raise TypeError('Worker controllers cannot be serialized')
    def __init__(self, token: object, channel: _Channel, job: Any, identity: Any, deadline: float) -> None:
        if token is not _BOOT_TOKEN:
            raise InvalidRequest()
        _CONTROLLERS[self] = SimpleNamespace(channel=channel, job=_decode(_bytes(job)),
            identity=_decode(_bytes(identity)), deadline=deadline, attempts={}, handles=set(), closed=False)

    async def _rpc(self, op: str, data: Any, deadline: float) -> Any:
        state = _controller_state(self)
        if not is_worker(self) or state.closed:
            raise ProviderUnavailable()
        return await state.channel.rpc(op, data, min(deadline, state.deadline))

    async def profile_binding(self, config: Any, *, deadline: float) -> Any:
        state = _controller_state(self)
        result = await self._rpc('profile', dict(config_sha256=_digest(parse_model(QdrantConfig, config).model_dump(mode='json'))), deadline)
        if _identity(result) != state.identity:
            raise ProviderUnavailable()
        return result

    async def issue_attempt(self, binding: Any, *, deadline: float) -> Any:
        state = _controller_state(self)
        if len(state.attempts) >= 8:
            raise ProviderUnavailable()
        result = _object(await self._rpc('issue', binding, deadline), {'attempt_id', 'binding', 'endpoint', 'api_key'})
        _integer(result['attempt_id'], 1, 8)
        from ._qdrant_publication_verification import ordinary_binding
        result['binding'] = dict(ordinary_binding(result['binding']))
        if any(result['binding'].get(key) != value for key, value in binding.items()):
            raise IntegrityViolation()
        if any(record['attempt_id'] == result['attempt_id'] for record in state.attempts.values()):
            raise InvalidRequest()
        attempt = _Attempt()
        state.attempts[attempt] = result
        return attempt

    async def attempt_binding(self, attempt: Any, *, deadline: float) -> Any:
        state = _controller_state(self)
        if type(attempt) is not _Attempt or attempt not in state.attempts:
            raise InvalidRequest()
        record = state.attempts[attempt]
        result = _object(await self._rpc('validate', dict(attempt_id=record['attempt_id']), deadline), {'binding'})
        if result['binding'] != record['binding']:
            raise ProviderUnavailable()
        return dict(record['binding'])

    def transport_for(self, attempt: Any) -> Any:
        state = _controller_state(self)
        if not is_worker(self) or state.closed or type(attempt) is not _Attempt or attempt not in state.attempts or len(state.handles) >= 16:
            raise InvalidRequest()
        handle = _WorkerHTTP(self, attempt, state.attempts[attempt])
        state.handles.add(handle)
        return handle

    async def before_write(self, attempt: Any, dispatch: Any, *, deadline: float) -> None:
        state = _controller_state(self)
        record = state.attempts.get(attempt)
        if record is None:
            raise InvalidRequest()
        result = await self._rpc('before_write', dict(attempt_id=record['attempt_id'], **dispatch), deadline)
        _object(result, set())

    @asynccontextmanager
    async def finalization(self, attempt: Any, *, deadline: float) -> Any:
        state = _controller_state(self)
        if attempt not in state.attempts:
            raise InvalidRequest()
        await self._rpc('finalize_begin', dict(attempt_id=state.attempts[attempt]['attempt_id']), deadline)
        try:
            yield
        finally:
            await self._rpc('finalize_end', {}, deadline)

    async def authorize(self, scope: Any, collection: str, document_id: str) -> bool:
        state = _controller_state(self)
        selected = scope.model_dump(mode='json') if type(scope) is TrustedScope else scope
        if selected != state.job['scope'] or collection != state.job['reference']['collection'] or document_id != state.job['reference']['document_id']:
            raise UnauthorizedScope()
        result = _object(await self._rpc('authorize', dict(reference=state.job['reference'], scope_sha256=_digest(selected)), state.deadline), {'allowed'})
        if type(result['allowed']) is not bool:
            raise InvalidRequest()
        return result['allowed']

    async def close(self) -> None:
        state = _controller_state(self)
        if state.closed:
            return
        for handle in tuple(state.handles):
            await handle.close()
        state.closed = True
        state.attempts.clear()


_BOOT_TOKEN = object()


def _http_state(value: Any) -> Any:
    if type(value) is not _WorkerHTTP or value not in _HTTP:
        raise InvalidRequest()
    return _HTTP[value]


class _WorkerHTTP:
    __slots__ = ('__weakref__',)
    bounded_responses = cancellation_safe = True
    def __init__(self, controller: OrdinaryWorkerController, attempt: Any, record: Any) -> None:
        from urllib.parse import urlsplit
        endpoint = record['endpoint']
        if type(endpoint) is not str:
            raise InvalidRequest()
        parsed = urlsplit(endpoint)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise UnsupportedCapability()
        if type(record['api_key']) is not str or not 1 <= len(record['api_key']) <= 256:
            raise InvalidRequest()
        state = _controller_state(controller)
        if state.closed or state.attempts.get(attempt) is not record:
            raise InvalidRequest()
        _HTTP[self] = SimpleNamespace(controller=controller, attempt=attempt, record=record,
            client=None, closed=False, active=False)

    async def request(self, method: str, path: str, *, body: bytes | None = None,
                      deadline: float, max_response_bytes: int = 1048576) -> bytes:
        handle = _http_state(self)
        state = _controller_state(handle.controller)
        if state.closed or state.attempts.get(handle.attempt) is not handle.record:
            raise InvalidRequest()
        deadline = min(deadline_value(deadline), state.deadline)
        target = '/collections/' + state.job['config']['physical_collection']
        mutation = method == 'PUT' and path == target + '/points?wait=true&ordering=strong'
        if not (mutation or method == 'POST' and path in (target + '/points', target + '/points/scroll') or method == 'GET' and path == target):
            raise InvalidRequest()
        if handle.closed or handle.active or state.closed:
            raise ProviderUnavailable()
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 1048576 or body is not None and (type(body) is not bytes or len(body) > 1048576) or method != 'GET' and body is None:
            raise InvalidRequest()
        handle.active = True
        try:
            import httpx
            if handle.client is None:
                handle.client = httpx.AsyncClient(trust_env=False, follow_redirects=False,
                    transport=httpx.AsyncHTTPTransport(retries=0), limits=httpx.Limits(max_connections=1, max_keepalive_connections=1))
            async with asyncio.timeout_at(deadline):
                async with handle.client.stream(method, handle.record['endpoint'] + path, content=body,
                        headers={'api-key': handle.record['api_key'], 'Accept-Encoding': 'identity', 'Content-Type': 'application/json'},
                        timeout=max(.001, deadline - asyncio.get_running_loop().time()), follow_redirects=False) as response:
                    status = int(response.status_code)
                    if mutation:
                        await handle.controller._rpc('write_observed', dict(attempt_id=handle.record['attempt_id'],
                            dispatch_id=handle.record['binding']['dispatch_id'], status=status), deadline)
                    if response.headers.get('content-encoding', 'identity').lower().strip() != 'identity':
                        raise ProviderUnavailable()
                    length = response.headers.get('content-length')
                    if length is not None and (len(length) > 10 or not length.isdecimal() or int(length) > max_response_bytes):
                        raise ProviderUnavailable()
                    buffer = bytearray()
                    async for chunk in response.aiter_raw(chunk_size=16384):
                        if len(buffer) + len(chunk) > max_response_bytes:
                            raise ProviderUnavailable()
                        buffer.extend(chunk)
                    if status in (401, 403):
                        raise UnauthorizedScope()
                    if status != 200:
                        raise ProviderUnavailable()
                    return bytes(buffer)
        except TimeoutError:
            raise DeadlineExceeded() from None
        finally:
            handle.active = False

    async def close(self) -> None:
        handle = _http_state(self)
        if handle.active:
            raise ProviderUnavailable()
        if handle.client is not None:
            async with asyncio.timeout(1):
                await handle.client.aclose()
        handle.closed = True
        _controller_state(handle.controller).handles.discard(self)


class OwnedPublicationWorker:
    __slots__ = ('__weakref__',)

    def __reduce__(self) -> Any:
        raise TypeError('Owned workers cannot be serialized')
    def __init__(self, token: object, process: Any) -> None:
        if token is not _BOOT_TOKEN:
            raise InvalidRequest()
        _OWNED[self] = process

    def _process(self) -> Any:
        if type(self) is not OwnedPublicationWorker or self not in _OWNED:
            raise InvalidRequest()
        process = _OWNED[self]
        if process.returncode is not None:
            raise ProviderUnavailable()
        return process

    async def pause(self, *, deadline: float) -> None:
        process = self._process()
        process.send_signal(signal.SIGSTOP)
        while True:
            deadline_value(deadline)
            probe = await asyncio.create_subprocess_exec('/bin/ps', '-o', 'stat=', '-p', str(process.pid),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env={'PATH': '/usr/bin:/bin'})
            try:
                async with asyncio.timeout_at(deadline):
                    output, _ = await probe.communicate()
            finally:
                if probe.returncode is None:
                    probe.kill()
                    async with asyncio.timeout(1):
                        await probe.wait()
            if probe.returncode == 0 and len(output) <= 128 and output.strip().startswith(b'T'):
                return
            self._process()
            await asyncio.sleep(.01)

    async def resume(self, *, deadline: float) -> None:
        deadline_value(deadline)
        self._process().send_signal(signal.SIGCONT)

    async def terminate(self, *, deadline: float) -> None:
        process = self._process()
        process.kill()
        async with asyncio.timeout_at(deadline_value(deadline)):
            await process.wait()
        if process.returncode is None:
            raise ProviderUnavailable()
        _OWNED.pop(self, None)


def _host_state(value: Any) -> Any:
    if type(value) is not ManagedQdrantPublicationWorkerHost or value not in _HOSTS:
        raise InvalidRequest()
    return _HOSTS[value]


class ManagedQdrantPublicationWorkerHost:
    __slots__ = ('__weakref__',)

    def __reduce__(self) -> Any:
        raise TypeError('Worker hosts cannot be serialized')
    def __init__(self, supervisor: ManagedQdrantSupervisor, authorize_write: Any) -> None:
        if type(supervisor) is not ManagedQdrantSupervisor or not callable(authorize_write):
            raise InvalidRequest()
        _HOSTS[self] = SimpleNamespace(supervisor=supervisor, authorize_write=authorize_write,
            active=None, closed=False, poisoned=False, process=None, channel=None, owned=None,
            held=None, callback=None, attempts={}, bindings={}, cleanup_lock=asyncio.Lock())

    async def _cleanup(self) -> None:
        state = _host_state(self)
        async with state.cleanup_lock:
            try:
                if state.process is not None and state.process.returncode is None:
                    state.process.kill()
                    async with asyncio.timeout(3):
                        await state.process.wait()
                if state.process is not None and state.process.returncode is None:
                    raise ProviderUnavailable()
                if state.callback is not None and not state.callback.done():
                    state.callback.cancel()
                    async with asyncio.timeout(1):
                        await asyncio.shield(state.callback)
            except asyncio.CancelledError:
                if (state.process is not None and state.process.returncode is None
                        or state.callback is not None and not state.callback.done()):
                    state.poisoned = True
                    _POISONED.add(self)
                    raise ProviderUnavailable() from None
            except BaseException:
                state.poisoned = True
                _POISONED.add(self)
                raise ProviderUnavailable() from None
            try:
                if state.held is not None:
                    held = state.held
                    await held.__aexit__(None, None, None)
                    state.held = None
                if state.channel is not None:
                    await state.channel.close()
                if state.owned is not None:
                    _OWNED.pop(state.owned, None)
                state.attempts.clear()
                state.bindings.clear()
                state.poisoned = False
                _POISONED.discard(self)
            except asyncio.CancelledError:
                state.poisoned = True
                _POISONED.add(self)
                raise
            except Exception:
                state.poisoned = True
                _POISONED.add(self)
                raise ProviderUnavailable() from None

    async def publish(self, job: Any, ledger: ExecutionLedger, *, deadline: float, observer: Any = None) -> Any:
        state = _host_state(self)
        if type(ledger) is not ExecutionLedger or observer is not None and not callable(observer):
            raise InvalidRequest()
        job = _job(job)
        deadline = min(deadline_value(deadline), ledger.deadline)
        if state.closed or state.poisoned or state.active is not None:
            raise ProviderUnavailable()
        identity = _identity(dict(state.supervisor.profile_binding(job['config'])))
        reservation = ledger.reserve(attempts=1)
        ledger.dispatch(reservation)
        success = False
        state.active = asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                result = await self._publish(job, identity, deadline, observer)
            await self._cleanup()
            ledger.reconcile(reservation)
            success = True
            return result
        except TimeoutError:
            raise DeadlineExceeded() from None
        except _TerminalFailure as error:
            _raise(error.code)
        except asyncio.CancelledError:
            raise
        except (InvalidRequest, IntegrityViolation, UnauthorizedScope, UnsupportedCapability, ProviderUnavailable, DeadlineExceeded, BudgetExhausted):
            raise
        except Exception:
            raise ProviderUnavailable() from None
        finally:
            try:
                await self._cleanup()
            finally:
                if not success:
                    ledger.abandon(reservation)
                state.active = None

    async def _publish(self, job: Any, identity: Any, deadline: float, observer: Any) -> Any:
        state = _host_state(self)
        parent, child = socket.socketpair()
        child.set_inheritable(True)
        try:
            environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL') if key in os.environ}
            state.process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-m', 'cragkit._qdrant_publication_worker', str(child.fileno()),
                pass_fds=(child.fileno(),), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=environment, close_fds=True)
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        state.owned = OwnedPublicationWorker(_BOOT_TOKEN, state.process)
        reader, writer = await asyncio.open_connection(sock=parent)
        state.channel = _Channel(reader, writer)
        remaining = max(1, int((deadline - asyncio.get_running_loop().time()) * 1000))
        await _send_boot(state.channel, dict(v=1, job=job, identity=identity, remaining_ms=remaining), deadline)
        sequence = barriers = observations = 0
        finalized = False
        written: set[int] = set()
        observed: set[int] = set()
        async def callback(function: Any, *args: Any) -> Any:
            pending = function(*args)
            if not inspect.isawaitable(pending):
                raise InvalidRequest()
            async def invoke() -> Any:
                return await pending
            state.callback = asyncio.create_task(invoke())
            return await asyncio.shield(state.callback)
        def fresh() -> None:
            if _identity(dict(state.supervisor.profile_binding(job['config']))) != identity:
                raise ProviderUnavailable()
        def attempt(data: Any) -> tuple[Any, Any]:
            index = _integer(data['attempt_id'], 1, 8)
            if index not in state.attempts:
                raise InvalidRequest()
            selected = state.attempts[index]
            binding = dict(state.supervisor.attempt_binding(selected))
            if binding != state.bindings[index]:
                raise ProviderUnavailable()
            if any(binding[key] != identity[key] for key in ('instance_id', 'storage_identity', 'supervisor_id', 'epoch', 'credential_generation')):
                raise ProviderUnavailable()
            return selected, binding
        while sequence < 128:
            request = _object(await state.channel.receive(deadline), {'v', 'id', 'op', 'remaining_ms', 'data'})
            sequence += 1
            if type(request['v']) is not int or request['v'] != 1 or type(request['id']) is not int or request['id'] != sequence:
                raise InvalidRequest()
            remaining = _integer(request['remaining_ms'], 1, 9007199254740991)
            end = min(deadline, asyncio.get_running_loop().time() + remaining / 1000)
            op, data = request['op'], request['data']
            result: Any = {}
            try:
                async with asyncio.timeout_at(end):
                    if op not in ('write_observed', 'done', 'finalize_end'):
                        fresh()
                    if state.held is not None and op not in ('authorize', 'validate', 'finalize_end'):
                        raise InvalidRequest()
                    if op == 'profile':
                        _object(data, {'config_sha256'})
                        if data['config_sha256'] != _digest(job['config']):
                            raise InvalidRequest()
                        result = _identity(dict(state.supervisor.profile_binding(job['config'])))
                    elif op == 'authorize':
                        _object(data, {'reference', 'scope_sha256'})
                        if data['reference'] != job['reference'] or data['scope_sha256'] != _digest(job['scope']):
                            raise UnauthorizedScope()
                        allowed = await callback(state.authorize_write, parse_model(TrustedScope, job['scope']), job['reference']['collection'], job['reference']['document_id'])
                        fresh()
                        if type(allowed) is not bool:
                            raise InvalidRequest()
                        result = dict(allowed=allowed)
                    elif op == 'issue':
                        _object(data, {'intent_id', 'owner_token', 'epoch', 'dispatch_id'})
                        if len(state.attempts) >= 8 or data['intent_id'] != job['reference']['intent_id'] or data['epoch'] != identity['epoch']:
                            raise InvalidRequest()
                        selected = state.supervisor.issue_attempt(data, deadline=end)
                        binding = dict(state.supervisor.attempt_binding(selected))
                        credential: dict[str, Any] = {}
                        async def sink(value: Any) -> None:
                            credential.update(value)
                        await state.supervisor.deliver_worker_credential(selected, sink, deadline=end)
                        index = len(state.attempts) + 1
                        state.attempts[index] = selected
                        state.bindings[index] = binding
                        result = dict(attempt_id=index, binding=binding, endpoint=credential['endpoint'], api_key=credential['api_key'])
                    elif op == 'validate':
                        _object(data, {'attempt_id'})
                        _, binding = attempt(data)
                        result = dict(binding=binding)
                    elif op == 'before_write':
                        _object(data, {'attempt_id', 'dispatch_id', 'sequence', 'request_sha256'})
                        _, binding = attempt(data)
                        index = data['attempt_id']
                        if barriers >= 8 or index in written or data['dispatch_id'] != binding['dispatch_id']:
                            raise InvalidRequest()
                        _integer(data['sequence'], 1, 256)
                        if type(data['request_sha256']) is not str or len(data['request_sha256']) != 64 or any(ch not in '0123456789abcdef' for ch in data['request_sha256']):
                            raise InvalidRequest()
                        barriers += 1
                        written.add(index)
                        if observer is not None:
                            await callback(observer, dict(kind=op, **data), state.owned)
                    elif op == 'write_observed':
                        _object(data, {'attempt_id', 'dispatch_id', 'status'})
                        index = _integer(data['attempt_id'], 1, 8)
                        if index not in written or index in observed or observations >= 8:
                            raise InvalidRequest()
                        # This diagnostic remains admissible after retirement. Never validates or refreshes a key.
                        selected = state.attempts[index]
                        if data['dispatch_id'] != state.bindings[index]['dispatch_id']:
                            raise InvalidRequest()
                        _integer(data['status'], 100, 599)
                        observations += 1
                        observed.add(index)
                        if observer is not None:
                            await callback(observer, dict(kind=op, **data), state.owned)
                    elif op == 'finalize_begin':
                        _object(data, {'attempt_id'})
                        if finalized or state.held is not None:
                            raise InvalidRequest()
                        selected, _ = attempt(data)
                        held = state.supervisor.control_session()
                        await held.__aenter__()
                        state.held = held
                        attempt(data)
                        finalized = True
                    elif op == 'finalize_end':
                        _object(data, set())
                        if state.held is None or state.callback is not None and not state.callback.done():
                            raise InvalidRequest()
                        await state.held.__aexit__(None, None, None)
                        state.held = None
                    elif op == 'done':
                        _object(data, {'result', 'error', 'cleanup'})
                        if state.held is not None or type(data['cleanup']) is not list or len(data['cleanup']) > 64 or any(item not in _CODES for item in data['cleanup']):
                            raise InvalidRequest()
                        if (data['result'] is None) == (data['error'] is None):
                            raise InvalidRequest()
                        if data['error'] is not None and data['error'] not in _CODES:
                            raise InvalidRequest()
                        if data['result'] is not None:
                            _public_result(data['result'], job['reference']['intent_id'])
                        await state.channel.send(dict(v=1, id=sequence, ok=True, data={}), end)
                        async with asyncio.timeout_at(deadline):
                            await state.process.wait()
                        if state.process.returncode != 0 or data['cleanup']:
                            raise _TerminalFailure('ProviderUnavailable')
                        if data['error'] is not None:
                            raise _TerminalFailure(data['error'])
                        return data['result']
                    else:
                        raise InvalidRequest()
                await state.channel.send(dict(v=1, id=sequence, ok=True, data=result), end)
            except (InvalidRequest, UnauthorizedScope, ProviderUnavailable, UnsupportedCapability, DeadlineExceeded) as error:
                await state.channel.send(dict(v=1, id=sequence, ok=False, error=_code(error)), deadline)
                raise
        raise ProviderUnavailable()

    async def close(self) -> None:
        state = _host_state(self)
        state.closed = True
        active = state.active
        if active is not None and active is not asyncio.current_task():
            active.cancel()
            try:
                async with asyncio.timeout(5):
                    await asyncio.shield(active)
            except asyncio.CancelledError:
                if not active.done():
                    raise ProviderUnavailable() from None
            except Exception:
                if not active.done():
                    raise ProviderUnavailable() from None
        await self._cleanup()


def _public_result(value: Any, intent_id: str) -> Any:
    _object(value, {'intent_id', 'operation', 'state', 'revision_id', 'generation_id',
        'authority_committed', 'replica_complete', 'published', 'purge_complete'})
    if value['intent_id'] != intent_id or value['operation'] != 'publish' or value['state'] not in ('published', 'conflict', 'denied'):
        raise InvalidRequest()
    for key in ('revision_id', 'generation_id'):
        if type(value[key]) is not str or not 1 <= len(value[key].encode('utf-8')) <= 256:
            raise InvalidRequest()
    if any(type(value[key]) is not bool for key in ('authority_committed', 'replica_complete', 'published', 'purge_complete')):
        raise InvalidRequest()
    if value['published'] != (value['state'] == 'published'):
        raise InvalidRequest()
    return value


async def _child(fd: int) -> None:
    channel: _Channel | None = None
    controller: OrdinaryWorkerController | None = None
    resource = writer = manager = transport = None
    result = None
    error = None
    cleanup: list[str] = []
    deadline = asyncio.get_running_loop().time() + 30
    try:
        connection = socket.socket(fileno=fd)
        connection.set_inheritable(False)
        reader, stream = await asyncio.open_connection(sock=connection)
        channel = _Channel(reader, stream)
        boot = _object(await _read_boot(channel, deadline), {'v', 'job', 'identity', 'remaining_ms'})
        if type(boot['v']) is not int or boot['v'] != 1:
            raise InvalidRequest()
        deadline = asyncio.get_running_loop().time() + _integer(boot['remaining_ms'], 1, 9007199254740991) / 1000
        job, identity = _job(boot['job']), _identity(boot['identity'])
        controller = OrdinaryWorkerController(_BOOT_TOKEN, channel, job, identity, deadline)
        from ._postgres_pool import PoolConfig, PoolResource
        from ._qdrant_writer import PostgresQdrantWriter
        from .qdrant_publication import (QdrantPublicationManager, PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport)
        pool = dict(job['writer_pool'])
        for key in ('sslrootcert', 'passfile'):
            pool[key] = Path(pool[key])
        resource = PoolResource(PoolConfig.model_validate(pool))
        writer = PostgresQdrantWriter(resource, job['config'], identity['instance_id'])
        authority = PostgresQdrantPublicationAuthority(writer, None)
        transport = ManagedQdrantPublicationTransport(controller)
        manager = QdrantPublicationManager(authority, transport, job['config'], controller, controller.authorize)
        await resource.open()
        await manager.initialize(deadline=deadline)
        result = dict(await manager.publish(job['reference'], job['scope'], ExecutionLedger(job['limits'], deadline=deadline), deadline=deadline))
    except BaseException as failure:
        error = _code(failure)
    finally:
        end = asyncio.get_running_loop().time() + 8
        for item in (manager, transport, controller, writer, resource):
            if item is not None:
                try:
                    async with asyncio.timeout_at(end):
                        await item.close()
                except BaseException as failure:
                    cleanup.append(_code(failure))
        if cleanup:
            result, error = None, 'ProviderUnavailable'
        if channel is not None:
            try:
                await channel.rpc('done', dict(result=result, error=error, cleanup=cleanup), min(end, deadline))
            finally:
                await channel.close()


def _entry() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].isdecimal():
        raise SystemExit(2)
    try:
        asyncio.run(_child(int(sys.argv[1])))
    except BaseException:
        raise SystemExit(1) from None


if __name__ == '__main__':
    # Always mint controllers in the canonical imported module, never the __main__ duplicate.
    from importlib import import_module
    import_module('cragkit._qdrant_publication_worker')._entry()
