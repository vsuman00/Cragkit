"""Explicit gated, budgeted evaluation dispatch with durable replay evidence."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import math
import time

from evaluation_payloads import EvaluationPayloadError, EvaluationPayloadGate
from live_evaluation_budget import LiveBudgetError, LiveEvaluationBudget
from provider_adapters import ProviderAdapterError
from provider_http import HttpProviderSend
from provider_journal import EvaluationJournal
from provider_recordings import RecordingValidationError, request_metadata, validate_recording

_CLOSE_TIMEOUT = 2.0

_TRANSPORT_CODES = frozenset(('provider_http_auth_failed', 'provider_http_rate_limited',
    'provider_http_server_failed', 'provider_pacing_invalid', 'provider_pacing_failed'))

_SAFE_CODES = frozenset(('provider_http_invalid', 'provider_http_failed', 'provider_http_close_failed', 'deadline_exceeded',
    'concurrent_dispatch', 'provider_journal_invalid', 'provider_journal_failed',
    'provider_recording_invalid', 'unapproved_evaluation_payload', 'live_budget_invalid',
    'live_budget_closed', 'live_budget_pending', 'live_budget_exhausted',
    'live_budget_reservation_invalid', 'live_budget_usage_invalid', 'live_budget_overrun',
    'provider_recorded_invalid', 'provider_recorded_failed')) | _TRANSPORT_CODES
_SAFE_TYPES = (ProviderAdapterError, EvaluationPayloadError, LiveBudgetError, RecordingValidationError)


def _sanitized(error):
    if (type(error) in _SAFE_TYPES and len(error.args) == 1
            and type(error.args[0]) is str and error.args[0] in _SAFE_CODES):
        return type(error)(error.args[0])
    return ProviderAdapterError('provider_recorded_failed')


def _invalid():
    raise ProviderAdapterError('provider_recorded_invalid')


class RecordedProviderSend:
    """Own one fresh run; no retries, directory reuse or credential discovery."""
    def __init__(self, keys, gate, directory, *, counter=None, enabled=False, transport=None):
        if enabled is not True or type(gate) is not EvaluationPayloadGate or not isinstance(keys, Mapping):
            _invalid()
        if counter is not None:
            from cragkit.context import Cl100kCounter, _ISSUED
            if type(counter) is not Cl100kCounter or counter not in _ISSUED:
                _invalid()
        self._kind = 'mock' if transport is not None else 'live'
        failure = None
        try:
            configured_keys = dict(keys)
            self._http = HttpProviderSend(configured_keys, transport=transport)
            self._providers = frozenset(configured_keys)
            self._journal = EvaluationJournal(directory, evidence_kind=self._kind)
        except Exception as error:
            failure = _sanitized(error)
        if failure is not None:
            raise failure
        self._gate, self._counter = gate, counter
        self._budget = LiveEvaluationBudget()
        self._entered = self._closed = self._failed = self._inflight = False
        self._cleanup_verified = False

    async def __aenter__(self):
        if self._entered or self._closed or self._failed:
            _invalid()
        failure, cancelled = None, None
        try:
            self._journal.__enter__()
            await self._http.__aenter__()
            self._entered = True
        except asyncio.CancelledError as error:
            cancelled = error
        except Exception as error:
            failure = _sanitized(error)
        if failure is not None or cancelled is not None:
            self._failed = True
            self._mark_failure(None, False, 'journal_failed')
            _, close_cancelled = await self._close_owned()
            if cancelled is None:
                cancelled = close_cancelled
            if cancelled is not None:
                raise cancelled
            raise failure
        return self

    def _mark_failure(self, ticket, completed, code):
        try:
            if ticket is not None and not completed:
                self._journal.uncertain(ticket, code)
            else:
                self._journal.fail(code)
        except Exception:
            # The original pending record remains unreplayable on failed writes.
            pass

    async def _close_owned(self, *, finalize=False):
        self._closed = True
        failure, cancelled = None, None
        task = asyncio.create_task(self._http.aclose())
        end = asyncio.get_running_loop().time() + _CLOSE_TIMEOUT
        while not task.done():
            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                done, _ = await asyncio.wait((task,), timeout=remaining)
                if done:
                    break
            except asyncio.CancelledError as error:
                cancelled = cancelled or error
        if task.done():
            if task.cancelled():
                failure = ProviderAdapterError('provider_recorded_failed')
            else:
                try:
                    task.result()
                except Exception as error:
                    failure = _sanitized(error)
        else:
            # Do not await a cancellation-resistant close beyond its allowance.
            def observe_late_close(completed):
                if not completed.cancelled():
                    completed.exception()
            task.add_done_callback(observe_late_close)
            task.cancel()
            failure = ProviderAdapterError('provider_recorded_failed')
        if failure is not None or cancelled is not None:
            self._failed = True
            self._mark_failure(None, False, 'cancelled' if cancelled else 'journal_failed')
        if finalize and not self._failed:
            try:
                self._journal.finish()
            except Exception as error:
                self._failed = True
                failure = _sanitized(error)
        try:
            self._journal.__exit__(None, None, None)
        except Exception as error:
            self._failed = True
            failure = failure or _sanitized(error)
        self._cleanup_verified = failure is None and cancelled is None
        return failure, cancelled

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self._failed = True
            self._mark_failure(None, False, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'journal_failed')
        failure, cancelled = await self._close_owned(finalize=True)
        if exc_type is not None:
            return False
        if cancelled is not None:
            raise cancelled
        if failure is not None:
            raise failure
        return False

    async def __call__(self, request, *, deadline, max_response_bytes):
        if not self._entered or self._closed or self._failed:
            _invalid()
        if self._inflight:
            raise ProviderAdapterError('concurrent_dispatch')
        self._inflight = True
        try:
            return await self._send(request, deadline=deadline, max_response_bytes=max_response_bytes)
        finally:
            self._inflight = False

    async def _send(self, request, *, deadline, max_response_bytes):
        reservation = ticket = raw = metadata = None
        settlement_attempted = completed = False
        failure = cancelled = None
        stage = 'validation'
        try:
            if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                    or type(max_response_bytes) is not int or not 0 < max_response_bytes <= 2097152):
                _invalid()
            if time.monotonic() >= deadline:
                raise ProviderAdapterError('deadline_exceeded')
            metadata = request_metadata(request)
            if metadata['provider'] not in self._providers:
                _invalid()
            ceiling = self._gate.admission_ceiling(request, counter=self._counter)
            reservation = self._budget.begin(metadata['provider'], ceiling)
            stage = 'journal_begin'
            ticket = self._journal.begin(request, ceiling)
            stage = 'http'
            raw = await self._http(request, deadline=deadline, max_response_bytes=max_response_bytes)
            stage = 'journal_complete'
            reported = self._journal.complete(ticket, raw)
            completed = True
            stage = 'settle'
            settlement_attempted = True
            self._budget.settle(reservation, reported)
        except asyncio.CancelledError as error:
            cancelled = error
        except Exception as error:
            failure = _sanitized(error)
        if failure is None and cancelled is None:
            return raw
        self._failed = True
        overrun = stage == 'settle'
        if reservation is not None and not settlement_attempted:
            valid, reported = False, None
            if raw is not None:
                try:
                    reported = validate_recording(metadata['provider'], metadata['model'], raw,
                        expected_items=metadata['response_items'], max_response_bytes=max_response_bytes)
                    valid = True
                except Exception:
                    pass
            if valid:
                settlement_attempted = True
                try:
                    self._budget.settle(reservation, reported)
                except Exception:
                    overrun = True
            else:
                try:
                    self._budget.abort(reservation)
                except Exception:
                    pass
        if cancelled is not None:
            reason = 'cancelled'
        elif overrun:
            reason = 'usage_overrun'
        elif str(failure) == 'deadline_exceeded':
            reason = 'deadline_exceeded'
        elif stage == 'http':
            code = failure.args[0]
            reason = code if code in _TRANSPORT_CODES else 'transport_failed'
        elif type(failure) is RecordingValidationError:
            reason = 'response_invalid'
        else:
            reason = 'journal_failed'
        self._mark_failure(ticket, completed, reason)
        if cancelled is not None:
            raise cancelled
        raise failure

    def snapshot(self):
        return dict(evidence_kind=self._kind, failed=self._failed, cleanup_verified=self._cleanup_verified,
                    budget=self._budget.snapshot(), journal=self._journal.snapshot())
