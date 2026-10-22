"""E-r1 deterministic boundary checks; all transports and vectors are synthetic."""

import asyncio
import json
import time
import traceback

import pytest
from pydantic import ValidationError

from cragkit import errors
from cragkit.embeddings import (
    FAKE_PROFILE, OPENAI_PROFILE, EmbeddingAdapter, EmbeddingLimits,
    EmbeddingPolicy, EmbeddingProfile,
)


class Counter:
    name = "fake-byte-v1"

    def __init__(self, count=None, name=None):
        self.value = count
        if name is not None:
            self.name = name

    def count(self, text):
        return len(text.encode("utf-8")) if self.value is None else self.value


def vector(index=0, magnitude=1.0):
    result = [0.0] * 1536
    result[index] = magnitude
    return result


def response(size=1, *, model=FAKE_PROFILE.model, usage=None):
    return {"model": model, "data": [
        {"index": index, "embedding": vector(index)} for index in range(size)
    ], "usage": usage}


class Transport:
    def __init__(self, payload=None):
        self.payload = response() if payload is None else payload
        self.calls = []

    async def __call__(self, body, *, deadline, max_response_bytes):
        self.calls.append((json.loads(body), deadline, max_response_bytes))
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()


def execute(adapter, texts=("a",), deadline=None):
    return asyncio.run(adapter.embed_batch(
        texts, deadline=time.monotonic() + 5 if deadline is None else deadline,
    ))


def test_fake_request_exact_shape_reordered_vectors_and_immutable_result():
    payload = response(2, usage={"prompt_tokens": 3, "total_tokens": 4})
    payload["data"].reverse()
    transport = Transport(payload)
    result = execute(EmbeddingAdapter(transport, Counter()), [" é", "🙂"])
    assert transport.calls[0][0] == {
        "model": "fake_embedding_model_v1", "dimensions": 1536,
        "encoding_format": "float", "input": [" é", "🙂"],
    }
    assert transport.calls[0][2] == 1048576
    assert result.profile == FAKE_PROFILE
    assert result.vectors == (tuple(vector(0)), tuple(vector(1)))
    assert result.provider_calls == 1 and result.synthetic is True
    assert result.usage.prompt_tokens == 3 and result.usage.total_tokens == 4
    assert result.usage.cost_usd == 0 and result.usage.cost_kind == "known"
    payload["data"][0]["embedding"][1] = 9
    assert result.vectors[1][1] == 1
    with pytest.raises(ValidationError):
        result.synthetic = False
    with pytest.raises(TypeError):
        result.vectors[0][0] = 2


@pytest.mark.parametrize("model", [FAKE_PROFILE, OPENAI_PROFILE, EmbeddingLimits(), EmbeddingPolicy()])
def test_public_configuration_is_frozen_and_forbids_extra_fields(model):
    field = next(iter(type(model).model_fields))
    with pytest.raises(ValidationError):
        setattr(model, field, getattr(model, field))
    with pytest.raises(ValidationError):
        type(model)(**{**model.model_dump(), "extra": "rejected"})


@pytest.mark.parametrize("keyword,model,changes", [
    ("profile", FAKE_PROFILE, {"model": "other"}),
    ("profile", FAKE_PROFILE, {"dimensions": True}),
    ("limits", EmbeddingLimits(), {"max_items": 9}),
    ("limits", EmbeddingLimits(), {"max_items": True}),
    ("policy", EmbeddingPolicy(), {"max_cost_usd": float("nan")}),
    ("policy", EmbeddingPolicy(), {"allow_live": "yes"}),
])
def test_adapter_revalidates_unchecked_configuration(keyword, model, changes):
    for unchecked in (
        model.model_copy(update=changes),
        type(model).model_construct(**{**model.model_dump(), **changes}),
    ):
        with pytest.raises(errors.InvalidRequest):
            EmbeddingAdapter(Transport(), Counter(), **{keyword: unchecked})


