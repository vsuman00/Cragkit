"""Tiny synthetic metric regressions; no sealed corpus access."""
import copy
import importlib.util
from hashlib import sha256
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('benchmark_metrics', Path(__file__).resolve().parents[2] / 'evaluation/runners/benchmark_metrics.py')
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)


def packet():
    raw = 'café yes'.encode()
    digest = sha256(raw).hexdigest()
    key = ('tenant-a', 'c', 'd', 'r')
    source = dict(zip(METRICS.IDENTITY, key), active=True, canonical_sha256=digest)
    ref = dict(document_id='d', revision_id='r', start_byte=0, end_byte=len(raw), text=raw.decode(), canonical_sha256=digest)
    question = dict(question_id='tiny', tenant_id='tenant-a', collection='c', required_filters=[],
                    answerability='answerable', facets=[dict(facet_id='f', state='supported', support=[ref])])
    evidence = dict(ref, collection='c', source_sha256=digest, text_sha256=digest)
    result = dict(status='sufficient', evidence=[evidence], facets=[dict(facet_id='f', state='supported')])
    return question, result, dict(manifest=dict(documents=[source]), sources={key: raw})


def test_exact_utf8_and_unknown_usage():
    q, r, kw = packet()
    row = METRICS.score_question(q, r, **kw)
    assert all(row[name] == 1 for name in METRICS.RANKING)
    assert not row['false_sufficient']
    report = METRICS.aggregate([row])
    assert report['usage_records'] == [None]
    assert report['false_sufficient']['wilson95'][1] > .7


def test_continuous_union_and_gap():
    q, r, kw = packet()
    original = r['evidence'][0]
    raw = original['text'].encode()
    def fragment(start, end):
        text = raw[start:end]
        return dict(original, start_byte=start, end_byte=end, text=text.decode(), text_sha256=sha256(text).hexdigest())
    r['evidence'] = [fragment(0, 5), fragment(5, len(raw))]
    assert not METRICS.score_question(q, r, **kw)['false_sufficient']
    r['evidence'] = [fragment(0, 3), fragment(5, len(raw))]
    assert METRICS.score_question(q, r, **kw)['false_sufficient']


def test_cross_tenant_collision_does_not_replace_source():
    q, r, kw = packet()
    other = dict(kw['manifest']['documents'][0], tenant_id='tenant-b', canonical_sha256=sha256(b'wrong').hexdigest())
    kw['manifest']['documents'].append(other)
    kw['sources'][('tenant-b', 'c', 'd', 'r')] = b'wrong'
    assert not METRICS.score_question(q, r, **kw)['false_sufficient']
    r['evidence'][0]['tenant_id'] = 'tenant-b'
    row = METRICS.score_question(q, r, **kw)
    assert row['authorization_violation'] and row['false_sufficient']


def test_corruption_inactive_filter_and_identity():
    q, r, kw = packet()
    r['evidence'][0]['text'] = 'invented'
    row = METRICS.score_question(q, r, **kw)
    assert row['fidelity_violation'] and row['document_recall_at_k'] == 0
    q, r, kw = packet()
    kw['manifest']['documents'][0]['active'] = False
    assert METRICS.score_question(q, r, **kw)['authorization_violation']
    q['required_filters'] = [dict(op='eq', field='revision_id', value='r')]
    assert not METRICS.score_question(q, r, **kw)['false_sufficient']
    r['evidence'][0]['revision_id'] = 'unknown'
    assert METRICS.score_question(q, r, **kw)['identity_violation']


def test_conflict_unknown_and_failure_are_separate():
    q, r, kw = packet()
    q['answerability'] = 'partially_answerable'
    q['facets'][0]['state'] = 'conflicting'
    q['facets'][0]['support'].append(copy.deepcopy(q['facets'][0]['support'][0]))
    r.update(status='partial', facets=[dict(facet_id='f', state='unknown')])
    row = METRICS.score_question(q, r, **kw)
    assert row['conflict_miss'] and row['abstention_correct'] and not row['false_sufficient']
    failure = METRICS.score_question(q, dict(operational_failure=True), **kw)
    assert failure['operational_failure'] and failure['degraded'] is None
    assert failure['conflict_miss'] is None
    assert all(failure[name] is None for name in ('abstention', 'false_sufficient', 'abstention_correct', 'required_abstention', 'answerable_abstention'))
    with pytest.raises(ValueError, match='failure_is_not_result'):
        METRICS.score_question(q, dict(operational_failure=True, status='insufficient'), **kw)


def test_configuration_errors_do_not_become_missing_evidence():
    q, r, kw = packet()
    kw['sources'].clear()
    with pytest.raises(ValueError, match='missing_source_snapshot'):
        METRICS.score_question(q, r, **kw)
    with pytest.raises(ValueError, match='invalid_k'):
        METRICS.score_question(q, r, k=True, **kw)


def test_distinct_revision_ranking_and_macro_denominators():
    from math import log2
    q, r, kw = packet()
    distractor = dict(kw['manifest']['documents'][0], document_id='x')
    kw['manifest']['documents'].append(distractor)
    kw['sources'][('tenant-a', 'c', 'x', 'r')] = next(iter(kw['sources'].values()))
    noise = dict(r['evidence'][0], document_id='x')
    r['evidence'] = [noise, dict(noise), r['evidence'][0]]
    row = METRICS.score_question(q, r, k=2, **kw)
    assert row['document_recall_at_k'] == 1
    assert row['reciprocal_rank'] == .5
    assert row['ndcg_at_k'] == pytest.approx(1/log2(3))
    short = METRICS.score_question(q, r, k=1, **kw)
    assert short['document_recall_at_k'] == 0
    assert short['facet_support_recall_at_k'] == 0
    assert not short['false_sufficient']  # sufficiency uses all packed evidence
    q['question_id'] = 'absent'
    q['answerability'] = 'unanswerable'
    q['facets'] = [dict(facet_id='f', state='missing', support=[])]
    absent = METRICS.score_question(q, dict(status='insufficient', evidence=[], facets=[]), k=2, **kw)
    assert METRICS.aggregate([row, absent])['document_recall_at_k']['denominator'] == 1
    with pytest.raises(ValueError, match='mixed_metric_configuration'):
        METRICS.aggregate([row, short])


def test_invalid_evidence_retains_rank_slot():
    q, r, kw = packet()
    noise = dict(r['evidence'][0], document_id='unknown')
    r['evidence'].insert(0, noise)
    row = METRICS.score_question(q, r, k=2, **kw)
    assert row['identity_violation']
    assert row['reciprocal_rank'] == .5
    assert METRICS.score_question(q, r, k=1, **kw)['document_recall_at_k'] == 0


def test_failure_does_not_improve_abstention_quality():
    q, r, kw = packet()
    q['answerability'] = 'unanswerable'
    q['facets'] = [dict(facet_id='f', state='missing', support=[])]
    failed = METRICS.score_question(q, dict(operational_failure=True), **kw)
    report = METRICS.aggregate([failed])
    assert report['operational_failure']['rate'] == 1
    for name in ('false_sufficient', 'abstention', 'answerable_abstention', 'conflict_miss', 'abstention_correct', 'required_abstention'):
        assert report[name]['denominator'] == 0
