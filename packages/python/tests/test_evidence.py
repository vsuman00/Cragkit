import asyncio
import hashlib
import time
from pathlib import Path

import pytest

from cragkit.context import Cl100kCounter, count_context
from cragkit.evidence import pack_and_assess
from cragkit.errors import DeadlineExceeded, InvalidRequest


def sample(text, eid='a'):
    digest = hashlib.sha256(text.encode()).hexdigest()
    src = dict(collection='c', document_id=eid, revision_id='r', source_sha256=digest, text=text)
    item = dict(**src, evidence_id=eid, chunk_id=eid, source_locator='fixture', start_byte=0,
                end_byte=len(text.encode()), text_sha256=digest)
    return item, src


def facet(item, fid):
    anchor = {key: item[key] for key in ('collection', 'document_id', 'revision_id', 'source_sha256',
                                       'start_byte', 'end_byte', 'text')}
    return dict(facet_id=fid, question='Which value?', required=True, absence='missing',
                anchors=[dict(claim_id='claim', **anchor)])


def policy(facets):
    return dict(policy_id='review', version='1', query_sha256=hashlib.sha256(b'query').hexdigest(), facets=facets)


def run(items, sources, **options):
    return asyncio.run(pack_and_assess('query', items, sources, deadline=time.monotonic() + 10,
                       max_tokens=options.pop('max_tokens', 10000), reserve=0, surrounding_bytes=0, **options))


def test_emitted_spans_only_and_unknown_without_policy():
    first, src = sample('a')
    result = run([first], [src])
    assert result['status'] == 'partial' and result['policy'] == 'unassessed.v0'
    assert result['rebalance_count'] == 0
    result = run([first], [src], policy=policy([facet(first, 'f')]), max_tokens=1)
    assert result['evidence'] == [] and result['status'] == 'insufficient'
    assert result['facets'][0]['state'] == 'missing' and result['facets'][0]['evidence_ids'] == []


def test_one_rebalance_can_improve_required_support_and_never_recurses():
    first, src1 = sample('a' * 100)
    second, src2 = sample('b', 'b')
    configured = policy([facet(first, 'f1'), facet(second, 'f2'), facet(second, 'f3')])
    needed = count_context([first], max_tokens=10000, reserve=0)['total_tokens']
    original = run([first, second], [src1, src2], policy=configured, max_tokens=needed)
    improved = run([first, second], [src1, src2], policy=configured, max_tokens=needed, rebalance=True)
    assert [e['evidence_id'] for e in original['evidence']] == ['a']
    assert [e['evidence_id'] for e in improved['evidence']] == ['b']
    assert improved['rebalance_count'] == 1 and improved['status'] == 'partial'
    assert [f['state'] for f in improved['facets']] == ['missing', 'supported', 'supported']


def test_equal_rebalance_keeps_original_and_dropped_alias_cannot_support():
    first, src1 = sample('a')
    second, src2 = sample('b', 'b')
    configured = policy([facet(first, 'f1'), facet(second, 'f2')])
    needed = count_context([first], max_tokens=10000, reserve=0)['total_tokens']
    result = run([first, second], [src1, src2], policy=configured, max_tokens=needed, rebalance=True)
    assert result['evidence'] == [first] and result['rebalance_count'] == 1
    assert result['facets'][1]['state'] == 'missing'


def test_strict_exact_budget_and_deadline_cancellation():
    pytest.importorskip('tiktoken')
    asset = Path(__file__).resolve().parents[3] / 'artifacts/tokenizers/cl100k_base.tiktoken'
    if not asset.exists(): pytest.skip('explicit tokenizer asset not provisioned')
    counter = Cl100kCounter.from_file(asset)
    item, src = sample('é🙂')
    needed = count_context([item], max_tokens=10000, reserve=0, counting_mode='strict', counter=counter)['total_tokens']
    result = run([item], [src], max_tokens=needed, counter=counter, counting_mode='strict', policy=policy([facet(item, 'f')]))
    assert result['total_tokens'] == needed and result['status'] == 'sufficient'
    assert run([item], [src], max_tokens=needed - 1, counter=counter, counting_mode='strict')['evidence'] == []
    async def check():
        with pytest.raises(DeadlineExceeded):
            await pack_and_assess('query', [], [], deadline=time.monotonic() - 1, max_tokens=1000)
        task = asyncio.create_task(pack_and_assess('query', [item], [src], deadline=time.monotonic() + 10, max_tokens=1000))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(check())


@pytest.mark.parametrize('options', [dict(rebalance=1), dict(policy={'invalid': True}), dict(counting_mode='unknown')])
def test_invalid_options(options):
    with pytest.raises(InvalidRequest): run([], [], **options)
