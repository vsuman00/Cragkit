"""QS-r1 source-only reader with private request-bound release capabilities."""
from __future__ import annotations

import asyncio
from types import MappingProxyType
from typing import Any, Mapping

from ._postgres_pool import PoolResource
from ._qdrant_authority import PostgresQdrantAuthority, compile_filters
from ._qdrant_contract import QdrantConfig, SPARSE_PROFILE, parse_model
from ._qdrant_source import (MAX_SOURCE_BYTES, SourceFetch, PrivateSource, source_limit,
                             metadata_guard, validate_nomination, verify_source)
from ._qdrant_transport import deadline_value
from .contracts import RetrievalRequest, TrustedScope
from .embeddings import FAKE_PROFILE, OPENAI_PROFILE
from .errors import (CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
                     ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)


def _safe(error: Exception) -> CragkitError:
    for kind in (DeadlineExceeded, IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability):
        if type(error) is kind:
            return kind()
    return ProviderUnavailable()


class PostgresQdrantSourceStore:
    def __init__(self, resource: PoolResource, config: object) -> None:
        if type(resource) is not PoolResource:
            raise InvalidRequest()
        metadata_guard(config)
        self._config: QdrantConfig = parse_model(QdrantConfig, config)
        selected = self.config.dense_profile.model_dump()
        if (selected not in (FAKE_PROFILE.model_dump(), OPENAI_PROFILE.model_dump()) or
            self.config.sparse_profile is not None and
            (self.config.sparse_profile != SPARSE_PROFILE or selected != FAKE_PROFILE.model_dump())):
            raise UnsupportedCapability()
        self._authority = PostgresQdrantAuthority(resource)
        self._closed = False
        self._ready = False
        self._initializing = False
        self._initializing_task: asyncio.Task[Any] | None = None
        self._handle: SourceRequest | None = None

    def __repr__(self) -> str:
        return 'PostgresQdrantSourceStore()'

    @property
    def config(self) -> QdrantConfig:
        return self._config

    def capabilities(self) -> Mapping[str, bool]:
        return MappingProxyType({'source_authority': True, 'candidate_replica_only': False,
                                 'qd_r1_compatible': False, 'publication': False, 'repair': False})

    async def initialize(self, *, deadline: float) -> None:
        end = deadline_value(deadline)
        if self._closed:
            raise InvalidRequest()
        if self._initializing or self._handle is not None:
            raise ProviderUnavailable()
        self._initializing = True
        self._initializing_task = asyncio.current_task()
        self._ready = False
        try:
            async with asyncio.timeout_at(end):
                await self._authority.initialize(deadline=end)
                deadline_value(end)
                if self._closed:
                    raise InvalidRequest()
                self._ready = True
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            self._initializing = False
            self._initializing_task = None

    def open_request(self, request: object, *, scope: object, deadline: float) -> SourceRequest:
        entered = asyncio.get_running_loop().time()
        req: RetrievalRequest = parse_model(RetrievalRequest, request)
        trusted: TrustedScope = parse_model(TrustedScope, scope)
        end = min(deadline_value(deadline), entered + req.limits.deadline_ms / 1000)
        compile_filters(req)
        if self._closed:
            raise InvalidRequest()
        if not self._ready:
            raise IndexNotReady()
        if self._handle is not None or self._initializing:
            raise ProviderUnavailable()
        handle = SourceRequest(self, req, trusted, end)
        self._handle = handle
        return handle

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._ready = False
        initial = self._initializing_task
        if initial is not None and initial is not asyncio.current_task():
            initial.cancel()
            _, pending = await asyncio.wait({initial}, timeout=1)
            for task in pending:
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        if self._handle is not None:
            await self._handle.close()


