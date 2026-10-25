"""Optional native Qdrant candidate nominations; no source release or provider calls."""
from __future__ import annotations

import asyncio
import json
import math
from types import MappingProxyType
from typing import Any, Literal, Mapping, Protocol

from ._qdrant_contract import (
    CandidatePayload, PAYLOAD_FIELDS, QdrantConfig, QdrantNomination, SPARSE_PROFILE,
    SparseProfile, compile_filter, decode_response, dense_vector, identity_tuple, matches,
    parse_model, point_id, snapshot, sparse_vector,
)
from ._qdrant_transport import HttpxQdrantTransport, deadline_value, safe_transport_error
from .contracts import RetrievalRequest, TrustedScope
from .embeddings import FAKE_PROFILE
from .errors import (
    CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
    ProviderUnavailable, UnsupportedCapability,
)
from .execution import ExecutionLedger


class QdrantTransport(Protocol):
    bounded_responses: bool
    cancellation_safe: bool

    async def request(self, method: str, path: str, *, body: bytes | None = None,
                      deadline: float, max_response_bytes: int = 1048576) -> bytes: ...


class QdrantSearchStore:
    """Single-operation, replica-only candidate boundary borrowing its transport.

    Close rejects new work and cancels active work with a one-second drain bound.
    It never closes the injected transport. A transport that ignores cancellation
    remains the application's responsibility and cannot start a subsequent branch.
    """
    def __init__(self, config: object, transport: QdrantTransport) -> None:
        self._config: QdrantConfig = parse_model(QdrantConfig, config)
        if (self._config.dense_profile.model_dump() != FAKE_PROFILE.model_dump() or
                self._config.sparse_profile is not None and self._config.sparse_profile != SPARSE_PROFILE):
            raise UnsupportedCapability()
        if (getattr(transport, 'bounded_responses', None) is not True or
                getattr(transport, 'cancellation_safe', None) is not True or
                not callable(getattr(transport, 'request', None))):
            raise UnsupportedCapability()
        self._transport = transport
        self._initialized = False
        self._closed = False
        self._active: asyncio.Task[Any] | None = None
        self._pending: set[asyncio.Task[Any]] = set()

    def __repr__(self) -> str:
        return 'QdrantSearchStore()'

    @property
    def config(self) -> QdrantConfig:
        return self._config

    def capabilities(self) -> Mapping[str, object]:
        return MappingProxyType({'candidate_replica_only': True, 'source_authority': False,
                                 'qd_r1_compatible': False, 'dense': True,
                                 'sparse': self._config.sparse_profile is not None,
                                 'native_fusion': False, 'identifier': False,
                                 'publication': False, 'filters': ('eq', 'in', 'and', 'or')})

    def _admit(self) -> None:
        if self._closed:
            raise InvalidRequest()
        if self._active is not None or self._pending:
            raise ProviderUnavailable()
        self._active = asyncio.current_task()

    async def _request(self, method: str, path: str, deadline: float,
                       body: bytes | None = None) -> Any:
        deadline_value(deadline)
        if self._closed:
            raise InvalidRequest()
        task = asyncio.create_task(self._transport.request(method, path, body=body,
                                   deadline=deadline, max_response_bytes=1048576))
        self._pending.add(task)
        def settled(done: asyncio.Task[Any]) -> None:
            self._pending.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(settled)
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
            if not done:
                task.cancel()
                raise DeadlineExceeded()
            self._pending.discard(task)
            raw = task.result()
            value = decode_response(raw)
            deadline_value(deadline)
            if self._closed:
                raise InvalidRequest()
            return value
        except asyncio.CancelledError:
            task.cancel()
            raise
        except CragkitError as error:
            raise safe_transport_error(error) from None
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception:
            raise ProviderUnavailable() from None

    async def initialize(self, *, deadline: float) -> None:
        end = deadline_value(deadline)
        self._admit()
        self._initialized = False
        try:
            root = await self._request('GET', '/', end)
            if type(root) is not dict or type(root.get('version')) is not str:
                raise IntegrityViolation()
            if root['version'] != '1.20.0':
                raise UnsupportedCapability()
            cluster = await self._request('GET', '/cluster', end)
            result = self._result(cluster)
            if type(result) is not dict or result.get('status') != 'disabled':
                raise UnsupportedCapability()
            collection = await self._request('GET', '/collections/' + self._config.physical_collection, end)
            self._collection(self._result(collection))
            deadline_value(end)
            self._initialized = True
        finally:
            self._active = None

    @staticmethod
    def _result(value: Any) -> Any:
        if type(value) is not dict or value.get('status') != 'ok' or 'result' not in value:
            raise IntegrityViolation()
        return value['result']

    def _collection(self, value: Any) -> None:
        try:
            params = value['config']['params']
            vectors = params['vectors']
            dense = vectors['dense']
            if (type(value) is not dict or type(params) is not dict or type(vectors) is not dict
                    or set(vectors) != {'dense'} or type(dense) is not dict
                    or type(dense.get('size')) not in (int, float) or dense['size'] != 1536
                    or dense.get('distance') != 'Cosine' or dense.get('multivector_config') is not None
                    or type(params.get('replication_factor')) not in (int, float) or params['replication_factor'] != 1
                    or type(params.get('write_consistency_factor')) not in (int, float) or params['write_consistency_factor'] != 1):
                raise UnsupportedCapability()
            sparse = params.get('sparse_vectors')
            if self._config.sparse_profile is None:
                if sparse not in (None, {}):
                    raise UnsupportedCapability()
            elif (type(sparse) is not dict or set(sparse) != {'sparse'} or type(sparse['sparse']) is not dict
                  or sparse['sparse'].get('modifier') not in (None, 'none')):
                raise UnsupportedCapability()
        except (KeyError, TypeError, AttributeError):
            raise UnsupportedCapability() from None

    async def search_candidates(self, request: object, *, scope: object,
                                dense: object = None, sparse: object = None,
                                branch_limits: object, ledger: ExecutionLedger,
                                deadline: float) -> tuple[QdrantNomination, ...]:
        entry = asyncio.get_running_loop().time()
        req: RetrievalRequest = parse_model(RetrievalRequest, request)
        trusted: TrustedScope = parse_model(TrustedScope, scope)
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        end = min(deadline_value(deadline), ledger.deadline, entry + req.limits.deadline_ms / 1000)
        deadline_value(end)
        query_filter = compile_filter(req, trusted)
        queries: dict[str, Any] = {}
        if dense is not None:
            queries['dense'] = dense_vector(dense)
        if sparse is not None:
            if self._config.sparse_profile is None:
                raise UnsupportedCapability()
            queries['sparse'] = sparse_vector(sparse)
        if not queries:
            raise InvalidRequest()
        limits = snapshot(branch_limits)
        if type(limits) is not dict or set(limits) != set(queries):
            raise InvalidRequest()
        if any(type(value) is not int or not 1 <= value <= 64 for value in limits.values()):
            raise InvalidRequest()
        total = sum(limits.values())
        if total > min(64, req.limits.max_candidates):
            raise InvalidRequest()
        bodies: dict[str, bytes] = {}
        for branch, vector in queries.items():
            body = {'query': vector, 'using': branch, 'filter': query_filter, 'limit': limits[branch],
                    'with_payload': list(PAYLOAD_FIELDS), 'with_vector': False}
            encoded = json.dumps(body, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(encoded) > 262144:
                raise InvalidRequest()
            bodies[branch] = encoded
        if not self._initialized:
            raise IndexNotReady()
        self._admit()
        token: object | None = None
        try:
            token = ledger.reserve(candidates=total)
            ledger.dispatch(token)
            nominees: list[QdrantNomination] = []
            across: dict[str, dict[str, Any]] = {}
            branches: tuple[Literal['dense', 'sparse'], ...] = ('dense', 'sparse')
            for branch in branches:
                if branch not in bodies:
                    continue
                envelope = await self._request('POST', '/collections/' + self._config.physical_collection + '/points/query',
                                               end, bodies[branch])
                result = self._result(envelope)
                if type(result) is not dict or set(result) != {'points'} or type(result['points']) is not list:
                    raise IntegrityViolation()
                points = result['points']
                if len(points) > limits[branch]:
                    raise IntegrityViolation()
                seen: set[str] = set()
                chunks: set[tuple[str, ...]] = set()
                for raw in points:
                    nomination = self._nomination(raw, branch, req, trusted)
                    ident = identity_tuple(nomination.payload)
                    chunk = ident[4:10]
                    if nomination.point_id in seen or chunk in chunks:
                        raise IntegrityViolation()
                    seen.add(nomination.point_id)
                    chunks.add(chunk)
                    payload = nomination.payload.model_dump(mode='json', exclude_unset=True)
                    old = across.get(nomination.point_id)
                    if old is not None and old != payload:
                        raise IntegrityViolation()
                    across[nomination.point_id] = payload
                    nominees.append(nomination)
                deadline_value(end)
            ledger.reconcile(token)
            token = None
            return tuple(nominees)
        finally:
            if token is not None:
                ledger.abandon(token)
            self._active = None

    def _nomination(self, raw: Any, branch: Literal['dense', 'sparse'], req: RetrievalRequest,
                    scope: TrustedScope) -> QdrantNomination:
        try:
            if type(raw) is not dict or not {'id', 'score', 'payload'} <= set(raw):
                raise IntegrityViolation()
            # Qdrant may add harmless transport metadata, never unrequested source/vector data.
            if set(raw) - {'id', 'score', 'payload', 'version', 'order_value', 'shard_key'}:
                raise IntegrityViolation()
            if type(raw['id']) is not str or type(raw['score']) not in (int, float):
                raise IntegrityViolation()
            score = float(raw['score'])
            if not math.isfinite(score) or branch == 'dense' and not -1.000001 <= score <= 1.000001:
                raise IntegrityViolation()
            payload = CandidatePayload.model_validate(raw['payload'])
            cfg = self._config
            if (payload.backend_namespace != cfg.backend_namespace or payload.physical_collection != cfg.physical_collection
                    or payload.collection_incarnation != cfg.collection_incarnation
                    or payload.dense_profile != cfg.dense_profile or payload.sparse_profile != cfg.sparse_profile
                    or payload.dense_profile_id != cfg.dense_profile.profile_id
                    or payload.sparse_profile_id != (cfg.sparse_profile.profile_id if cfg.sparse_profile else '')
                    or payload.tenant_id != scope.tenant_id or payload.collection != req.collection
                    or not (scope.principal_id in payload.principal_ids or set(scope.grant_ids).intersection(payload.grant_ids))
                    or not matches(req.model_dump(mode='json')['required_filters'], raw['payload'])
                    or raw['id'] != point_id(identity_tuple(payload))):
                raise IntegrityViolation()
            return QdrantNomination(point_id=raw['id'], branch=branch, score=score,
                                     score_kind='cosine_similarity' if branch == 'dense' else 'dot_product',
                                     payload=payload)
        except (ValueError, TypeError, OverflowError, UnicodeError, InvalidRequest):
            raise IntegrityViolation() from None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._initialized = False
        active = self._active
        tasks = set(self._pending)
        if active is not None and active is not asyncio.current_task():
            tasks.add(active)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=1)
            for task in pending:
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())


__all__ = ['QdrantSearchStore', 'QdrantConfig', 'CandidatePayload', 'QdrantNomination',
           'SparseProfile', 'SPARSE_PROFILE', 'HttpxQdrantTransport', 'point_id', 'compile_filter']
