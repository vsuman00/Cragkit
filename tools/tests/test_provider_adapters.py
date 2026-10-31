"""Injected synthetic provider bytes test mappings, never retrieval quality."""
import asyncio
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_adapters as M


def encoded(value):
    return json.dumps(value, allow_nan=True).encode()


def embedding_body(texts=None):
    return encoded(dict(model=M.OPENAI_MODEL, dimensions=1536, encoding_format='float', input=texts or ['tiny']))


def embedding_response(size=1):
    return dict(model=M.OPENAI_MODEL, data=[dict(index=i, embedding=[1.] + [0.] * 1535) for i in range(size)],
                usage=dict(prompt_tokens=size, total_tokens=size))


def rerank_body():
    return encoded(dict(profile=dict(profile_id='cohere_v5fast_development_v1', provider='cohere',
        model=M.COHERE_MODEL, model_revision='mutable_alias:rerank-v5.0-fast', score_kind='relevance_score',
        score_direction='higher_is_better', preprocessing_revision='utf8-development-r1', truncation_policy='reject'),
        query='tiny query', candidates=[dict(candidate_id='a', text='alpha'), dict(candidate_id='b', text='beta')]))


def rerank_response():
    return dict(results=[dict(index=1, relevance_score=.9), dict(index=0, relevance_score=.2)],
                meta=dict(billed_units=dict(input_tokens=19)))


def call(transport, body):
    return asyncio.run(transport(body, deadline=time.monotonic()+10, max_response_bytes=1048576))


def sender(response, requests=None):
    async def send(request, *, deadline, max_response_bytes):
        if requests is not None:
            requests.append(request)
        return encoded(response)
    return send


def test_openai_mapping_records_actual_usage_and_exact_payload():
    requests = []
    transport = M.OpenAIEmbeddingTransport(sender(embedding_response(), requests))
    assert json.loads(call(transport, embedding_body())) == embedding_response()
    assert requests[0].provider == 'openai'
    assert json.loads(requests[0].body)['dimensions'] == 1536
    assert transport.observations[0]['usage'] == dict(prompt_tokens=1, total_tokens=1)
    assert 'tiny' not in repr(requests[0])
    assert len(transport.recordings) == 1


@pytest.mark.parametrize('mutation', ['model', 'dimension', 'duplicate', 'reordered', 'missing', 'nonfinite', 'bool', 'norm', 'usage'])
def test_openai_rejects_malformed_response(mutation):
    response = embedding_response(2)
    if mutation == 'model':
        response['model'] = 'fake_embedding_model_v1'
    elif mutation == 'dimension':
        response['data'][0]['embedding'].pop()
    elif mutation == 'duplicate':
        response['data'][1]['index'] = 0
    elif mutation == 'reordered':
        response['data'].reverse()
    elif mutation == 'missing':
        response['data'].pop()
    elif mutation == 'nonfinite':
        response['data'][0]['embedding'][0] = float('nan')
    elif mutation == 'bool':
        response['data'][0]['embedding'][0] = True
    elif mutation == 'norm':
        response['data'][0]['embedding'][0] = 2
    elif mutation == 'usage':
        response['usage']['total_tokens'] = -1
    transport = M.OpenAIEmbeddingTransport(sender(response))
    with pytest.raises(M.ProviderAdapterError):
        call(transport, embedding_body(['first', 'second']))
    assert not transport.recordings


def test_unknown_usage_is_not_zero():
    response = embedding_response()
    response.pop('usage')
    transport = M.OpenAIEmbeddingTransport(sender(response))
    call(transport, embedding_body())
    assert transport.observations[0]['usage'] is None
    response = rerank_response()
    response.pop('meta')
    transport = M.CohereRerankTransport(sender(response))
    call(transport, rerank_body())
    assert transport.observations[0]['usage'] is None


def test_cohere_indices_map_to_membership_in_original_order():
    requests = []
    transport = M.CohereRerankTransport(sender(rerank_response(), requests))
    assert json.loads(call(transport, rerank_body())) == [dict(candidate_id='a', raw_score=.2), dict(candidate_id='b', raw_score=.9)]
    payload = json.loads(requests[0].body)
    assert payload['documents'] == ['alpha', 'beta']
    assert payload['top_n'] == 2 and payload['max_tokens_per_doc'] == 4096
    assert transport.observations[0]['usage']['input_tokens'] == 19


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'outside', 'nonfinite', 'bool', 'reordered', 'model', 'usage'])
def test_cohere_rejects_bad_membership_scores_usage(mutation):
    response = rerank_response()
    if mutation == 'duplicate':
        response['results'][1]['index'] = 1
    elif mutation == 'missing':
        response['results'].pop()
    elif mutation == 'outside':
        response['results'][0]['index'] = 2
    elif mutation == 'nonfinite':
        response['results'][0]['relevance_score'] = float('inf')
    elif mutation == 'bool':
        response['results'][0]['index'] = True
    elif mutation == 'reordered':
        response['results'].reverse()
    elif mutation == 'model':
        response['model'] = 'other-model'
    elif mutation == 'usage':
        response['meta']['billed_units']['input_tokens'] = -1
    with pytest.raises(M.ProviderAdapterError):
        call(M.CohereRerankTransport(sender(response)), rerank_body())