class SourceRequest:
    """Private-state handle; no public binding constructor or serialized capability."""
    def __init__(self, store: PostgresQdrantSourceStore, request: RetrievalRequest,
                 scope: TrustedScope, deadline: float) -> None:
        self._store, self._request, self._scope = store, request, scope
        self._deadline = deadline
        self._closed = False
        self._active: asyncio.Task[Any] | None = None
        self._pending: set[asyncio.Task[Any]] = set()
        self._bindings: dict[object, dict[str, Any]] = {}
        self._fetches = 0
        self._source_bytes = 0

    def __repr__(self) -> str:
        return 'SourceRequest()'

    def _check(self) -> None:
        if self._closed or self._store._closed or self._store._handle is not self:
            raise InvalidRequest()
        deadline_value(self._deadline)
        if self._active is not None or self._pending:
            raise ProviderUnavailable()

    async def _read(self, nomination: Any, *, retained: bool, max_source_bytes: int,
                    include_source: bool, provenance: dict[str, str] | None = None) -> tuple[SourceFetch, list[dict[str, Any]]]:
        self._active = asyncio.current_task()
        task = asyncio.create_task(self._store._authority.read(nomination,self._request,self._scope,self._store.config,
            retained=retained,max_source_bytes=max_source_bytes,deadline=self._deadline))
        self._pending.add(task)
        def done(finished: asyncio.Task[Any]) -> None:
            self._pending.discard(finished)
            if not finished.cancelled():
                finished.exception()
        task.add_done_callback(done)
        try:
            completed, _ = await asyncio.wait({task}, timeout=max(0,self._deadline-asyncio.get_running_loop().time()))
            if not completed:
                task.cancel()
                self._closed = True
                raise DeadlineExceeded()
            rows = task.result()
            self._pending.discard(task)
            deadline_value(self._deadline)
            if self._closed:
                raise InvalidRequest()
            # Charge actual returned canonical buffers before validation, including corruption.
            loaded = 0
            if type(rows) is list:
                for row in rows:
                    if type(row) is dict and type(row.get('canonical_utf8')) in (bytes,bytearray,memoryview):
                        buffer = row['canonical_utf8']
                        loaded += buffer.nbytes if type(buffer) is memoryview else len(buffer)
            self._source_bytes += loaded
            if self._source_bytes > MAX_SOURCE_BYTES or loaded > max_source_bytes:
                self._closed = True
                raise IntegrityViolation()
            result = verify_source(nomination,rows,self._request,self._scope,self._store.config,retained=retained,
                max_source_bytes=max_source_bytes,include_source=include_source,bound_provenance=provenance)
            deadline_value(self._deadline)
            return result, rows
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception as error:
            raise _safe(error) from None
        finally:
            self._active = None

    async def fetch_candidate(self, nomination: object, *, max_source_bytes: int,
                              include_source: bool = False) -> SourceFetch:
        self._check()
        allowance = min(source_limit(max_source_bytes), MAX_SOURCE_BYTES - self._source_bytes)
        if type(include_source) is not bool:
            raise InvalidRequest()
        nom = validate_nomination(nomination,self._request,self._scope,self._store.config)
        if self._fetches >= 64 or len(self._bindings) >= 64:
            return SourceFetch(state='budget_exhausted')
        self._fetches += 1
        result, rows = await self._read(nom,retained=False,max_source_bytes=allowance,include_source=include_source)
        if result.state != 'verified':
            return result
        token = object()
        self._bindings[token] = {'nomination':nom,'provenance':{key:rows[0][key] for key in ('parser_id','chunker_profile','source_locator')},'purposes':set()}
        return result.model_copy(update={'binding':token})

    async def release(self, binding: object, *, purpose: str, max_source_bytes: int,
                      include_source: bool = False) -> SourceFetch:
        self._check()
        allowance = min(source_limit(max_source_bytes), MAX_SOURCE_BYTES - self._source_bytes)
        if type(include_source) is not bool or type(purpose) is not str or purpose not in ('provider','final'):
            raise InvalidRequest()
        if type(binding) is not object or binding not in self._bindings:
            raise InvalidRequest()
        record = self._bindings[binding]
        purposes = record['purposes']
        if purpose in purposes or purpose == 'provider' and 'final' in purposes or len(purposes) >= 2:
            raise InvalidRequest()
        purposes.add(purpose)
        result, _ = await self._read(record['nomination'],retained=True,max_source_bytes=allowance,
                                    include_source=include_source,provenance=record['provenance'])
        return result.model_copy(update={'binding':binding}) if result.state == 'verified' else result

    async def close(self) -> None:
        self._closed = True
        self._bindings.clear()
        tasks = set(self._pending)
        if self._active is not None and self._active is not asyncio.current_task():
            tasks.add(self._active)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=1)
            for task in pending:
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        if self._store._handle is self:
            self._store._handle = None


__all__ = ['PostgresQdrantSourceStore', 'SourceFetch', 'PrivateSource']
