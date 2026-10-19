import copy
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from cragkit import errors
from cragkit.contracts import parse_request, parse_scope, parse_tool_request

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/requests.json").read_text()
)
BASE = {"query": "  café 🙂  ", "collection": "manuals", "request_id": "request-1"}
LEAF = {"op": "eq", "field": "tag", "value": "original"}


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["id"])
def test_shared_fixtures(case):
    parser = {"request": parse_request, "tool": parse_tool_request, "scope": parse_scope}[case["kind"]]
    if case["valid"]:
        parsed = parser(case["input"])
        wire = parsed.model_dump(mode="json")
        for key, value in case["input"].items():
            if key not in ("limits", "output_profile"):
                assert wire[key] == value
    else:
        with pytest.raises(errors.InvalidRequest):
            parser(case["input"])


def test_defaults_ids_and_json_integer_equivalence():
    request = parse_request({"query": "find", "collection": "docs"})
    other = parse_tool_request({"query": "find", "collection": "docs"})
    assert UUID(request.request_id).version == 4
    assert request.request_id != other.request_id
    assert request.schema_version == "0.1"
    assert request.required_filters == request.search_hints == ()
    assert request.limits.model_dump() == {
        "deadline_ms": 10000, "max_attempts": 3, "max_subqueries": 4,
        "max_candidates": 200, "max_context_tokens": 2000, "max_provider_calls": 16,
        "max_spend_usd": None,
    }
    assert request.output_profile.model_dump() == {
        "renderer": "cragkit.context.v1", "tokenizer": None,
        "envelope_reserve_tokens": 256, "counting_mode": "estimated",
    }
    normalized = parse_request({**BASE, "limits": {"deadline_ms": 1.0}})
    assert type(normalized.limits.deadline_ms) is int
    scalar = parse_request({**BASE, "required_filters": [{**LEAF, "value": 1.0}]})
    assert type(scalar.required_filters[0].value) is float
    assert parse_request(BASE).query == BASE["query"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 2**53])
def test_invalid_native_numbers(value):
    for request in (
        {**BASE, "limits": {"max_spend_usd": value}},
        {**BASE, "required_filters": [{**LEAF, "value": value}]},
        {**BASE, "required_filters": [{"op": "gt", "field": "tag", "value": value}]},
    ):
        with pytest.raises(errors.InvalidRequest):
            parse_request(request)


def test_snapshots_are_deeply_immutable():
    original = {
        **BASE,
        "required_filters": [{"op": "and", "filters": [{"op": "in", "field": "tag", "values": ["a"]}]}],
        "search_hints": ["hint"], "limits": {"max_attempts": 2},
    }
    parsed = parse_request(original)
    before = parsed.model_dump(mode="json")
    original["required_filters"][0]["filters"][0]["values"].append("b")
    original["search_hints"].append("other")
    original["limits"]["max_attempts"] = 9
    assert parsed.model_dump(mode="json") == before
    with pytest.raises(ValidationError):
        parsed.query = "changed"
    with pytest.raises(ValidationError):
        parsed.limits.max_attempts = 9
    with pytest.raises(ValidationError):
        parsed.required_filters[0].filters[0].values = ("changed",)
    grants = ["read"]
    scope = parse_scope({"tenant_id": "t", "principal_id": "p", "authorization_revision": "a", "grant_ids": grants})
    grants.append("write")
    assert scope.grant_ids == ("read",)


def test_cyclic_and_non_json_inputs_are_rejected():
    node = {"op": "not"}
    node["filter"] = node
    for value in ({**BASE, "required_filters": [node]}, {**BASE, "search_hints": ("hint",)}, None, []):
        with pytest.raises(errors.InvalidRequest):
            parse_request(value)
    circular = []
    circular.append(circular)
    with pytest.raises(errors.InvalidRequest):
        parse_request({**BASE, "unknown": circular})


