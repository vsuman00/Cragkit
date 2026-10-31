"""Stored response validation reuses the actual model-specific mappers."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_adapters import COHERE_MODEL, OPENAI_MODEL, ProviderRequest
from provider_recordings import RecordingValidationError, request_metadata, validate_recording


def request(provider='openai'):
    body = (dict(model=OPENAI_MODEL, dimensions=1536, encoding_format='float', input=['public fixture'])
            if provider == 'openai' else dict(model=COHERE_MODEL, query='fixture',
                documents=['public fixture'], top_n=1, max_tokens_per_doc=4096))
    return ProviderRequest(provider, body['model'], json.dumps(body).encode(), 'a' * 64)


def response(provider='openai', usage=True):
    if provider == 'openai':
        value = dict(model=OPENAI_MODEL, data=[dict(index=0, embedding=[1.] + [0.] * 1535)])
        if usage:
            value['usage'] = dict(prompt_tokens=2, total_tokens=3)
    else:
        value = dict(results=[dict(index=0, relevance_score=.8)])
        if usage:
            value['meta'] = dict(billed_units=dict(input_tokens=2., search_units=.5))
    return value


@pytest.mark.parametrize('provider', ['openai', 'cohere'])
def test_metadata_is_closed_and_excludes_payload(provider):
    row = request(provider)
    assert request_metadata(row) == dict(provider=provider, model=row.model, replay_key='a' * 64,
        request_sha256=sha256(row.body).hexdigest(), response_items=1)


@pytest.mark.parametrize('provider,expected', [('openai', 3), ('cohere', 2)])
def test_reported_usage_is_not_replaced_with_an_estimate(provider, expected):
    assert validate_recording(provider, request(provider).model, json.dumps(response(provider)).encode(),
                              expected_items=1) == expected
    assert validate_recording(provider, request(provider).model, json.dumps(response(provider, False)).encode(),
                              expected_items=1) is None


def test_search_units_do_not_become_input_token_counts():
    value = response('cohere')
    value['meta']['billed_units'] = dict(search_units=1.)
    assert validate_recording('cohere', COHERE_MODEL, json.dumps(value).encode(), expected_items=1) is None


@pytest.mark.parametrize('mutation', ['dimension', 'nonfinite', 'index', 'model', 'usage', 'count'])
def test_bad_embedding_recording_cannot_be_replayed(mutation):
    value, items = response(), 1
    if mutation == 'dimension':
        value['data'][0]['embedding'].pop()
    if mutation == 'nonfinite':
        value['data'][0]['embedding'][0] = float('nan')
    if mutation == 'index':
        value['data'][0]['index'] = 1
    if mutation == 'model':
        value['model'] = 'another model'
    if mutation == 'usage':
        value['usage']['prompt_tokens'] = 4
    if mutation == 'count':
        items = 2
    with pytest.raises(RecordingValidationError):
        validate_recording('openai', OPENAI_MODEL, json.dumps(value).encode(), expected_items=items)


@pytest.mark.parametrize('mutation', ['index', 'score', 'count', 'fractional_tokens'])
def test_bad_rerank_recording_cannot_be_replayed(mutation):
    value, items = response('cohere'), 1
    if mutation == 'index':
        value['results'][0]['index'] = True
    if mutation == 'score':
        value['results'][0]['relevance_score'] = 2
    if mutation == 'count':
        items = 2
    if mutation == 'fractional_tokens':
        value['meta']['billed_units']['input_tokens'] = 1.5
    with pytest.raises(RecordingValidationError):
        validate_recording('cohere', COHERE_MODEL, json.dumps(value).encode(), expected_items=items)


@pytest.mark.parametrize('raw', [b'{private invalid', b'{"model":1,"model":2}', b'[]'])
def test_private_parser_context_is_not_retained(raw):
    for operation in (lambda: request_metadata(replace(request(), body=raw)),
                      lambda: validate_recording('openai', OPENAI_MODEL, raw, expected_items=1)):
        with pytest.raises(RecordingValidationError) as error:
            operation()
        assert error.value.__cause__ is None and error.value.__context__ is None


@pytest.mark.parametrize('changed', [dict(provider='other'), dict(model='wrong'), dict(replay_key='bad')])
def test_recording_identity_must_match_the_fixed_provider(changed):
    with pytest.raises(RecordingValidationError):
        request_metadata(replace(request(), **changed))


def test_shared_node_fixture_stays_bound_to_actual_python_request_and_response_mapping():
    import base64
    from provider_adapters import OpenAIEmbeddingTransport, CohereRerankTransport
    root = Path(__file__).resolve().parents[2]
    fixture = json.loads((root / 'contracts/fixtures/provider_replay.json').read_text())
    assert fixture['evidence_kind'] == 'synthetic_mechanics'
    for call in fixture['calls']:
        cls = OpenAIEmbeddingTransport if call['transport'] == 'embedding' else CohereRerankTransport
        transport = cls(lambda *args, **kwargs: None)
        body = json.dumps(call['native_body'], ensure_ascii=False, separators=(',', ':')).encode()
        mapped_request, context = transport._prepare(body)
        recording = call['recording']
        assert (mapped_request.provider, mapped_request.model, mapped_request.replay_key) == (
            recording['provider'], recording['model'], recording['replay_key'])
        raw = base64.b64decode(recording['response_base64'], validate=True)
        mapped, _ = transport._map(json.loads(raw), context)
        assert json.loads(mapped) == call['mapped_response']
