import asyncio
import json
import time

import pytest

from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.reranking import FAKE_RERANK_PROFILE, RerankingAdapter


CANDIDATES = [{"candidate_id": "a", "text": "first"}, {"candidate_id": "b", "text": "second"}]


class Recorded:
    def __init__(self, raw: bytes = b'[{"candidate_id":"b","raw_score":-2},{"candidate_id":"a","raw_score":-2}]') -> None:
        self.raw = raw
        self.calls = 0
        self.body: dict[str, object] = {}

    async def __call__(self, body: bytes, *, deadline: float, max_response_bytes: int) -> bytes:
        self.calls += 1
        self.body = json.loads(body)
        assert max_response_bytes == 65536
        return self.raw


def run(adapter: RerankingAdapter, candidates: object = None, **kwargs: object) -> dict[str, object]:
    return asyncio.run(adapter.rank("question", CANDIDATES if candidates is None else candidates, deadline=time.monotonic() + 2, **kwargs))  # type: ignore[arg-type]


def test_complete_mapping_and_stable_ties() -> None:
    transport = Recorded()
    result = run(RerankingAdapter(transport))
    assert result["order"] == ["a", "b"]
    assert result["scores"] == [{"candidate_id": "a", "raw_score": -2.0}, {"candidate_id": "b", "raw_score": -2.0}]
    assert result["provider_calls"] == 1 and result["synthetic"] is True
    assert transport.body["query"] == "question"
    assert CANDIDATES[0]["text"] == "first"


def test_direction_and_raw_negative_scores() -> None:
    transport = Recorded(b'[{"candidate_id":"a","raw_score":1.25},{"candidate_id":"b","raw_score":-2.5}]')
    profile = FAKE_RERANK_PROFILE.model_copy(update={"score_direction": "lower_is_better"})
    assert run(RerankingAdapter(transport, profile=profile))["order"] == ["b", "a"]


@pytest.mark.parametrize("raw", [
    b'[]', b'[{"candidate_id":"a","raw_score":1},{"candidate_id":"a","raw_score":2}]',
    b'[{"candidate_id":"a","raw_score":true},{"candidate_id":"b","raw_score":1}]',
    b'[{"candidate_id":"a","raw_score":"1"},{"candidate_id":"b","raw_score":1}]',
    b'[{"candidate_id":"a","raw_score":NaN},{"candidate_id":"b","raw_score":1}]',
    b'[{"candidate_id":"a","raw_score":1e999},{"candidate_id":"b","raw_score":1}]',
    b'[{"candidate_id":"a","raw_score":1,"raw_score":2},{"candidate_id":"b","raw_score":1}]',
    b'[{"candidate_id":"a","raw_score":1,"extra":2},{"candidate_id":"b","raw_score":1}]',
    b'[{"candidate_id":"a","raw_score":1},{"candidate_id":"invented","raw_score":2}]',
    b'[' * 1000, b'x' * 65537,
])
def test_invalid_response_is_fatal_even_with_fallback(raw: bytes) -> None:
    with pytest.raises(IntegrityViolation):
        run(RerankingAdapter(Recorded(raw)), allow_fallback=True)


@pytest.mark.parametrize("candidates", [
    CANDIDATES * 21, [{"candidate_id": "", "text": "x"}],
    [{"candidate_id": "a", "text": "x"}, {"candidate_id": "a", "text": "y"}],
    [{"candidate_id": "x", "text": "\ud800"}], [{"candidate_id": "x", "text": "x" * 16385}],
    [{"candidate_id": "x", "text": "x", "extra": 1}],
])
def test_bad_input_never_dispatches(candidates: object) -> None:
    transport = Recorded()
    with pytest.raises(InvalidRequest):
        run(RerankingAdapter(transport), candidates)
    assert transport.calls == 0


