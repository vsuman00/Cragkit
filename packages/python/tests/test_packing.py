import asyncio
import hashlib
import json
import time
from pathlib import Path

import pytest

from cragkit.context import Cl100kCounter, count_context
from cragkit.errors import ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest
from cragkit.packing import pack_evidence


def source(text, document='d'):
    return dict(collection='c', document_id=document, revision_id='r', text=text,
                source_sha256=hashlib.sha256(text.encode()).hexdigest())


def seed(src, start=0, end=None, name='e1'):
    data = src['text'].encode()
    end = len(data) if end is None else end
    text = data[start:end].decode()
    return dict(evidence_id=name, collection=src['collection'], document_id=src['document_id'],
                revision_id=src['revision_id'], chunk_id='chunk-' + name,
                source_locator='fixture', start_byte=start, end_byte=end, text=text,
                source_sha256=src['source_sha256'], text_sha256=hashlib.sha256(text.encode()).hexdigest())


def pack(items, sources, **kwargs):
    return asyncio.run(pack_evidence(items, sources, deadline=time.monotonic() + 10,
                                    max_tokens=kwargs.pop('max_tokens', 10000), **kwargs))


def test_unicode_overlap_merges_exact_source_and_stable_span_id():
    src = source('café 🙂 evidence')
    items = [seed(src, 0, 10), seed(src, 6, name='e2')]
    result = pack(items, [src], surrounding_bytes=0)
    item = result['evidence'][0]
    payload = ['c', 'd', 'r', src['source_sha256'], 0, len(src['text'].encode())]
    expected = 'span-' + hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()
    assert item['evidence_id'] == item['chunk_id'] == expected
    assert item['text'] == src['text']
    assert result['aliases'] == {expected: ['e1', 'e2']}
    assert result['merged_count'] == 1 and result['expanded_count'] == 0


def test_paragraph_expansion_preserves_negation_and_code():
    src = source('Heading\n\nDo not delete.\n```py\nx = 1\n```\n\nTail')
    data = src['text'].encode()
    start = data.index(b'delete')
    result = pack([seed(src, start, start + 6)], [src])
    assert result['evidence'][0]['text'] == 'Do not delete.\n```py\nx = 1\n```'
    assert result['expanded_count'] == 1


def test_unreachable_boundary_never_cuts_or_expands_seed():
    src = source('a' * 100 + 'not permitted' + 'z' * 100)
    item = seed(src, 100, 113)
    result = pack([item], [src], surrounding_bytes=2)
    assert result['evidence'] == [item]
    assert result['aliases'] == {'e1': ['e1']}


def test_disjoint_spans_remain_separate_array_items():
    src = source('first omitted last')
    items = [seed(src, 0, 5), seed(src, 14, name='e2')]
    result = pack(items, [src], surrounding_bytes=0)
    assert json.loads(result['context']) == items
    assert result['merged_count'] == 0


def test_tiny_budget_omits_complete_span_and_mandatory_failure_is_typed():
    src = source('Do not cut this.')
    result = pack([seed(src)], [src], max_tokens=1, reserve=0)
    assert result['context'] == '[]' and result['omitted_count'] == 1
    with pytest.raises(ContextBudgetTooSmall):
        pack([], [], max_tokens=1)


def test_facet_priority_then_rank_and_exact_budget():
    src = source('a b c')
    items = [seed(src, 0, 1), seed(src, 2, 3, 'e2'), seed(src, 4, 5, 'e3')]
    needed = count_context([items[2]], max_tokens=10000, reserve=0)['total_tokens']
    result = pack(items, [src], surrounding_bytes=0, facet_evidence=[['e3']],
                  max_tokens=needed, reserve=0)
    assert result['evidence'] == [items[2]]
    assert result['omitted_count'] == 2 and result['total_tokens'] == needed


def test_facet_references_choose_global_rank_and_skip_covered_facet():
    src = source('a b c')
    items = [seed(src, 0, 1), seed(src, 2, 3, 'e2'), seed(src, 4, 5, 'e3')]
    result = pack(items, [src], surrounding_bytes=0, facet_evidence=[['e3', 'e2'], ['e2', 'e1']])
    assert [item['evidence_id'] for item in result['evidence']] == ['e2', 'e1', 'e3']


@pytest.mark.parametrize('mutation', ['digest', 'text', 'missing', 'locator'])
def test_all_seed_sources_checked_even_when_budget_would_omit(mutation):
    src = source('exact source')
    items = [seed(src)]
    sources = [src.copy()]
    if mutation == 'digest':
        sources[0]['source_sha256'] = '0' * 64
    elif mutation == 'text':
        sources[0] = source('other source')
    elif mutation == 'missing':
        sources = []
    else:
        items.append({**items[0], 'evidence_id': 'e2', 'source_locator': 'other'})
    with pytest.raises(IntegrityViolation):
        pack(items, sources, max_tokens=1, reserve=0)


@pytest.mark.parametrize('kwargs', [dict(surrounding_bytes=True), dict(surrounding_bytes=4097),
                                   dict(facet_evidence=[['absent']]), dict(facet_evidence=[['e1', 'e1']])])
def test_invalid_options(kwargs):
    src = source('text')
    with pytest.raises(InvalidRequest):
        pack([seed(src)], [src], **kwargs)


