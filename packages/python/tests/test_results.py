import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cragkit.contracts import parse_result
from cragkit.errors import InvalidRequest

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/results.json").read_text()
)
CASES = {case["id"]: case["input"] for case in FIXTURES["cases"]}


def partial():
    return copy.deepcopy(CASES["unicode-large-id-unknown-partial"])


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["id"])
def test_shared_result_fixtures(case):
    if case["valid"]:
        result = parse_result(case["input"])
        assert result.request_id == case["input"]["request_id"]
        assert result.status == case["input"]["status"]
        assert result.model_dump(mode="json")["context"] == case["input"].get("context", "")
    else:
        with pytest.raises(InvalidRequest):
            parse_result(case["input"])


def test_unknown_usage_stays_null_and_explicit_zero_is_retained():
    unknown = parse_result({"request_id": "r", "status": "insufficient"})
    assert unknown.usage.provider_input_tokens is None
    assert unknown.usage.provider_output_tokens is None
    assert unknown.usage.cost_usd is None
    assert unknown.usage.context_tokens is None
    assert unknown.usage.cost_kind == unknown.usage.context_counting == "unknown"
    known = parse_result(CASES["explicit-known-zero-usage"])
    assert known.usage.provider_input_tokens == known.usage.provider_output_tokens == 0
    assert known.usage.cost_usd == known.usage.context_tokens == 0
    assert known.usage.cost_kind == "known"
    assert known.model_dump(mode="json")["usage"]["stage_durations"] == []


@pytest.mark.parametrize("status", ["sufficient", "partial", "insufficient"])
@pytest.mark.parametrize("execution", ["complete", "degraded"])
def test_coverage_and_execution_are_independent(status, execution):
    value = copy.deepcopy(CASES["assessed-sufficient"])
    value.update(status=status, execution=execution)
    if execution == "degraded":
        value["limitations"] = [{"code": "degraded_search"}]
    parsed = parse_result(value)
    assert parsed.status == status
    assert parsed.execution == execution


def test_evidence_exact_utf8_digest_offsets_and_large_ids():
    value = partial()
    item = value["evidence"][0]
    assert item["start_byte"] == 7
    item["start_byte"] = 100.0
    item["end_byte"] = 100 + len(item["text"].encode("utf-8"))
    result = parse_result(value)
    assert result.evidence[0].text == item["text"]
    assert result.evidence[0].text_sha256 == hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
    assert type(result.evidence[0].start_byte) is int
    assert result.evidence[0].document_id == "900719925474099312345"
    item["text"] = item["text"].replace("café", "cafe")
    with pytest.raises(InvalidRequest):
        parse_result(value)


def test_nested_result_snapshots_are_detached_and_frozen():
    value = partial()
    value["usage"] = {"stage_durations": [{"stage": "search", "duration_ms": 1}]}
    result = parse_result(value)
    before = result.model_dump(mode="json")
    value["evidence"][0]["document_id"] = "changed"
    value["facets"][0]["evidence_ids"].append("changed")
    value["limitations"][0]["facet_ids"].append("changed")
    value["usage"]["stage_durations"][0]["duration_ms"] = 2
    assert result.model_dump(mode="json") == before
    with pytest.raises(ValidationError):
        result.evidence[0].document_id = "changed"
    with pytest.raises(ValidationError):
        result.facets[0].evidence_ids = ("changed",)
    with pytest.raises(ValidationError):
        result.usage.stage_durations[0].duration_ms = 3
    with pytest.raises(ValidationError):
        result.versions.policy = "changed"


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf"), 2**53])
def test_nonfinite_or_unsafe_usage_is_rejected(number):
    for usage in (
        {"cost_usd": number, "cost_kind": "known"},
        {"provider_input_tokens": number},
        {"stage_durations": [{"stage": "search", "duration_ms": number}]},
    ):
        with pytest.raises(InvalidRequest):
            parse_result({**partial(), "usage": usage})


def test_cycles_and_invalid_result_errors_do_not_leak():
    value = partial()
    value["usage"] = value
    with pytest.raises(InvalidRequest) as caught:
        parse_result(value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert caught.value.to_dict() == {
        "code": "invalid_request", "message": "Invalid retrieval request.", "retryable": False,
    }


def test_source_digest_consistency_uses_the_full_revision_key():
    value = partial()
    second = copy.deepcopy(value["evidence"][0])
    second.update(evidence_id="ev-2", source_sha256="0" * 64)
    value["evidence"].append(second)
    with pytest.raises(InvalidRequest):
        parse_result(value)
    second["revision_id"] = "other-revision"
    parse_result(value)
    second["revision_id"] = value["evidence"][0]["revision_id"]
    second["collection"] = "other-collection"
    parse_result(value)


def test_unique_facet_references_and_required_coverage():
    value = partial()
    value["facets"][0]["evidence_ids"] = ["ev-1", "ev-1"]
    with pytest.raises(InvalidRequest):
        parse_result(value)
    assessed = copy.deepcopy(CASES["assessed-sufficient"])
    assessed["facets"][0]["required"] = False
    with pytest.raises(InvalidRequest):
        parse_result(assessed)
    assessed["status"] = "partial"
    parse_result(assessed)


def test_evidence_and_context_byte_limits():
    value = partial()
    item = value["evidence"][0]
    item["text"] = "🙂" * 8192
    item["end_byte"] = item["start_byte"] + 32768
    item["text_sha256"] = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
    value["context"] = "🙂" * 65536
    parse_result(value)
    value["context"] += "a"
    with pytest.raises(InvalidRequest):
        parse_result(value)
    value["context"] = ""
    item["text"] += "a"
    item["end_byte"] += 1
    item["text_sha256"] = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
    with pytest.raises(InvalidRequest):
        parse_result(value)
