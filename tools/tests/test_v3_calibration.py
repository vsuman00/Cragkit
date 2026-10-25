import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from cragkit.assessment import assess_evidence

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('v3_calibration', ROOT / 'evaluation/runners/v3_calibration.py')
CAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAL)


def baseline():
    evaluation = json.loads((ROOT / 'evaluation/reports/V2/V2-08-results.json').read_text())
    evaluation['manifest_sha256'] = hashlib.sha256((ROOT / 'evaluation/corpus/manifest.json').read_bytes()).hexdigest()
    evaluation['development_labels_sha256'] = hashlib.sha256((ROOT / 'evaluation/questions/dev.json').read_bytes()).hexdigest()
    return dict(state='passed', cleanup_verified=True, evaluation=evaluation)


def test_prepare_preserves_same_two_candidates_logical_revisions_and_conflict_policy():
    original = baseline()
    prepared = CAL.prepare(original)
    assert [case['question_id'] for case in prepared['cases']] == ['q01', 'q03', 'q05', 'q08', 'q19', 'q20']
    records = {record['metrics']['question_id']: record for record in original['evaluation']['records'] if record['mode'] == 'hybrid'}
    for case in prepared['cases']:
        assert [[item['document_id'], item['revision_id']] for item in case['evidence']] == records[case['question_id']]['ranked'][:2]
        assert [item['evidence_id'] for item in case['evidence']] == [f"{case['question_id']}-{index}" for index in range(len(case['evidence']))]
        assert all(item['source_locator'] == 'synthetic:v3-calibration' for item in case['evidence'])
        assert all(item['start_byte'] == 0 and item['end_byte'] == len(item['text'].encode()) for item in case['evidence'])
    conflict = next(case for case in prepared['cases'] if case['question_id'] == 'q19')
    assert len({anchor['claim_id'] for anchor in conflict['policy']['facets'][0]['anchors']}) == 2
    assert assess_evidence(conflict['query'], conflict['evidence'], conflict['policy'])['facets'][0]['state'] == 'conflicting'
    original['evaluation']['modes'].clear()
    assert prepared['baseline']['modes']


@pytest.mark.parametrize('mutation', ['state', 'cleanup', 'manifest', 'labels', 'questions', 'duplicate', 'ranked', 'unknown_document'])
def test_prepare_rejects_unverified_or_malformed_baseline(mutation):
    value = baseline()
    hybrid = next(record for record in value['evaluation']['records'] if record['mode'] == 'hybrid' and record['ranked'])
    if mutation == 'state': value['state'] = 'failed'
    elif mutation == 'cleanup': value['cleanup_verified'] = 1
    elif mutation == 'manifest': value['evaluation']['manifest_sha256'] = '0' * 64
    elif mutation == 'labels': value['evaluation']['development_labels_sha256'] = '0' * 64
    elif mutation == 'questions': value['evaluation']['question_ids'].reverse()
    elif mutation == 'duplicate': value['evaluation']['records'].append(hybrid)
    elif mutation == 'ranked': hybrid['ranked'] = [['doc', 'revision', 'extra']]
    else: hybrid['ranked'] = [['unknown', 'r1']]
    with pytest.raises(ValueError, match='invalid_calibration_baseline'): CAL.prepare(value)


def test_replay_uses_real_local_adapter_with_complete_unordered_scores():
    pytest.importorskip('tiktoken')
    if not (ROOT / 'artifacts/tokenizers/cl100k_base.tiktoken').exists(): pytest.skip('tokenizer asset not provisioned')
    case = CAL.prepare(baseline())['cases'][0]
    scores = [dict(candidate_id=item['evidence_id'], raw_score=index) for index, item in enumerate(case['evidence'])][::-1]
    original = copy.deepcopy(case)
    result = asyncio.run(CAL.replay([case], {case['question_id']: scores}))[0]
    assert result['order'] == [item['evidence_id'] for item in reversed(case['evidence'])]
    assert result['before']['counting_mode'] == result['after']['counting_mode'] == 'strict'
    assert result['before']['context_tokens'] <= 20000 - 256
    assert result['after']['policy'] == 'reviewed-development:1'
    assert case == original
    assert CAL.PROFILE.provider == 'cohere' and CAL.PROFILE.model_revision == 'mutable_alias:rerank-v5.0-fast'


