"""Disclosure admission mechanics only; no source packet or provider is accessed."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation_payloads import EvaluationPayloadError, EvaluationPayloadGate
from provider_adapters import COHERE_MODEL, OPENAI_MODEL, ProviderRequest

SOURCE = 'Public synthetic source: bounded retries preserve access.'
QUERY = 'What preserves access?'


def request(provider='openai', **changes):
    body = (dict(model=OPENAI_MODEL, dimensions=1536, encoding_format='float', input=[QUERY, SOURCE])
            if provider == 'openai' else dict(model=COHERE_MODEL, query=QUERY,
                documents=[SOURCE, 'bounded retries'], top_n=2, max_tokens_per_doc=4096))
    body.update(changes)
    return ProviderRequest(provider, body['model'], json.dumps(body).encode(), 'a' * 64)


@pytest.fixture(scope='module')
def counter():
    from cragkit.context import Cl100kCounter
    path = Path(__file__).resolve().parents[2] / 'artifacts/tokenizers/cl100k_base.tiktoken'
    if not path.is_file():
        pytest.skip('Explicitly prepared pinned tokenizer asset required')
    return Cl100kCounter.from_file(path)


def test_openai_exact_pinned_count_and_immutable_source_query_snapshot(counter):
    sources, queries = [SOURCE], [QUERY]
    gate = EvaluationPayloadGate(sources, queries)
    sources[0] = 'private replacement'; queries[0] = 'private query'
    assert gate.admission_ceiling(request(), counter=counter) == counter.count(QUERY) + counter.count(SOURCE)
    assert SOURCE not in repr(gate)
    with pytest.raises(EvaluationPayloadError):
        gate.admission_ceiling(request(input=['private replacement']), counter=counter)


def test_cohere_reserves_complete_pair_context_without_claiming_local_tokenizer():
    gate = EvaluationPayloadGate([SOURCE], [QUERY])
    assert gate.admission_ceiling(request('cohere')) == 2 * 32768


@pytest.mark.parametrize('provider,changes', [
    ('openai', {'input': ['private source']}), ('openai', {'input': ['new unapproved query']}),
    ('openai', {'dimensions': True}), ('openai', {'dimensions': 3072}),
    ('openai', {'encoding_format': 'base64'}), ('openai', {'input': [SOURCE] * 9}),
    ('openai', {'input': []}), ('openai', {'user': 'unapproved metadata'}),
    ('cohere', {'query': 'unapproved rewrite'}), ('cohere', {'documents': ['private document'], 'top_n': 1}),
    ('cohere', {'top_n': True}), ('cohere', {'top_n': 1}),
    ('cohere', {'max_tokens_per_doc': 8192}), ('cohere', {'documents': [SOURCE] * 16, 'top_n': 16}),
    ('cohere', {'return_documents': True}),
])
def test_unapproved_text_or_changed_wire_policy_has_no_admission(provider, changes):
    gate = EvaluationPayloadGate([SOURCE], [QUERY])
    with pytest.raises(EvaluationPayloadError, match='^unapproved_evaluation_payload$') as error:
        gate.admission_ceiling(request(provider, **changes))
    assert error.value.__context__ is None


@pytest.mark.parametrize('body', [b'{private malformed', b'[]', b'{"model":1,"model":2}'])
def test_bad_json_does_not_retain_private_parser_context(body):
    gate = EvaluationPayloadGate([SOURCE], [QUERY])
    with pytest.raises(EvaluationPayloadError) as error:
        gate.admission_ceiling(replace(request(), body=body))
    assert error.value.__context__ is None and error.value.__cause__ is None


def test_surrogate_source_fails_without_retaining_encoding_error():
    with pytest.raises(EvaluationPayloadError) as error:
        EvaluationPayloadGate(['private\ud800'], [QUERY])
    assert error.value.__context__ is None


def test_unissued_counter_cannot_lower_openai_admission():
    from cragkit.context import Cl100kCounter
    gate = EvaluationPayloadGate([SOURCE], [QUERY])
    class Fake:
        def count(self, text):
            pytest.fail('Unissued counter was invoked')
    for counter in (None, Fake(), object.__new__(Cl100kCounter)):
        with pytest.raises(EvaluationPayloadError):
            gate.admission_ceiling(request(), counter=counter)


@pytest.mark.parametrize('sources,queries', [([], [QUERY]), ([SOURCE], []), ('source', [QUERY]),
    ([SOURCE], [QUERY] * 129), (['x' * 262145], [QUERY]), ([SOURCE], ['x' * 8193]),
    (['x' * 262144] * 5, [QUERY])])
def test_packet_memory_and_shape_bounds(sources, queries):
    with pytest.raises(EvaluationPayloadError):
        EvaluationPayloadGate(sources, queries)
