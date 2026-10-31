"""Synthetic-only independent scoring; never reads original reviewed labels."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import evaluation_scoring as S
from cragkit.contracts import parse_result


def digest(text):return sha256(text.encode()).hexdigest()


def fixture():
    docs=[dict(tenant_id='tenant',collection='docs',document_id=name,revision_id='r1',active=True,
               text=text,canonical_sha256=digest(text)) for name,text in [('a','café yes'),('b','Noise.')]]
    query=dict(question_id='q',tenant_id='tenant',collection='docs',query='What?',required_filters=[])
    packet=dict(revision='EVX-r1',documents=docs,queries=[query])
    support=dict(document_id='a',revision_id='r1',start_byte=0,end_byte=len(docs[0]['text'].encode()),
                 text=docs[0]['text'],canonical_sha256=docs[0]['canonical_sha256'])
    reviewed=[dict(query,answerability='answerable',facets=[dict(facet_id='f',question='What is supported?',state='supported',support=[support])])]
    receipts=[dict(tenant_id='tenant',collection='docs',document_id=doc['document_id'],logical_revision_id='r1',
        revision_id=digest('native-'+doc['document_id']),generation_id=digest('generation-'+doc['document_id']),
        canonical_sha256=doc['canonical_sha256'],embedding_profile='fake_embedding_1536_v1',active=True) for doc in docs]
    evidence=[dict(evidence_id='ev-'+doc['document_id'],collection='docs',document_id=doc['document_id'],
        revision_id=receipt['revision_id'],chunk_id='chunk-'+doc['document_id'],source_locator='synthetic:score',
        start_byte=0,end_byte=len(doc['text'].encode()),text=doc['text'],source_sha256=doc['canonical_sha256'],
        text_sha256=digest(doc['text'])) for doc,receipt in zip(docs,receipts,strict=True)]
    rows=[]
    for mode in S.MODES:
        result=parse_result(dict(request_id='mode-'+mode,status='insufficient',evidence=copy.deepcopy(evidence),
            usage=dict(provider_calls=2 if mode=='reranked_hybrid' else 1))).model_dump(mode='json')
        rows.append(dict(question_id='q',mode=mode,result=result,latency_ms=1))
    observation=dict(revision='EVX-r1',runtime='python',kind='mechanics',receipts=receipts,rows=rows,cleanup_verified=True)
    audit=dict(question_id='q',mode='reranked_hybrid',query_sha256=digest(query['query']),profile_id='fake_reranker_v1',
        candidates=[dict(candidate_id=item['evidence_id'],text_sha256=item['text_sha256']) for item in reversed(evidence)])
    return packet,reviewed,observation,[audit]


def test_full_reports_preserve_raw_wires_and_use_audited_shortlist_not_hybrid():
    packet,labels,observation,audit=fixture()
    original=copy.deepcopy((packet,labels,observation,audit))
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    assert report['ready'] and report['row_count']==5 and report['question_count']==1
    assert report['same_shortlist']['verified']
    comparison=report['same_shortlist']['comparisons'][0]
    assert comparison['baseline_score']['reciprocal_rank']==.5
    assert comparison['reranked_score']['reciprocal_rank']==1
    assert comparison['delta_reciprocal_rank']==.5
    assert report['modes']['hybrid']['scores'][0]['reciprocal_rank']==1
    assert report['paired_deltas']['reranked_mrr_minus_same_shortlist_hybrid']['mean']==.5
    assert (packet,labels,observation,audit)==original
    json.dumps(report,allow_nan=False)


@pytest.mark.parametrize('mutation',['missing_mode','duplicate_mode','label_query','label_scope','label_filter','support_text','receipt_digest','receipt_logical','ambiguous_alias'])
def test_invalid_identity_denominators_or_reviewed_binding_refuse(mutation):
    packet,labels,observation,audit=fixture()
    if mutation=='missing_mode':observation['rows'].pop()
    elif mutation=='duplicate_mode':observation['rows'][-1]['mode']='dense'
    elif mutation=='label_query':labels[0]['query']='changed question'
    elif mutation=='label_scope':labels[0]['tenant_id']='foreign'
    elif mutation=='label_filter':labels[0]['required_filters']=[dict(op='eq',field='document_id',value='b')]
    elif mutation=='support_text':labels[0]['facets'][0]['support'][0]['text']='invented'
    elif mutation=='receipt_digest':observation['receipts'][0]['canonical_sha256']='0'*64
    elif mutation=='receipt_logical':observation['receipts'][0]['logical_revision_id']='unknown'
    else:
        duplicate=copy.deepcopy(packet['documents'][0]);duplicate.update(revision_id='r2',active=False)
        packet['documents'].insert(0,duplicate)
        receipt=copy.deepcopy(observation['receipts'][0]);receipt.update(logical_revision_id='r2',active=False)
        observation['receipts'].insert(0,receipt)
    with pytest.raises(S.EvaluationScoringError,match='invalid_evaluation_scoring'):
        S.score_observation(packet,labels,observation,rerank_inputs=audit)


@pytest.mark.parametrize('mutation',['missing','text_hash','dropped','duplicate','query_hash','candidate_id'])
def test_shortlist_changes_never_invent_a_baseline(mutation):
    packet,labels,observation,audit=fixture()
    if mutation=='missing':audit=[]
    elif mutation=='text_hash':audit[0]['candidates'][0]['text_sha256']='0'*64
    elif mutation=='dropped':observation['rows'][3]['result']['evidence'].pop()
    elif mutation=='duplicate':audit.append(copy.deepcopy(audit[0]))
    elif mutation=='query_hash':audit[0]['query_sha256']='0'*64
    else:audit[0]['candidates'][0]['candidate_id']='unknown-evidence'
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    assert not report['ready'] and not report['same_shortlist']['verified']
    assert report['same_shortlist']['comparisons'][0]['baseline_score'] is None
    assert report['paired_deltas']['reranked_mrr_minus_same_shortlist_hybrid']['mean'] is None
    assert all(report['modes'][mode]['aggregate']['total_questions']==1 for mode in S.MODES)


def test_operational_failure_preserves_frozen_denominators():
    packet,labels,observation,audit=fixture()
    observation['rows'][1]['result']=dict(operational_failure=True,error_code='provider_unavailable')
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    aggregate=report['modes']['dense']['aggregate']
    assert aggregate['total_questions']==aggregate['document_recall_at_k']['denominator']==1
    assert aggregate['document_recall_at_k']['mean']==0
    assert aggregate['operational_failure']['count']==1
    assert aggregate['false_sufficient']['denominator']==aggregate['abstention']['denominator']==0
    assert report['counts']['operational_failures']==1 and not report['ready']


def test_catastrophic_failure_without_receipts_keeps_all_five_rows():
    packet,labels,observation,_=fixture()
    observation['receipts']=[];observation['cleanup_verified']=False
    for row in observation['rows']:row['result']=dict(operational_failure=True,error_code='provider_unavailable')
    report=S.score_observation(packet,labels,observation)
    assert report['counts']['operational_failures']==5 and report['row_count']==5 and not report['ready']
    assert all(mode['aggregate']['total_questions']==1 for mode in report['modes'].values())
    observation['cleanup_verified']=True
    with pytest.raises(S.EvaluationScoringError):S.score_observation(packet,labels,observation)


def test_unknown_native_identity_cannot_accidentally_match_logical_alias_or_promote_rank():
    packet,labels,observation,audit=fixture()
    first=copy.deepcopy(observation['rows'][0]['result']['evidence'][0])
    first.update(evidence_id='unknown-native',revision_id='r1')
    observation['rows'][0]['result']['evidence'].insert(0,first)
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    score=report['modes']['lexical']['scores'][0]
    assert score['reciprocal_rank']==.5 and score['identity_violation']
    assert report['counts']['identity_violations']==1 and not report['ready']


def test_genuine_shaped_wrong_excerpt_counts_fidelity_and_false_sufficiency_independently():
    packet,labels,observation,audit=fixture()
    result=observation['rows'][0]['result']
    result['evidence']=[copy.deepcopy(result['evidence'][1])]
    result['status']='sufficient';result['versions']['policy']='synthetic-assessed'
    result['facets']=[dict(facet_id='f',question='What?',state='supported',required=True,evidence_ids=['ev-b'],
                           assessment_method='synthetic',assessment_version='1')]
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    assert report['counts']['false_sufficient']==1 and not report['ready']
    result['status']='insufficient';result['facets']=[]
    item=copy.deepcopy(observation['rows'][1]['result']['evidence'][0])
    item.update(text='wrong!',end_byte=6,text_sha256=digest('wrong!'))
    result['evidence']=[item]
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    assert report['counts']['fidelity_violations']==1


def test_successful_empty_without_rerank_dispatch_has_empty_verified_baseline():
    packet,labels,observation,_=fixture()
    for row in observation['rows']:
        row['result']['evidence']=[];row['result']['usage']['provider_calls']=1
    report=S.score_observation(packet,labels,observation)
    assert report['same_shortlist']['verified']
    assert report['same_shortlist']['baseline']['scores'][0]['reciprocal_rank']==0
    observation['rows'][3]['result']['usage']['provider_calls']=2
    assert not S.score_observation(packet,labels,observation)['same_shortlist']['verified']


def test_full_tenant_identity_prevents_cross_tenant_revision_alias_binding():
    packet,labels,observation,audit=fixture()
    other=copy.deepcopy(packet['documents'][0]);other['tenant_id']='tenant-b'
    packet['documents'].append(other)
    receipt=copy.deepcopy(observation['receipts'][0]);receipt.update(tenant_id='tenant-b',revision_id=digest('tenant-b-native'))
    observation['receipts'].append(receipt)
    observation['rows'][0]['result']['evidence'][0]['revision_id']=receipt['revision_id']
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    assert report['modes']['lexical']['scores'][0]['identity_violation']
    assert report['modes']['lexical']['scores'][0]['document_recall_at_k']==0


def test_unanswerable_only_keeps_null_rank_denominators_and_cannot_pass_delta_targets():
    packet,labels,observation,_=fixture()
    labels[0]['answerability']='unanswerable'
    labels[0]['facets'][0].update(state='missing',support=[])
    for row in observation['rows']:
        row['result']['evidence']=[];row['result']['usage']['provider_calls']=1
    report=S.score_observation(packet,labels,observation)
    assert report['same_shortlist']['verified'] and not report['ready']
    for mode in report['modes'].values():
        assert mode['aggregate']['document_recall_at_k']==dict(mean=None,denominator=0)
    assert all(delta['mean'] is None and delta['denominator']==0 for delta in report['paired_deltas'].values())


def test_reviewed_conflict_unknown_is_an_abstention_and_detection_miss():
    packet,labels,observation,audit=fixture()
    labels[0]['answerability']='partially_answerable'
    labels[0]['facets'][0]['state']='conflicting'
    other=packet['documents'][1]
    labels[0]['facets'][0]['support'].append(dict(document_id='b',revision_id='r1',start_byte=0,
        end_byte=len(other['text'].encode()),text=other['text'],canonical_sha256=other['canonical_sha256']))
    for row in observation['rows']:
        row['result']['facets']=[dict(facet_id='f',question='Conflict?',state='unknown')]
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    for mode in report['modes'].values():
        assert mode['aggregate']['conflict_miss']['count']==mode['aggregate']['conflict_miss']['denominator']==1
        assert mode['aggregate']['abstention_correct']['rate']==1
        assert mode['aggregate']['false_sufficient']['count']==0


def test_packed_span_change_with_same_evidence_id_invalidates_shortlist_comparison():
    packet,labels,observation,audit=fixture()
    item=observation['rows'][3]['result']['evidence'][0]
    item.update(text='café',end_byte=len('café'.encode()),text_sha256=digest('café'))
    report=S.score_observation(packet,labels,observation,rerank_inputs=audit)
    assert report['same_shortlist']['comparisons'][0]['reason']=='candidate_text_changed'
    assert report['modes']['reranked_hybrid']['scores'][0]['facet_support_recall_at_k']==0
    assert not report['ready']


def test_label_free_observation_validation_does_not_score_or_consume_labels(monkeypatch):
    packet,_,observation,_=fixture()
    def forbidden(*args,**kwargs):pytest.fail('label-free validation entered scoring')
    monkeypatch.setattr(S,'_labels',forbidden)
    original=copy.deepcopy(observation)
    assert S.validate_observation(packet,observation) is None
    assert observation==original


@pytest.mark.parametrize('mutation',['missing_mode','duplicate_question_mode','missing_receipt','wrong_receipt_hash'])
def test_label_free_observation_validation_rejects_incomplete_matrix_or_receipts(mutation):
    packet,_,observation,_=fixture()
    if mutation=='missing_mode':observation['rows'].pop()
    elif mutation=='duplicate_question_mode':observation['rows'][-1]['mode']='lexical'
    elif mutation=='missing_receipt':observation['receipts'].pop()
    else:observation['receipts'][0]['canonical_sha256']='0'*64
    with pytest.raises(S.EvaluationScoringError,match='invalid_evaluation_scoring'):
        S.validate_observation(packet,observation)
