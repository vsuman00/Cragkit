"""Hand-calculated metric examples independent of the reviewed corpus."""
import importlib.util
from math import log2
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'dense_metrics', Path(__file__).resolve().parents[2] / 'evaluation/runners/dense_metrics.py'
)
assert SPEC and SPEC.loader
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)


def span(doc='a', rev='r1', start=10, end=20):
    return dict(document_id=doc, revision_id=rev, start_byte=start, end_byte=end)


def facet(*refs, state='supported'):
    return dict(state=state, support=list(refs))


def question(*facets, answerability='answerable'):
    return dict(question_id='unit-question', answerability=answerability, facets=list(facets))


def test_distinct_document_ranks_and_hand_calculated_scores():
    label = question(facet(span('a')), facet(span('b')))
    evidence = [span('x'), span('x'), span('a'), span('a'), span('b')]
    row = METRICS.score_question(label, evidence, k=3)
    assert row['positive_document_count'] == 2
    assert row['document_recall_at_k'] == 1
    assert row['reciprocal_rank'] == 0.5
    assert row['ndcg_at_k'] == pytest.approx((1/log2(3) + 1/log2(4)) / (1 + 1/log2(3)))
    assert row['facet_support_recall_at_k'] == 1
    short = METRICS.score_question(label, evidence, k=2)
    assert short['document_recall_at_k'] == 0.5
    assert short['facet_support_recall_at_k'] == 0.5


def test_empty_positive_result_and_top_k_miss():
    label = question(facet(span()))
    for evidence in ([], [span('x'), span('a')]):
        row = METRICS.score_question(label, evidence, k=1)
        assert all(row[field] == 0 for field in (
            'document_recall_at_k', 'reciprocal_rank', 'ndcg_at_k', 'facet_support_recall_at_k'))


def test_span_union_covers_adjacency_but_not_gaps_or_partial_quotes():
    label = question(facet(span()))
    for evidence in ([span(start=10, end=19)], [span(start=11, end=20)],
                     [span(start=10, end=14), span(start=15, end=20)]):
        row = METRICS.score_question(label, evidence)
        assert row['document_recall_at_k'] == 1
        assert row['facet_support_recall_at_k'] == 0
    assert METRICS.score_question(label, [span(start=15), span(end=15)])['facet_support_recall_at_k'] == 1


def test_conflict_requires_both_sides_and_missing_facets_are_excluded():
    label = question(facet(span('a'), span('b'), state='conflicting'), facet(state='missing'),
                     answerability='partially_answerable')
    assert METRICS.score_question(label, [span('a')])['facet_support_recall_at_k'] == 0
    assert METRICS.score_question(label, [span('a'), span('b')])['facet_support_recall_at_k'] == 1


def test_supported_facet_accepts_alternative_reference():
    label = question(facet(span('a'), span('b')))
    row = METRICS.score_question(label, [span('b')])
    assert row['document_recall_at_k'] == 0.5
    assert row['facet_support_recall_at_k'] == 1


def test_revision_identity_and_cutoff_apply_to_span_coverage():
    label = question(facet(span('a', rev='r2')))
    row = METRICS.score_question(label, [span('a'), span('a', rev='r2')], k=1)
    assert row['document_recall_at_k'] == 0
    assert row['facet_support_recall_at_k'] == 0
    assert METRICS.score_question(label, [span('a'), span('a', rev='r2')], k=2)['reciprocal_rank'] == 0.5


def test_unanswerable_diagnostic_and_macro_denominators():
    absent = question(facet(state='missing'), answerability='unanswerable')
    empty = METRICS.score_question(absent, [])
    returned = METRICS.score_question(absent, [span('x')])
    positive = METRICS.score_question(question(facet(span())), [span()])
    assert returned['document_recall_at_k'] is None
    assert returned['reciprocal_rank'] is None
    assert returned['ndcg_at_k'] is None
    assert returned['facet_support_recall_at_k'] is None
    assert positive['evidence_on_unanswerable'] is None
    result = METRICS.aggregate([empty, returned, positive])
    assert result['total_questions'] == 3
    assert result['positive_questions'] == 1
    assert result['unanswerable_questions'] == 2
    assert result['document_recall_at_k'] == 1
    assert result['facet_support_recall_at_k'] == 1
    assert result['evidence_on_unanswerable_rate'] == 0.5
    assert METRICS.aggregate([])['document_recall_at_k'] is None
    assert METRICS.aggregate([])['evidence_on_unanswerable_rate'] is None


@pytest.mark.parametrize('k', [0, -1, True, 1.5, '5', None])
def test_bad_k_uses_fixed_redacted_code(k):
    with pytest.raises(ValueError, match='^invalid_k$'):
        METRICS.score_question(question(), [], k)


@pytest.mark.parametrize('evidence', [None, {}, [None], [{}], [span(doc='')],
    [span(rev=12)], [span(start=True)], [span(start=-1)], [span(end=10)],
    [span(end=9)], [span(end=20.0)], [span(), {'private': 'source text'}]])
def test_malformed_evidence_uses_fixed_redacted_code(evidence):
    with pytest.raises(ValueError, match='^malformed_evidence$'):
        METRICS.score_question(question(), evidence)