def test_malformed_sources_and_forged_evidence_are_revalidated():
    from cragkit.contracts import Evidence
    src = source('text')
    item = Evidence.model_validate(seed(src)).model_copy(update={'end_byte': 99})
    with pytest.raises(InvalidRequest):
        pack([item], [src])
    for bad in [{**src, 'extra': 1}, {**src, 'text': '\ud800'}, {**src, 'document_id': ''}]:
        with pytest.raises(InvalidRequest):
            pack([], [bad])


def test_source_text_is_preserved_without_implicit_canonicalization():
    src = source('\ufeff\r\n\0  ')
    assert pack([seed(src)], [src])['evidence'][0]['text'] == src['text']


def test_oversized_merged_span_is_omitted_whole():
    src = source('a' * 32768 + 'b')
    result = pack([seed(src, 0, 32768), seed(src, 32768, name='e2')], [src], surrounding_bytes=0)
    assert result['evidence'] == [] and result['omitted_count'] == 2


def test_deadline_and_native_cancellation():
    async def run():
        with pytest.raises(DeadlineExceeded):
            await pack_evidence([], [], deadline=time.monotonic() - 1, max_tokens=1000)
        src = source('text')
        task = asyncio.create_task(pack_evidence([seed(src)], [src],
                                  deadline=time.monotonic() + 10, max_tokens=1000))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())


def test_generated_span_id_skips_all_input_ids_and_preserves_unchanged_seeds():
    src = source('a b c')
    payload = ['c', 'd', 'r', src['source_sha256'], 0, len(src['text'].encode())]
    base = 'span-' + hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()
    other = source('unchanged', document='other')
    third = source('also unchanged', document='third')
    items = [seed(src, 0, 1), seed(other, name=base), seed(third, name=base + '-1')]
    result = pack(items, [src, other, third])
    assert [item['evidence_id'] for item in result['evidence']] == [base + '-2', base, base + '-1']
    assert result['evidence'][1:] == items[1:]
    assert result['aliases'] == {base + '-2': ['e1'], base: [base], base + '-1': [base + '-1']}
    assert result['expanded_count'] == 1 and result['omitted_count'] == 0


def test_caller_mutation_after_yield_cannot_change_source_or_facet_snapshot():
    async def run():
        first, second = source('a'), source('b c', document='second')
        items = [seed(first), seed(second, 0, 1, 'e2'), seed(second, 2, 3, 'e3')]
        sources = [first, second]
        facets = [['e3']]
        task = asyncio.create_task(pack_evidence(items, sources, deadline=time.monotonic() + 10,
                                                max_tokens=10000, surrounding_bytes=0,
                                                facet_evidence=facets))
        await asyncio.sleep(0)
        second['text'] = 'changed after validation began'
        second['source_sha256'] = '0' * 64
        sources.clear()
        facets[0][:] = ['e1']
        facets.append(['missing'])
        result = await task
        assert [item['evidence_id'] for item in result['evidence']] == ['e3', 'e1', 'e2']
        assert [item['text'] for item in result['evidence']] == ['c', 'a', 'b']
        assert result['omitted_count'] == 0
    asyncio.run(run())


def test_canonical_equivalent_unicode_document_ids_merge_separately():
    composed, decomposed = source('abc', document='é'), source('abc', document='e\u0301')
    items = [seed(composed, 0, 2), seed(decomposed, 0, 2, 'e2'),
             seed(composed, 1, 3, 'e3'), seed(decomposed, 1, 3, 'e4')]
    result = pack(items, [composed, decomposed], surrounding_bytes=0)
    assert [item['document_id'] for item in result['evidence']] == ['é', 'e\u0301']
    assert [item['text'] for item in result['evidence']] == ['abc', 'abc']
    assert len(set(item['evidence_id'] for item in result['evidence'])) == 2
    assert list(result['aliases'].values()) == [['e1', 'e3'], ['e2', 'e4']]
    assert result['merged_count'] == 2 and result['omitted_count'] == 0


def test_strict_pinned_counter_exact_fit_and_one_below_omits_whole_span():
    pytest.importorskip('tiktoken')
    asset = Path(__file__).resolve().parents[3] / 'artifacts/tokenizers/cl100k_base.tiktoken'
    if not asset.exists():
        pytest.skip('explicit tokenizer asset not provisioned')
    counter = Cl100kCounter.from_file(asset)
    src = source('café 🙂 <|endoftext|> \u0085x \ufeffx')
    item = seed(src)
    needed = count_context([item], max_tokens=10000, reserve=7,
                           counting_mode='strict', counter=counter)['total_tokens']
    kwargs = dict(reserve=7, counting_mode='strict', counter=counter, surrounding_bytes=0)
    exact = pack([item], [src], max_tokens=needed, **kwargs)
    assert exact['evidence'] == [item]
    assert exact['total_tokens'] == needed and exact['context_tokens'] == needed - 7
    assert exact['tokenizer'] == 'cl100k_base' and exact['counting_mode'] == 'strict'
    below = pack([item], [src], max_tokens=needed - 1, **kwargs)
    assert below['evidence'] == [] and below['context'] == '[]'
    assert below['total_tokens'] == 8 and below['omitted_count'] == 1
