from hashlib import sha256
import json
from pathlib import Path
import traceback

import pytest
from pydantic import ValidationError

from cragkit.canonical import canonicalize
from cragkit.errors import InvalidRequest


FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/canonical.json').read_text())


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['id'])
def test_shared_canonical_fixture(case):
    source = bytes.fromhex(case['source_hex']) if 'source_hex' in case else case['source']
    if 'error' in case:
        with pytest.raises(InvalidRequest):
            canonicalize(source, **case['options'])
    else:
        assert canonicalize(source, **case['options']).model_dump(mode='json') == case['expected']


def test_original_and_canonical_digests_and_exact_immutable_spans():
    source = '\ufeffCafé 🙂\r\n\r\nsecond\rthird'
    result = canonicalize(source, target_bytes=7, max_chunk_bytes=12)
    canonical = result.canonical_text.encode('utf-8')
    assert result.source_sha256 == sha256(source.encode('utf-8')).hexdigest()
    assert result.canonical_sha256 == sha256(canonical).hexdigest()
    assert result.source_sha256 != result.canonical_sha256
    assert b''.join(chunk.text.encode('utf-8') for chunk in result.chunks) == canonical
    end = 0
    for ordinal, chunk in enumerate(result.chunks):
        assert chunk.ordinal == ordinal and chunk.start_byte == end
        assert canonical[chunk.start_byte:chunk.end_byte].decode('utf-8') == chunk.text
        assert chunk.text_sha256 == sha256(chunk.text.encode()).hexdigest()
        assert chunk.chunk_id == sha256(f'{result.canonical_sha256}:{chunk.start_byte}:{chunk.end_byte}:{result.chunker_profile}'.encode()).hexdigest()
        end = chunk.end_byte
    with pytest.raises(ValidationError):
        result.canonical_text = 'changed'
    with pytest.raises(ValidationError):
        result.chunks[0].text = 'changed'
    assert isinstance(result.chunks, tuple)


def test_soft_target_keeps_intact_structure_and_only_oversize_is_flagged():
    result = canonicalize('# Heading\n\n```py\nx=1\n```\n\nlast', format='text/markdown', target_bytes=4, max_chunk_bytes=32)
    assert [chunk.text for chunk in result.chunks] == ['# Heading\n\n', '```py\nx=1\n```\n\n', 'last']
    assert not any(chunk.oversized_split for chunk in result.chunks)
    split = canonicalize('🙂🙂🙂', target_bytes=1, max_chunk_bytes=4)
    assert [chunk.text for chunk in split.chunks] == ['🙂', '🙂', '🙂']
    assert all(chunk.oversized_split for chunk in split.chunks)


def test_many_packable_paragraphs_do_not_trigger_final_chunk_limit():
    result = canonicalize('a\n\n' * 2000)
    assert len(result.chunks) < 10
    with pytest.raises(InvalidRequest):
        canonicalize('x' * 4100, target_bytes=4, max_chunk_bytes=4)


def test_explicit_token_counter_has_actual_counts_and_stable_profile():
    result = canonicalize('🙂ab cd ef', target_bytes=32, max_chunk_bytes=32,
                          token_counter=len, tokenizer_id='scalar.v1', token_target=2, max_tokens=3)
    assert result.token_count == len(result.canonical_text)
    assert result.tokenizer_id == 'scalar.v1'
    assert all(chunk.token_count == len(chunk.text) <= 3 for chunk in result.chunks)
    assert all(chunk.oversized_split for chunk in result.chunks)
    assert 'tokenizer=scalar.v1:target=2:max=3' in result.chunker_profile
    zero = canonicalize('text', token_counter=lambda _: 0, tokenizer_id='zero', token_target=1, max_tokens=1)
    assert zero.token_count == zero.chunks[0].token_count == 0


def test_nonmonotonic_counter_uses_actual_counts_not_binary_search():
    def counter(value):
        return {'abcd': 8, 'a': 1, 'ab': 2, 'abc': 1, 'd': 1}.get(value, len(value))
    result = canonicalize('abcd', token_counter=counter, tokenizer_id='nonmono', token_target=2, max_tokens=2)
    assert ''.join(chunk.text for chunk in result.chunks) == 'abcd'
    assert all(chunk.token_count == counter(chunk.text) <= 2 for chunk in result.chunks)


@pytest.mark.parametrize('changes', [
    {'max_source_bytes': True}, {'max_source_bytes': 16_777_217}, {'target_bytes': 0},
    {'target_bytes': 1.0}, {'max_chunk_bytes': 3}, {'max_chunk_bytes': 32769},
    {'token_counter': len}, {'tokenizer_id': 'only-id'}, {'token_target': 2},
    {'max_tokens': 3}, {'token_counter': len, 'tokenizer_id': 'bad id', 'token_target': 1, 'max_tokens': 2},
    {'token_counter': len, 'tokenizer_id': 'valid', 'token_target': 3, 'max_tokens': 2},
])
def test_strict_configuration_rejection(changes):
    with pytest.raises(InvalidRequest):
        canonicalize('source', **changes)


@pytest.mark.parametrize('count', [True, -1, 1.0, float('nan'), float('inf'), 9_007_199_254_740_992, None])
def test_invalid_counter_results_are_safe(count):
    with pytest.raises(InvalidRequest):
        canonicalize('source', token_counter=lambda _: count, tokenizer_id='invalid', token_target=1, max_tokens=1)


def test_callback_failures_and_invalid_utf8_do_not_leak_source_or_causes():
    def broken(_):
        raise RuntimeError('private-source-secret')
    for source, options in [(b'\xffprivate-source-secret', {}), ('source', {
        'token_counter': broken, 'tokenizer_id': 'broken', 'token_target': 1, 'max_tokens': 1,
    })]:
        with pytest.raises(InvalidRequest) as caught:
            canonicalize(source, **options)
        assert 'private-source-secret' not in ''.join(traceback.format_exception(caught.value))
        assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_none_quartet_and_strict_source_types():
    assert canonicalize('text', token_counter=None, tokenizer_id=None, token_target=None, max_tokens=None) == canonicalize('text')
    for source in (None, bytearray(b'text'), 1, ['text']):
        with pytest.raises(InvalidRequest):
            canonicalize(source)


def test_counter_call_budget_is_explicit_and_bounded():
    calls = 0
    def counter(_):
        nonlocal calls
        calls += 1
        return 100
    with pytest.raises(InvalidRequest):
        canonicalize('a' * 70_000, target_bytes=32768, token_counter=counter,
                     tokenizer_id='budget', token_target=100, max_tokens=100)
    assert calls == 65_536


def test_byte_impossible_merges_do_not_consume_token_counter_budget():
    calls = []
    def counter(text):
        calls.append(text)
        return len(text)
    document = canonicalize('a\n\nb\n\nc', target_bytes=1, max_chunk_bytes=8,
                            token_counter=counter, tokenizer_id='scalar.v1',
                            token_target=1, max_tokens=8)
    assert len(calls) == 7
    assert len(document.chunks) == 3


def test_async_counter_is_rejected_without_leaking_an_unawaited_coroutine():
    async def counter(text):
        raise RuntimeError('private counter detail')
    with pytest.raises(InvalidRequest):
        canonicalize('text', token_counter=counter, tokenizer_id='async.v1',
                     token_target=2, max_tokens=4)
