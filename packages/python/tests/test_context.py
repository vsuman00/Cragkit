import hashlib
import json
from pathlib import Path

import pytest

from cragkit.context import Cl100kCounter, count_context, render_context
from cragkit.errors import ContextBudgetTooSmall, InvalidRequest, UnsupportedCapability

ASSET = Path(__file__).resolve().parents[3] / 'artifacts/tokenizers/cl100k_base.tiktoken'


def evidence(text='Quote "🙂"\n<|endoftext|> café', **changes):
    encoded = text.encode('utf-8')
    value = dict(evidence_id='e1', collection='c', document_id='d', revision_id='r',
                 chunk_id='ch', source_locator='file:test', start_byte=7,
                 end_byte=7 + len(encoded), text=text, source_sha256='0' * 64,
                 text_sha256=hashlib.sha256(encoded).hexdigest())
    value.update(changes)
    return value


def counter():
    pytest.importorskip('tiktoken')
    if not ASSET.exists():
        pytest.skip('explicit tokenizer asset not provisioned')
    return Cl100kCounter.from_file(ASSET)


def test_exact_json_preserves_text_and_citation_and_fixed_order():
    item = evidence()
    context = render_context([dict(reversed(list(item.items())))])
    assert context == json.dumps([item], ensure_ascii=False, separators=(',', ':'))
    assert json.loads(context) == [item]
    assert '\\n' in context and '\\"' in context and '🙂' in context
    assert render_context([]) == '[]'


def test_estimate_counts_serialized_bytes_and_reserve():
    item = evidence()
    result = count_context([item], max_tokens=1000, reserve=3)
    assert result == dict(context=render_context([item]),
                         context_tokens=(len(render_context([item]).encode('utf-8')) + 3) // 4,
                         total_tokens=(len(render_context([item]).encode('utf-8')) + 3) // 4 + 3,
                         renderer='cragkit.context.v2', tokenizer=None, counting_mode='estimated')
    assert result['context_tokens'] > len(item['text'].encode('utf-8')) // 4


def test_estimated_exact_fit_and_mandatory_envelope():
    assert count_context([], max_tokens=1, reserve=0)['total_tokens'] == 1
    with pytest.raises(ContextBudgetTooSmall):
        count_context([], max_tokens=256)
    needed = count_context([evidence()], max_tokens=1000, reserve=2)['total_tokens']
    assert count_context([evidence()], max_tokens=needed, reserve=2)['total_tokens'] == needed
    with pytest.raises(ContextBudgetTooSmall):
        count_context([evidence()], max_tokens=needed - 1, reserve=2)


@pytest.mark.parametrize('kwargs', [dict(max_tokens=True), dict(max_tokens=0),
    dict(max_tokens=1_000_001), dict(max_tokens=2, reserve=-1),
    dict(max_tokens=2, reserve=1.0), dict(max_tokens=2, counter=object()), dict(max_tokens=2, counting_mode='unknown')])
def test_invalid_budget_or_estimated_counter(kwargs):
    with pytest.raises(InvalidRequest):
        count_context([], **kwargs)


@pytest.mark.parametrize('value', [None, (), {}, [evidence()] * 65,
    [evidence(text_sha256='1' * 64)], [evidence(), evidence()],
    [evidence(), evidence(evidence_id='e2', source_sha256='1' * 64)],
    [evidence(extra='not allowed')], [{**evidence(), 'text': '\ud800'}]])
def test_invalid_evidence(value):
    with pytest.raises(InvalidRequest):
        render_context(value)


def test_rendered_byte_limit_includes_escaping():
    items = [evidence('\n' * 32768, evidence_id=str(i), chunk_id=str(i)) for i in range(4)]
    with pytest.raises(InvalidRequest):
        render_context(items)


def test_strict_requires_supported_counter_and_mode():
    for kwargs in [dict(counting_mode='strict'),
                   dict(counting_mode='strict', counter=object())]:
        with pytest.raises(UnsupportedCapability):
            count_context([], max_tokens=100, **kwargs)
    with pytest.raises(UnsupportedCapability):
        Cl100kCounter(object())


def test_actual_local_tokenizer_exact_representation_and_special_text():
    actual = counter()
    assert actual.count('hello world') == 2
    assert actual.count('[]') == 1
    item = evidence()
    result = count_context([item], max_tokens=1000, reserve=7, counter=actual, counting_mode='strict')
    assert result['context_tokens'] == actual.count(render_context([item]))
    assert result['total_tokens'] == result['context_tokens'] + 7
    assert result['tokenizer'] == 'cl100k_base'
    assert result['counting_mode'] == 'strict'
    exact = result['total_tokens']
    assert count_context([item], max_tokens=exact, reserve=7, counter=actual,
                         counting_mode='strict')['total_tokens'] == exact
    with pytest.raises(ContextBudgetTooSmall):
        count_context([item], max_tokens=exact - 1, reserve=7, counter=actual, counting_mode='strict')
    with pytest.raises(InvalidRequest):
        actual.count('\ud800')


def test_corrupt_or_missing_asset_is_redacted(tmp_path):
    pytest.importorskip('tiktoken')
    path = tmp_path / 'bad.tiktoken'
    path.write_bytes(b'private invalid asset')
    for candidate in [path, tmp_path / 'absent']:
        with pytest.raises(InvalidRequest) as caught:
            Cl100kCounter.from_file(candidate)
        assert 'private' not in str(caught.value)
        assert caught.value.__cause__ is None


def test_shared_pinned_tokenizer_regressions():
    fixture_path = Path(__file__).resolve().parents[3] / 'contracts/fixtures/context.json'
    fixture = json.loads(fixture_path.read_text())
    actual = counter()
    for item in fixture['token_cases']:
        assert actual.count(item['text']) == item['expected_tokens'], item['id']


def test_shared_serialized_context_counts():
    fixture_path = Path(__file__).resolve().parents[3] / 'contracts/fixtures/context.json'
    fixture = json.loads(fixture_path.read_text())
    actual = counter()
    for item in fixture['cases']:
        if 'expected_error' in item:
            continue
        result = count_context(item['evidence'], max_tokens=item['max_tokens'],
                               reserve=item['reserve'], counting_mode=item['counting_mode'],
                               counter=actual if item['counting_mode'] == 'strict' else None)
        assert result['context'] == item['expected_context'], item['id']
        assert result['context_tokens'] == item['expected_context_tokens'], item['id']
        assert result['total_tokens'] == item['expected_context_tokens'] + item['reserve']


def test_unissued_counter_rejected_and_forged_evidence_revalidated():
    from cragkit.context import Cl100kCounter, count_context, render_context
    from cragkit.errors import UnsupportedCapability, InvalidRequest
    forged = object.__new__(Cl100kCounter)
    with pytest.raises(UnsupportedCapability):
        count_context([], max_tokens=1000, counting_mode='strict', counter=forged)


def test_forged_evidence_model_is_revalidated():
    import hashlib
    from cragkit.contracts import Evidence
    from cragkit.context import render_context
    from cragkit.errors import InvalidRequest
    digest = hashlib.sha256(b'hello').hexdigest()
    item = Evidence(evidence_id='e1', collection='c', document_id='d', revision_id='r',
                    chunk_id='chunk', source_locator='fixture', start_byte=0, end_byte=5,
                    text='hello', source_sha256=digest, text_sha256=digest)
    with pytest.raises(InvalidRequest):
        render_context([item.model_copy(update={'end_byte':99})])