@pytest.mark.parametrize("name,maximum", [
    ("max_items", 8), ("max_input_bytes", 8192), ("max_batch_bytes", 32768),
    ("max_input_tokens", 8192), ("max_batch_tokens", 32768),
    ("max_response_bytes", 2097152),
])
def test_limit_models_enforce_positive_strict_integers(name, maximum):
    assert getattr(EmbeddingLimits(**{name: maximum}), name) == maximum
    for value in (0, -1, True, 1.0, "1", maximum + 1):
        with pytest.raises(ValidationError):
            EmbeddingLimits(**{name: value})


@pytest.mark.parametrize("texts", [[], "scalar", (x for x in ["a"]), [""], [1], [b"a"], ["\ud800"], ["a"] * 9])
def test_invalid_inputs_never_dispatch(texts):
    transport = Transport()
    with pytest.raises(errors.InvalidRequest):
        execute(EmbeddingAdapter(transport, Counter()), texts)
    assert transport.calls == []


@pytest.mark.parametrize("count", [0, -1, True, 1.0, "1", None, 2147483648])
def test_invalid_counter_outputs_never_dispatch(count):
    class BadCounter(Counter):
        def count(self, text):
            return count
    transport = Transport()
    with pytest.raises(errors.InvalidRequest):
        execute(EmbeddingAdapter(transport, BadCounter()))
    assert transport.calls == []


@pytest.mark.parametrize("limits,texts,count", [
    ({"max_input_bytes": 3}, ["🙂"], 1),
    ({"max_batch_bytes": 3}, ["é", "é"], 1),
    ({"max_input_tokens": 2}, ["a"], 3),
    ({"max_batch_tokens": 3}, ["a", "b"], 2),
])
def test_byte_and_token_excess_never_dispatch(limits, texts, count):
    transport = Transport()
    with pytest.raises(errors.InvalidRequest):
        execute(EmbeddingAdapter(transport, Counter(count), limits=EmbeddingLimits(**limits)), texts)
    assert transport.calls == []


def test_exact_admission_boundaries_and_whitespace_are_preserved():
    transport = Transport(response(2))
    adapter = EmbeddingAdapter(transport, Counter(2), limits=EmbeddingLimits(
        max_items=2, max_input_bytes=4, max_batch_bytes=8,
        max_input_tokens=2, max_batch_tokens=4,
    ))
    execute(adapter, ["🙂", "    "])
    assert transport.calls[0][0]["input"] == ["🙂", "    "]


@pytest.mark.parametrize("raw", [
    b"\xff", b"{", b'[]', b'null',
    b'{"model":"fake_embedding_model_v1","model":"fake_embedding_model_v1","data":[]}',
    b'{"data":NaN}', b'{"data":Infinity}', b'{"data":-Infinity}',
])
def test_invalid_raw_json_is_sanitized(raw):
    with pytest.raises(errors.ProviderUnavailable) as caught:
        execute(EmbeddingAdapter(Transport(raw), Counter()))
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_response_byte_cap_is_inclusive():
    raw = json.dumps(response()).encode()
    execute(EmbeddingAdapter(Transport(raw), Counter(), limits=EmbeddingLimits(max_response_bytes=len(raw))))
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(Transport(raw), Counter(), limits=EmbeddingLimits(max_response_bytes=len(raw) - 1)))


@pytest.mark.parametrize("component", [True, "1", None, float("nan"), float("inf"), float("-inf"), 1e308])
def test_invalid_vector_components_are_rejected(component):
    payload = response()
    payload["data"][0]["embedding"][0] = component
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(Transport(payload), Counter()))


@pytest.mark.parametrize("magnitude", [0, 0.998, 1.002])
def test_zero_or_nonunit_vectors_are_not_normalized(magnitude):
    payload = response()
    payload["data"][0]["embedding"] = vector(magnitude=magnitude)
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(Transport(payload), Counter()))


