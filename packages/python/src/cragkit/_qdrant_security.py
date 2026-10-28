"""Independent, borrowed-writer admission for authoritative security changes."""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

from ._qdrant_transport import deadline_value
from ._qdrant_manifest import _Security, _parse, _snapshot, encode_security_intent
from ._qdrant_writer import PostgresQdrantWriter, writer_binding
from ._qdrant_writer_contract import context
from .contracts import TrustedScope
from .errors import (DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
                     ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from .execution import BudgetExhausted, ExecutionLedger

_CLEANUP_SECONDS = 1.0


def _safe(error: Exception) -> Exception:
    for kind in (BudgetExhausted, DeadlineExceeded, IndexNotReady, IntegrityViolation,
                 InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability):
        if type(error) is kind:
            return kind()
    return ProviderUnavailable()


class QdrantSecurityManager:
    def __init__(self, writer: PostgresQdrantWriter,
                 authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]]) -> None:
        writer_binding(writer)
        if not callable(authorize_write):
            raise InvalidRequest()
        self._writer = writer
        self._authorize_write = authorize_write
        self._ready = False
        self._closed = False
        self._cancelled = False
        self._active: asyncio.Task[Any] | None = None

    def _check(self, deadline: float) -> None:
        if self._cancelled:
            raise asyncio.CancelledError()
        deadline_value(deadline)

    async def _run(self, body: Callable[[float], Awaitable[Any]], *, deadline: float,
                   ledger: ExecutionLedger | None = None, initializing: bool = False) -> Any:
        deadline = deadline_value(deadline)
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        if not initializing and not self._ready:
            raise IndexNotReady()
        if ledger is not None:
            if type(ledger) is not ExecutionLedger:
                raise InvalidRequest()
            deadline = min(deadline, ledger.deadline)
        deadline_value(deadline)
        self._cancelled = False

        async def work() -> Any:
            reservation = None
            completed = False
            try:
                if ledger is not None:
                    reservation = ledger.reserve(attempts=1)
                    ledger.dispatch(reservation)
                self._check(deadline)
                result = await body(deadline)
                self._check(deadline)
                if ledger is not None:
                    ledger.reconcile(reservation)
                    completed = True
                return result
            finally:
                if ledger is not None and reservation is not None and not completed:
                    ledger.abandon(reservation)

        task = asyncio.create_task(work())
        self._active = task
        def finished(done: asyncio.Task[Any]) -> None:
            if self._active is done:
                self._active = None
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        except (asyncio.CancelledError, TimeoutError) as error:
            self._cancelled = True
            task.cancel()
            try:
                async with asyncio.timeout(_CLEANUP_SECONDS):
                    await asyncio.shield(task)
            except BaseException:
                if not task.done():
                    self._closed = True
            if isinstance(error, asyncio.CancelledError):
                raise
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            if task.done() and self._active is task:
                self._active = None

    async def initialize(self, *, deadline: float) -> None:
        async def initialize(limit: float) -> None:
            await self._writer.initialize(deadline=limit)
            self._check(limit)
            self._ready = True
        await self._run(initialize, deadline=deadline, initializing=True)

    async def _security(self, change: object, scope: object, ledger: ExecutionLedger, *,
                        action: str, deadline: float) -> Mapping[str, Any]:
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        record = _snapshot(change)
        encode_security_intent(record)
        intent = _parse(_Security, record)
        if intent.action != action:
            raise InvalidRequest()
        ctx = context(dict(scope=scope,collection=intent.collection,document_id=intent.document_id,
                           intent_id=intent.intent_id,owner_token=str(uuid4())))
        if ctx.scope.tenant_id != intent.tenant_id:
            raise UnauthorizedScope()

        async def apply(limit: float) -> Mapping[str, Any]:
            self._check(limit)
            try:
                pending = self._authorize_write(ctx.scope,ctx.collection,ctx.document_id)
                if not inspect.isawaitable(pending):
                    raise InvalidRequest()
                allowed = await pending
            except asyncio.CancelledError:
                raise
            except InvalidRequest:
                raise InvalidRequest() from None
            except Exception:
                raise ProviderUnavailable() from None
            self._check(limit)
            if type(allowed) is not bool:
                raise InvalidRequest()
            if not allowed:
                raise UnauthorizedScope()
            result = await self._writer.apply_security(record,ctx.scope,owner_token=ctx.owner_token,deadline=limit)
            self._check(limit)
            return MappingProxyType(dict(intent_id=ctx.intent_id,operation=action,state=result['state'],
                revision_id=result['revision_id'],generation_id=result['generation_id'],
                authority_committed=result['authority_committed'],replica_complete=result['replica_complete'],
                published=result['state']=='published',purge_complete=result['purge_complete']))
        return cast(Mapping[str, Any], await self._run(apply,deadline=deadline,ledger=ledger))

    async def update_authorization(self, change: object, scope: object, ledger: ExecutionLedger, *,
                                   deadline: float) -> Mapping[str, Any]:
        return await self._security(change,scope,ledger,action='update_authorization',deadline=deadline)

    async def tombstone(self, change: object, scope: object, ledger: ExecutionLedger, *,
                        deadline: float) -> Mapping[str, Any]:
        return await self._security(change,scope,ledger,action='tombstone',deadline=deadline)

    async def close(self) -> None:
        self._closed = True
        self._cancelled = True
        active = self._active
        if active is not None:
            active.cancel()
            try:
                async with asyncio.timeout(_CLEANUP_SECONDS):
                    await asyncio.shield(active)
            except asyncio.CancelledError:
                if not active.done():
                    raise
            except Exception:
                raise ProviderUnavailable() from None