def test_empty_and_exhausted_budget() -> None:
    transport = Recorded()
    assert run(RerankingAdapter(transport), [], max_provider_calls=0)["order"] == []
    with pytest.raises(InvalidRequest):
        run(RerankingAdapter(transport), max_provider_calls=0)
    assert transport.calls == 0


def test_utf8_prefix_diagnostic_and_total_limit() -> None:
    profile = FAKE_RERANK_PROFILE.model_copy(update={"truncation_policy": "utf8_prefix"})
    transport = Recorded(b'[{"candidate_id":"a","raw_score":1}]')
    result = run(RerankingAdapter(transport, profile=profile), [{"candidate_id": "a", "text": "€" * 5462}])
    assert result["truncations"] == [{"candidate_id": "a", "original_bytes": 16386, "view_bytes": 16383}]
    candidates = [{"candidate_id": str(i), "text": "x" * 16384} for i in range(17)]
    with pytest.raises(InvalidRequest):
        run(RerankingAdapter(transport, profile=profile), candidates)


def test_explicit_unavailable_fallback_and_live_policy() -> None:
    async def unavailable(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes:
        raise ProviderUnavailable()
    adapter = RerankingAdapter(unavailable)
    with pytest.raises(ProviderUnavailable):
        run(adapter)
    result = run(adapter, allow_fallback=True)
    assert result["order"] == ["a", "b"] and result["degraded"] is True
    assert result["scores"] == [] and result["provider_calls"] == 1
    profile = FAKE_RERANK_PROFILE.model_copy(update={"provider": "hosted"})
    with pytest.raises(UnsupportedCapability):
        run(RerankingAdapter(unavailable, profile=profile), allow_fallback=True)


def test_timeout_cancellation_and_reentrancy() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        async def waiting(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes:
            entered.set()
            await release.wait()
            return b'[]'
        adapter = RerankingAdapter(waiting)
        task = asyncio.create_task(adapter.rank("q", CANDIDATES, deadline=time.monotonic() + 1))
        await entered.wait()
        with pytest.raises(InvalidRequest):
            await adapter.rank("q", CANDIDATES, deadline=time.monotonic() + 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        with pytest.raises(DeadlineExceeded):
            await adapter.rank("q", CANDIDATES, deadline=time.monotonic() + .01)
    asyncio.run(scenario())


def test_configuration_revalidated_and_invalid_deadline() -> None:
    forged = FAKE_RERANK_PROFILE.model_copy(update={"model": "\ud800"})
    with pytest.raises(InvalidRequest):
        RerankingAdapter(Recorded(), profile=forged)
    for deadline in [True, float("nan"), float("inf"), 10 ** 1000]:
        with pytest.raises(InvalidRequest):
            asyncio.run(RerankingAdapter(Recorded()).rank("q", CANDIDATES, deadline=deadline))


def test_noncooperating_transport_keeps_admission_bounded() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        stopped = asyncio.Event()
        async def stubborn(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes:
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            stopped.set()
            return b'[]'
        adapter = RerankingAdapter(stubborn)
        with pytest.raises(DeadlineExceeded):
            await adapter.rank("q", CANDIDATES, deadline=time.monotonic() + .01)
        with pytest.raises(InvalidRequest):
            await adapter.rank("q", CANDIDATES, deadline=time.monotonic() + 1)
        release.set()
        await stopped.wait()
        await asyncio.sleep(0)
        assert (await adapter.rank("q", [], deadline=time.monotonic() + 1))["provider_calls"] == 0
    asyncio.run(scenario())


def test_expiry_between_task_scheduling_and_dispatch_does_not_call_transport(monkeypatch) -> None:
    transport = Recorded()
    adapter = RerankingAdapter(transport)
    calls = 0
    def check(deadline: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise DeadlineExceeded()
    monkeypatch.setattr(adapter, "_deadline", check)
    with pytest.raises(DeadlineExceeded):
        run(adapter)
    assert calls == 4
    assert transport.calls == 0