@pytest.mark.parametrize("change", ["model", "short", "long"])
def test_profile_mismatch_has_distinct_error(change):
    payload = response()
    if change == "model":
        payload["model"] = "different-model"
    else:
        payload["data"][0]["embedding"] = [1.0] * (1535 if change == "short" else 1537)
    with pytest.raises(errors.EmbeddingProfileMismatch):
        execute(EmbeddingAdapter(Transport(payload), Counter()))


@pytest.mark.parametrize("indexes", [[0, 0], [0], [0, 2], [-1, 1], [False, 1], [0.0, 1], ["0", 1]])
def test_index_coverage_is_separate_from_vector_validity(indexes):
    payload = response(2)
    payload["data"] = [{"index": i, "embedding": vector()} for i in indexes]
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(Transport(payload), Counter()), ["a", "b"])


@pytest.mark.parametrize("usage", [
    {}, {"prompt_tokens": 1}, {"prompt_tokens": True, "total_tokens": 1},
    {"prompt_tokens": 1.0, "total_tokens": 1}, {"prompt_tokens": -1, "total_tokens": 1},
    {"prompt_tokens": 2, "total_tokens": 1}, {"prompt_tokens": 0, "total_tokens": 2147483648},
])
def test_malformed_usage_is_rejected(usage):
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(Transport(response(usage=usage)), Counter()))


def test_mocked_openai_usage_unknown_zero_estimated_and_accounting_failure():
    # OpenAI-shaped JSON here is a local mock; no endpoint or billing is exercised.
    for usage, expected, kind in (
        (None, None, "unknown"), ({"prompt_tokens": 0, "total_tokens": 0}, 0, "estimated"),
        ({"prompt_tokens": 2, "total_tokens": 2}, 0.000002, "estimated"),
    ):
        adapter = EmbeddingAdapter(Transport(response(model=OPENAI_PROFILE.model, usage=usage)),
            Counter(2, "cl100k_base"), profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=1.0, usd_per_million_tokens=1.0))
        result = execute(adapter)
        assert result.synthetic is False
        assert result.usage.cost_usd == expected and result.usage.cost_kind == kind
        assert result.usage.prompt_tokens == (None if usage is None else usage["prompt_tokens"])
    adapter = EmbeddingAdapter(Transport(response(model=OPENAI_PROFILE.model,
        usage={"prompt_tokens": 3, "total_tokens": 3})), Counter(2, "cl100k_base"), profile=OPENAI_PROFILE,
        policy=EmbeddingPolicy(allow_live=True, max_cost_usd=1.0, usd_per_million_tokens=1.0))
    with pytest.raises(errors.ProviderUnavailable):
        execute(adapter)


@pytest.mark.parametrize("policy", [
    EmbeddingPolicy(), EmbeddingPolicy(allow_live=True),
    EmbeddingPolicy(allow_live=True, usd_per_million_tokens=1.0),
    EmbeddingPolicy(allow_live=True, max_cost_usd=0.0000008999999999999999, usd_per_million_tokens=0.3),
])
def test_live_policy_denial_including_decimal_rounding_never_dispatch(policy):
    transport = Transport()
    with pytest.raises(errors.UnsupportedCapability):
        adapter = EmbeddingAdapter(transport, Counter(3, "cl100k_base"), profile=OPENAI_PROFILE, policy=policy)
        execute(adapter)
    assert transport.calls == []


def test_tokenizer_mismatch_never_dispatch():
    transport = Transport()
    with pytest.raises(errors.UnsupportedCapability):
        adapter = EmbeddingAdapter(transport, Counter(name="wrong"))
        execute(adapter)
    assert transport.calls == []


@pytest.mark.parametrize("deadline", [True, None, "later", float("nan"), float("inf")])
def test_invalid_deadlines_never_dispatch(deadline):
    transport = Transport()
    async def scenario():
        with pytest.raises(errors.InvalidRequest):
            await EmbeddingAdapter(transport, Counter()).embed_query("a", deadline=deadline)
    asyncio.run(scenario())
    assert transport.calls == []