@pytest.mark.parametrize('mutation', ['missing', 'invented', 'duplicate', 'nonfinite', 'extra', 'case_duplicate'])
def test_replay_rejects_malformed_recording_before_asset_loading(mutation):
    case = CAL.prepare(baseline())['cases'][0]
    scores = [dict(candidate_id=item['evidence_id'], raw_score=index) for index, item in enumerate(case['evidence'])]
    cases = [case]
    recordings = {case['question_id']: scores}
    if mutation == 'missing': scores.pop()
    elif mutation == 'invented': scores[0]['candidate_id'] = 'invented'
    elif mutation == 'duplicate': scores[1]['candidate_id'] = scores[0]['candidate_id']
    elif mutation == 'nonfinite': scores[0]['raw_score'] = float('nan')
    elif mutation == 'extra': recordings['extra'] = []
    else: cases.append(case)
    with pytest.raises(ValueError, match='invalid_calibration_recording'):
        asyncio.run(CAL.replay(cases, recordings))


def test_metrics_have_explicit_denominators_false_acceptance_and_conflict_detection_misses():
    prepared = CAL.prepare(baseline())
    results = []
    for case in prepared['cases']:
        assessed = assess_evidence(case['query'], case['evidence'], case['policy'])
        packed = dict(evidence=case['evidence'], **assessed)
        results.append(dict(question_id=case['question_id'], before=copy.deepcopy(packed), after=copy.deepcopy(packed), order=[item['evidence_id'] for item in case['evidence']], scores=[]))
    unanswerable = next(result for result in results if result['question_id'] == 'q05')
    unanswerable['after']['status'] = 'sufficient'
    conflict = next(result for result in results if result['question_id'] == 'q19')
    conflict['after']['facets'][0]['state'] = 'unknown'
    report = CAL.evaluate(prepared, results)
    assert report['after']['false_sufficient'] == dict(count=1, denominator=6, rate=1 / 6)
    assert report['after']['conflict_error'] == dict(count=1, denominator=1, rate=1.0)
    assert report['before']['conflict_error']['count'] == 0
    assert report['after']['answerable_abstention']['denominator'] == 4
    assert report['after']['abstention']['denominator'] == 6
    assert report['after']['ranking']['total_questions'] == 6
    assert report['historical_V2_full_candidate_baseline'] == prepared['baseline']['modes']
    assert 'no_two_facet_question_in_live_subset' in report['limitations']
    prepared['protocol_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='invalid_calibration_protocol'): CAL.evaluate(prepared, results)


def test_false_sufficient_uses_raw_reviewed_labels_without_calling_assessor(monkeypatch):
    prepared = CAL.prepare(baseline())
    results = []
    for case in prepared['cases']:
        assessed = assess_evidence(case['query'], case['evidence'], case['policy'])
        packed = dict(evidence=case['evidence'], **assessed)
        results.append(dict(question_id=case['question_id'], before=copy.deepcopy(packed), after=copy.deepcopy(packed), order=[item['evidence_id'] for item in case['evidence']], scores=[]))
    first = results[0]['after']
    irrelevant = next(item for item in first['evidence'] if item['document_id'] != 'retry-policy')
    first['evidence'] = [irrelevant]
    first['status'] = 'sufficient'
    first['facets'][0].update(state='supported', evidence_ids=[irrelevant['evidence_id']])
    # An assessor regression must not change the evaluator's ground truth.
    monkeypatch.setattr(CAL, 'assess_evidence', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('assessor used for ground truth')))
    report = CAL.evaluate(prepared, results)
    assert report['before']['false_sufficient']['count'] == 0
    assert report['after']['false_sufficient'] == dict(count=1, denominator=6, rate=1 / 6)


def test_ranking_order_is_measured_before_label_aware_packing():
    prepared=CAL.prepare(baseline())
    recordings={case['question_id']:[dict(candidate_id=e['evidence_id'],raw_score=i if case['question_id']=='q01' else -i)
                for i,e in enumerate(case['evidence'])] for case in prepared['cases']}
    results=asyncio.run(CAL.replay(prepared['cases'],recordings))
    report=CAL.evaluate(prepared,results)
    assert report['before']['ranking']['reciprocal_rank']==0.7
    assert report['after']['ranking']['reciprocal_rank']==0.8
    assert report['before']['packed_ranking']['reciprocal_rank']==0.8
    assert report['after']['packed_ranking']['reciprocal_rank']==0.8
