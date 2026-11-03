"""Serial pacing for explicit evaluation runs; no provider I/O or retries."""
import asyncio
import math
import time

from provider_adapters import ProviderAdapterError


class EvaluationPacer:
    """Admit one evaluation dispatch at a time against its original deadline."""

    def __init__(self):
        self._clock = time.monotonic
        self._sleep = asyncio.sleep
        self._busy = False
        self._last_cohere = None
        self._last_terminal_cohere = None
        self._invalidated = False
        self._observed = None

    def _now(self):
        value = None
        try:
            value = self._clock()
        except Exception:
            pass
        if type(value) not in (int, float):
            raise ProviderAdapterError('provider_pacing_invalid')
        try:
            valid = math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid or (self._observed is not None and value < self._observed):
            raise ProviderAdapterError('provider_pacing_invalid')
        self._observed = value
        return value

    def finish(self, provider):
        """Anchor the next admission after a started operation has unwound."""
        if type(provider) is not str or provider not in ('openai', 'cohere'):
            raise ProviderAdapterError('provider_pacing_invalid')
        if self._busy:
            raise ProviderAdapterError('concurrent_dispatch')
        if self._invalidated:
            raise ProviderAdapterError('provider_pacing_invalid')
        self._busy = True
        try:
            failed = False
            try:
                now = self._now()
            except ProviderAdapterError:
                self._invalidated = True
                failed = True
            if failed:
                raise ProviderAdapterError('provider_pacing_invalid')
            if provider == 'cohere':
                self._last_terminal_cohere = now
        finally:
            self._busy = False

    async def wait(self, provider, *, deadline):
        if type(provider) is not str or provider not in ('openai', 'cohere'):
            raise ProviderAdapterError('provider_pacing_invalid')
        valid = False
        if type(deadline) in (int, float):
            try:
                valid = math.isfinite(deadline)
            except OverflowError:
                pass
        if not valid:
            raise ProviderAdapterError('provider_pacing_invalid')
        if self._busy:
            raise ProviderAdapterError('concurrent_dispatch')
        if self._invalidated:
            raise ProviderAdapterError('provider_pacing_invalid')
        self._busy = True
        try:
            task = asyncio.current_task()
            if task is None or task.cancelling():
                raise asyncio.CancelledError()
            now = self._now()
            target = now
            anchors = [value for value in (self._last_cohere, self._last_terminal_cohere)
                       if value is not None]
            if provider == 'cohere' and anchors:
                anchor = max(anchors)
                next_slot = anchor + 6.1
                if next_slot - anchor < 6.1:
                    next_slot = math.nextafter(next_slot, math.inf)
                target = max(now, next_slot)
            if now >= deadline or target >= deadline:
                raise ProviderAdapterError('deadline_exceeded')
            if target > now:
                failure = False
                cancelled = False
                try:
                    await self._sleep(target - now)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    failure = True
                if cancelled or task.cancelling():
                    raise asyncio.CancelledError()
                if failure:
                    raise ProviderAdapterError('provider_pacing_failed')
                now = self._now()
                if now >= deadline:
                    raise ProviderAdapterError('deadline_exceeded')
                if now < target:
                    raise ProviderAdapterError('provider_pacing_failed')
            if task.cancelling():
                raise asyncio.CancelledError()
            if provider == 'cohere':
                self._last_cohere = now
        finally:
            self._busy = False