def test_transport_fault_is_sanitized_without_private_exception_context_and_reusable():
    class Fault(Transport):
        async def __call__(self, body, **kwargs):
            if not self.calls:
                self.calls.append(None)
                raise RuntimeError("private-input credential-response")
            return await super().__call__(body, **kwargs)
    transport = Fault()
    adapter = EmbeddingAdapter(transport, Counter())
    with pytest.raises(errors.ProviderUnavailable) as caught:
        execute(adapter)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert "private-input" not in "".join(traceback.format_exception(caught.value))
    assert execute(adapter).vectors == (tuple(vector()),)


def test_cancellation_rejects_overlap_awaits_cleanup_snapshots_and_reuses():
    async def scenario():
        started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Blocking(Transport):
            async def __call__(self, body, **kwargs):
                if not started.is_set():
                    self.calls.append((json.loads(body),))
                    started.set()
                    try:
                        await release.wait()
                    finally:
                        await asyncio.sleep(0)
                        cleanup.set()
                return json.dumps(response()).encode()
        transport = Blocking()
        adapter = EmbeddingAdapter(transport, Counter())
        texts = ["original"]
        task = asyncio.create_task(adapter.embed_batch(texts, deadline=time.monotonic() + 5))
        await started.wait()
        texts[0] = "changed"
        with pytest.raises(errors.ProviderUnavailable):
            await adapter.embed_query("overlap", deadline=time.monotonic() + 5)
        assert len(transport.calls) == 1
        assert transport.calls[0][0]["input"] == ["original"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleanup.is_set()
        result = await adapter.embed_query("reuse", deadline=time.monotonic() + 5)
        assert result.vectors == (tuple(vector()),)
    asyncio.run(scenario())


def test_deadline_cancels_transport_and_allows_same_instance_reuse():
    async def scenario():
        cleanup = asyncio.Event()
        class Slow(Transport):
            async def __call__(self, body, **kwargs):
                if not self.calls:
                    self.calls.append(None)
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cleanup.set()
                return json.dumps(response()).encode()
        transport = Slow()
        adapter = EmbeddingAdapter(transport, Counter())
        with pytest.raises(errors.DeadlineExceeded):
            await adapter.embed_query("a", deadline=time.monotonic() + 0.02)
        assert cleanup.is_set()
        await adapter.embed_query("b", deadline=time.monotonic() + 5)
    asyncio.run(scenario())


@pytest.mark.parametrize("field,value", [
    ("max_cost_usd", -1.0), ("max_cost_usd", float("inf")),
    ("max_cost_usd", 1000000.1), ("usd_per_million_tokens", 0.0),
    ("usd_per_million_tokens", float("nan")), ("usd_per_million_tokens", 1000000.1),
])
def test_policy_rejects_invalid_costs(field, value):
    with pytest.raises(ValidationError):
        EmbeddingPolicy(**{field: value})


def test_fake_unknown_token_usage_stays_null_and_live_permission_does_not_change_identity():
    result = execute(EmbeddingAdapter(Transport(), Counter(), policy=EmbeddingPolicy(allow_live=True)))
    assert result.profile == FAKE_PROFILE and result.synthetic is True
    assert result.usage.prompt_tokens is None and result.usage.total_tokens is None
    assert result.usage.cost_usd == 0 and result.usage.cost_kind == "known"


def test_missing_usage_and_safe_integer_boundary():
    payload = response()
    del payload["usage"]
    result = execute(EmbeddingAdapter(Transport(payload), Counter()))
    assert result.usage.prompt_tokens is None
    result = execute(EmbeddingAdapter(Transport(response(usage={
        "prompt_tokens": 2147483647, "total_tokens": 2147483647,
    })), Counter()))
    assert result.usage.total_tokens == 2147483647


def test_small_unit_norm_tolerance_preserves_components():
    payload = response()
    payload["data"][0]["embedding"] = vector(magnitude=1.0009)
    result = execute(EmbeddingAdapter(Transport(payload), Counter()))
    assert result.vectors[0][0] == 1.0009


@pytest.mark.parametrize("data", [None, {}, [None], [{"index": 0}], [{"index": 0, "embedding": "wrong"}]])
def test_malformed_data_shapes_are_provider_failures(data):
    payload = response()
    payload["data"] = data
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(Transport(payload), Counter()))


