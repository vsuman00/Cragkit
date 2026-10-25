import asyncio
import hashlib
import time

import pytest

from cragkit.contracts import Evidence, parse_request, parse_scope, parse_tool_request
from cragkit.contracts._validation import native_json, text
from cragkit.errors import InvalidRequest
from cragkit.packing import pack_evidence


BASE = {"query": "find", "collection": "docs"}
NUL = "before\0after"


@pytest.mark.parametrize("parse", [parse_request, parse_tool_request])
@pytest.mark.parametrize("changes", [
    {"query": NUL}, {"collection": NUL}, {"request_id": NUL},
    {"search_hints": [NUL]},
])
def test_request_and_tool_reject_nul(parse, changes):
    with pytest.raises(InvalidRequest):
        parse({**BASE, **changes})


@pytest.mark.parametrize("field", ["renderer", "tokenizer"])
def test_output_profile_rejects_nul_identity(field):
    with pytest.raises(InvalidRequest):
        parse_request({**BASE, "output_profile": {field: NUL}})


@pytest.mark.parametrize("changes", [
    {"tenant_id": NUL}, {"principal_id": NUL},
    {"authorization_revision": NUL}, {"grant_ids": [NUL]},
])
def test_scope_rejects_nul(changes):
    with pytest.raises(InvalidRequest):
        parse_scope({"tenant_id": "t", "principal_id": "p",
                     "authorization_revision": "a", **changes})


@pytest.mark.parametrize("leaf", [
    {"op": "eq", "field": "tag", "value": NUL},
    {"op": "ne", "field": "tag", "value": NUL},
    {"op": "in", "field": "tag", "values": ["safe", NUL]},
])
@pytest.mark.parametrize("wrapper", ["direct", "not", "and", "or"])
@pytest.mark.parametrize("field", ["document_id", "revision_id", "language", "kind", "tag"])
def test_filter_strings_reject_nul_at_nested_boundaries(leaf, wrapper, field):
    leaf = {**leaf, "field": field}
    predicate = leaf if wrapper == "direct" else (
        {"op": "not", "filter": leaf} if wrapper == "not" else
        {"op": wrapper, "filters": [{"op": "not", "filter": leaf}]}
    )
    with pytest.raises(InvalidRequest):
        parse_request({**BASE, "required_filters": [predicate]})


def test_nul_policy_preserves_source_and_evidence_bytes():
    source = "pré\0fix 🙂"
    encoded = source.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    evidence = Evidence.model_validate({
        "evidence_id": "e", "collection": "c", "document_id": "d",
        "revision_id": "r", "chunk_id": "k", "source_locator": "fixture",
        "start_byte": 0, "end_byte": len(encoded), "text": source,
        "source_sha256": digest, "text_sha256": digest,
    })
    assert Evidence.model_validate_json(evidence.model_dump_json()).text.encode("utf-8") == encoded
    assert text(source, 1024) == source
    assert native_json({"source": source}) == {"source": source}
    packed = asyncio.run(pack_evidence(
        [evidence.model_dump(mode="json")],
        [{"collection": "c", "document_id": "d", "revision_id": "r",
          "source_sha256": digest, "text": source}],
        deadline=time.monotonic() + 10, max_tokens=10000, surrounding_bytes=0,
    ))
    assert packed["evidence"][0]["text"].encode("utf-8") == encoded


def test_valid_input_text_is_not_normalized():
    original = "  café 🙂\r\n"
    assert parse_request({"query": original, "collection": " docs "}).query == original
    assert parse_request({**BASE, "required_filters": [
        {"op": "in", "field": "tag", "values": ["", False, 1, " café "]},
    ]}).required_filters[0].values == ("", False, 1, " café ")