def test_replay_binds_query_model_order_ids_text_and_exact_tape():
    original = M.CohereRerankTransport(sender(rerank_response()))
    expected = call(original, rerank_body())
    replay = M.ReplaySend(original.recordings)
    actual = call(M.CohereRerankTransport(replay), rerank_body())
    assert actual == expected
    replay.assert_complete()
    with pytest.raises(M.ProviderAdapterError, match='replay_missing'):
        call(M.CohereRerankTransport(replay), rerank_body())
    for change in ('query', 'order', 'id', 'text'):
        request = json.loads(rerank_body())
        if change == 'query':
            request['query'] += ' changed'
        elif change == 'order':
            request['candidates'].reverse()
        elif change == 'id':
            request['candidates'][0]['candidate_id'] = 'new'
        else:
            request['candidates'][0]['text'] += ' changed'
        replay = M.ReplaySend(original.recordings)
        with pytest.raises(M.ProviderAdapterError, match='replay_mismatch'):
            call(M.CohereRerankTransport(replay), encoded(request))
        with pytest.raises(M.ProviderAdapterError, match='replay_unconsumed'):
            replay.assert_complete()


def test_invalid_request_never_dispatches_and_errors_are_sanitized():
    requests = []
    transport = M.OpenAIEmbeddingTransport(sender(embedding_response(), requests))
    body = json.loads(embedding_body())
    body['model'] = 'fake_embedding_model_v1'
    with pytest.raises(M.ProviderAdapterError):
        call(transport, encoded(body))
    with pytest.raises(M.ProviderAdapterError):
        call(transport, b'{"model":"secret","model":"duplicate"}')
    assert not requests


def test_injected_transports_feed_actual_core_adapters():
    from cragkit.embeddings import EmbeddingAdapter, EmbeddingPolicy, OPENAI_PROFILE
    from cragkit.reranking import RerankingAdapter, RerankProfile
    class Counter:
        name = 'cl100k_base'
        def count(self, text):
            return 10
    async def run():
        embeddings = EmbeddingAdapter(M.OpenAIEmbeddingTransport(sender(embedding_response())), Counter(),
            profile=OPENAI_PROFILE, policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02))
        batch = await embeddings.embed_query('tiny', deadline=time.monotonic()+10)
        assert not batch.synthetic and batch.usage.total_tokens == 1
        profile = RerankProfile(**json.loads(rerank_body())['profile'])
        reranker = RerankingAdapter(M.CohereRerankTransport(sender(rerank_response())), profile=profile, allow_live=True)
        result = await reranker.rank('tiny query', json.loads(rerank_body())['candidates'], deadline=time.monotonic()+10)
        assert result['order'] == ['b', 'a']
    asyncio.run(run())


def test_injected_send_error_never_exposes_body_or_credentials():
    async def send(request, **kwargs):
        raise RuntimeError('sensitive-provider-body-and-key')
    transport = M.OpenAIEmbeddingTransport(send)
    with pytest.raises(M.ProviderAdapterError, match='^provider_send_failed$'):
        call(transport, embedding_body())
    assert not transport.recordings and not transport.observations


def test_replay_keeps_legitimate_repeated_dispatches_as_separate_entries():
    transport = M.OpenAIEmbeddingTransport(sender(embedding_response()))
    first = call(transport, embedding_body())
    second = call(transport, embedding_body())
    assert first == second and len(transport.recordings) == 2
    replay = M.ReplaySend(transport.recordings)
    target = M.OpenAIEmbeddingTransport(replay)
    assert call(target, embedding_body()) == first
    assert call(target, embedding_body()) == second
    replay.assert_complete()


def test_cohere_fractional_billed_units_are_preserved():
    response = rerank_response()
    response['meta']['billed_units'] = {'search_units': 1.0, 'input_tokens': None}
    transport = M.CohereRerankTransport(sender(response))
    call(transport, rerank_body())
    assert transport.observations[0]['usage'] == {'search_units': 1.0, 'input_tokens': None}


def test_canonical_request_crosses_gate_recording_and_fake_http():
    """Collection must not replace the request class held by other boundaries."""
    import httpx
    import evaluation_payloads
    import provider_http
    import provider_recordings

    assert M.ProviderRequest is evaluation_payloads.ProviderRequest
    assert M.ProviderRequest is provider_recordings.ProviderRequest
    assert M.ProviderRequest is provider_http.ProviderRequest
    request, ids = M.CohereRerankTransport(lambda: None)._prepare(rerank_body())
    gate = evaluation_payloads.EvaluationPayloadGate(['alpha beta'], ['tiny query'])
    assert gate.admission_ceiling(request) == 2 * 32768
    assert provider_recordings.request_metadata(request)['response_items'] == len(ids)
    raw = encoded(rerank_response())
    calls = []

    class ResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw

    def handler(sent):
        calls.append(sent)
        assert sent.content == request.body
        return httpx.Response(200, headers={'content-type': 'application/json'}, stream=ResponseStream())

    async def run():
        async with provider_http.HttpProviderSend({'cohere': 'synthetic-test-key'},
                transport=httpx.MockTransport(handler)) as send:
            response = await send(request, deadline=time.monotonic()+2, max_response_bytes=4096)
        assert provider_recordings.validate_recording(request.provider, request.model, response,
            expected_items=len(ids)) == 19

    asyncio.run(run())
    assert len(calls) == 1