def test_nonbytes_transport_response_is_rejected():
    async def wrong(body, *, deadline, max_response_bytes):
        return json.dumps(response())
    with pytest.raises(errors.ProviderUnavailable):
        execute(EmbeddingAdapter(wrong, Counter()))


def test_counter_exception_is_sanitized_and_admission_resets():
    class FlakyCounter(Counter):
        fail = True
        def count(self, text):
            if self.fail:
                self.fail = False
                raise RuntimeError("private-tokenizer-input")
            return 1
    transport = Transport()
    adapter = EmbeddingAdapter(transport, FlakyCounter())
    with pytest.raises(errors.InvalidRequest) as caught:
        execute(adapter)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert transport.calls == []
    execute(adapter)
    assert len(transport.calls) == 1


def test_expired_and_post_count_deadlines_never_dispatch(monkeypatch):
    transport = Transport()
    with pytest.raises(errors.DeadlineExceeded):
        execute(EmbeddingAdapter(transport, Counter()), deadline=time.monotonic() - 1)
    clock = [100.0]
    class AdvancingCounter(Counter):
        def count(self, text):
            clock[0] = 102.0
            return 1
    monkeypatch.setattr("cragkit.embeddings.time.monotonic", lambda: clock[0])
    with pytest.raises(errors.DeadlineExceeded):
        execute(EmbeddingAdapter(transport, AdvancingCounter()), deadline=101.0)
    assert transport.calls == []


def test_transport_timeout_is_typed_and_reusable():
    class TimeoutOnce(Transport):
        async def __call__(self, body, **kwargs):
            if not self.calls:
                self.calls.append(None)
                raise TimeoutError("private-timeout-details")
            return await super().__call__(body, **kwargs)
    adapter = EmbeddingAdapter(TimeoutOnce(), Counter())
    with pytest.raises(errors.DeadlineExceeded) as caught:
        execute(adapter)
    assert caught.value.__context__ is None
    execute(adapter)


@pytest.mark.parametrize("raw", [b'[' * 1100 + b']' * 1100,
    ('{"model":"fake_embedding_model_v1","data":[{"index":0,"embedding":['
     + '1' + '0' * 400 + ',' + ','.join(['0'] * 1535) + ']}]}').encode(),
])
def test_nested_json_and_numeric_conversion_overflow_fail_safely(raw):
    with pytest.raises(errors.ProviderUnavailable) as caught:
        execute(EmbeddingAdapter(Transport(raw), Counter()))
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_forged_configuration_is_rejected_without_warning_disclosure():
    import warnings

    forged = EmbeddingPolicy.model_construct(allow_live="private-token")
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with pytest.raises(errors.InvalidRequest):
            EmbeddingAdapter(Transport(), Counter(), policy=forged)
    assert recorded == []


def test_decimal_caller_precision_cannot_weaken_budget_or_reported_cost():
    from decimal import localcontext

    transport = Transport(response(model=OPENAI_PROFILE.model,
        usage={"prompt_tokens": 1234, "total_tokens": 1234}))
    with localcontext() as context:
        context.prec = 2
        denied = EmbeddingAdapter(transport, Counter(1234, "cl100k_base"), profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=0.00151, usd_per_million_tokens=1.234))
        with pytest.raises(errors.UnsupportedCapability):
            execute(denied)
        assert transport.calls == []
        allowed = EmbeddingAdapter(transport, Counter(1234, "cl100k_base"), profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=0.002, usd_per_million_tokens=1.234))
        result = execute(allowed)
    assert result.usage.cost_usd == 0.001522756
    assert result.usage.cost_kind == "estimated"
    assert len(transport.calls) == 1