def test_filter_depth_and_node_boundaries():
    node = copy.deepcopy(LEAF)
    for _ in range(7):
        node = {"op": "not", "filter": node}
    parse_request({**BASE, "required_filters": [node]})
    with pytest.raises(errors.InvalidRequest):
        parse_request({**BASE, "required_filters": [{"op": "not", "filter": node}]})
    roots = [{"op": "and", "filters": [copy.deepcopy(LEAF) for _ in range(size)]} for size in (16, 16, 16, 12)]
    parse_request({**BASE, "required_filters": roots})
    roots[-1]["filters"].append(copy.deepcopy(LEAF))
    with pytest.raises(errors.InvalidRequest):
        parse_request({**BASE, "required_filters": roots})


def test_native_preflight_bounds_unknown_fields_before_validation():
    deep = "private"
    for _ in range(33):
        deep = [deep]
    for unknown in (deep, [None] * 4096):
        with pytest.raises(errors.InvalidRequest) as caught:
            parse_request({**BASE, "unknown": unknown})
        assert caught.value.__context__ is None
        assert caught.value.to_dict()["message"] == "Invalid retrieval request."


@pytest.mark.parametrize("name,maximum,minimum", [
    ("deadline_ms", 300000, 1), ("max_attempts", 10, 1), ("max_subqueries", 16, 1),
    ("max_candidates", 10000, 1), ("max_context_tokens", 1000000, 1),
    ("max_provider_calls", 1000, 0),
])
def test_integer_limits(name, maximum, minimum):
    for value in (minimum, maximum):
        parse_request({**BASE, "limits": {name: value}})
    for value in (minimum - 1, maximum + 1, True, 1.5, "1", None):
        with pytest.raises(errors.InvalidRequest):
            parse_request({**BASE, "limits": {name: value}})


def test_unicode_and_output_profile_boundaries():
    parse_request({**BASE, "query": "🙂" * 4096, "collection": "🙂" * 32})
    for changes in (
        {"collection": "🙂" * 33}, {"query": "\ud800"},
        {"output_profile": {"counting_mode": "other"}},
        {"output_profile": {"envelope_reserve_tokens": True}},
        {"output_profile": {"renderer": " "}},
    ):
        with pytest.raises(errors.InvalidRequest):
            parse_request({**BASE, **changes})
    strict = parse_request({**BASE, "output_profile": {"counting_mode": "strict", "tokenizer": "tokenizer-v1"}})
    assert strict.output_profile.tokenizer == "tokenizer-v1"


@pytest.mark.parametrize("cls,code,message,retryable", [
    (errors.InvalidRequest, "invalid_request", "Invalid retrieval request.", False),
    (errors.UnauthorizedScope, "unauthorized_scope", "Access scope is not authorized.", False),
    (errors.UnsupportedCapability, "unsupported_capability", "Required capability is unavailable.", False),
    (errors.IndexNotReady, "index_not_ready", "Index is not ready.", True),
    (errors.EmbeddingProfileMismatch, "embedding_profile_mismatch", "Embedding profile does not match.", False),
    (errors.ProviderUnavailable, "provider_unavailable", "Provider is unavailable.", True),
    (errors.DeadlineExceeded, "deadline_exceeded", "Request deadline exceeded.", True),
    (errors.ContextBudgetTooSmall, "context_budget_too_small", "Context budget cannot fit the required envelope.", False),
    (errors.IntegrityViolation, "integrity_violation", "Source integrity validation failed.", False),
])
def test_fixed_error_envelopes(cls, code, message, retryable):
    error = cls()
    assert str(error) == message
    assert error.to_dict() == {"code": code, "message": message, "retryable": retryable}


def test_rejection_has_no_private_validation_chain():
    with pytest.raises(errors.InvalidRequest) as caught:
        parse_request({**BASE, "query": {"secret": "private-query"}})
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "private-query" not in str(caught.value.to_dict())
