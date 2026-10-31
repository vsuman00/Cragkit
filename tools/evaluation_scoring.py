"""Pure independent scoring of copied logical views of native evaluation wires."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import re
from statistics import fmean

from cragkit.contracts import parse_result
from cragkit.contracts._validation import identity, native_json
from retrieval_evaluation import MODES, document_order, query_variants, validate_packet

_SPEC = importlib.util.spec_from_file_location('_evaluation_frozen_metrics',
    Path(__file__).resolve().parents[1] / 'evaluation/runners/benchmark_metrics.py')
_METRICS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_METRICS)
_HASH = re.compile('[0-9a-f]{64}')


class EvaluationScoringError(ValueError):
    """Content-free scoring input refusal."""


def _require(condition):
    if not condition:
        raise ValueError()


def _labels(packet, reviewed):
    _require(type(reviewed) is list and len(reviewed) == len(packet['queries']))
    sources = {(d['tenant_id'],d['collection'],d['document_id'],d['revision_id']):d
               for d in packet['documents']}
    queries = {q['question_id']:q for q in packet['queries']}
    labels, facet_ids = {}, set()
    for question in reviewed:
        _require(type(question) is dict and set(question) == {'question_id','tenant_id','collection','query','required_filters','answerability','facets'})
        qid = question['question_id']
        _require(qid in queries and qid not in labels)
        query = queries[qid]
        _require(all(question[field] == query[field] for field in query))
        filters = {}
        for item in question['required_filters']:
            _require(type(item) is dict and set(item) == {'op','field','value'} and item['op'] == 'eq'
                     and item['field'] in ('document_id','revision_id') and type(item['value']) is str
                     and item['field'] not in filters)
            filters[item['field']] = item['value']
        _require(type(question['facets']) is list and 1 <= len(question['facets']) <= 32)
        states = []
        for facet in question['facets']:
            _require(type(facet) is dict and set(facet) == {'facet_id','question','state','support'})
            identity(facet['facet_id'])
            _require(facet['facet_id'] not in facet_ids and type(facet['question']) is str and bool(facet['question'].strip()))
            facet_ids.add(facet['facet_id'])
            _require(facet['state'] in ('supported','missing','conflicting') and type(facet['support']) is list)
            spans = set()
            for support in facet['support']:
                _require(type(support) is dict and set(support) == {'document_id','revision_id','start_byte','end_byte','text','canonical_sha256'})
                key = (question['tenant_id'],question['collection'],support['document_id'],support['revision_id'])
                _require(key in sources)
                doc = sources[key]
                raw = doc['text'].encode('utf-8')
                start, end = support['start_byte'], support['end_byte']
                _require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw))
                _require(type(support['text']) is str and raw[start:end].decode('utf-8') == support['text']
                         and support['canonical_sha256'] == doc['canonical_sha256'])
                _require(all(doc[field] == value for field,value in filters.items())
                         and (doc['active'] or 'revision_id' in filters))
                span = (*key,start,end)
                _require(span not in spans)
                spans.add(span)
            count = len(spans)
            _require((facet['state'] == 'missing' and count == 0)
                     or (facet['state'] == 'supported' and count >= 1)
                     or (facet['state'] == 'conflicting' and count >= 2))
            states.append(facet['state'])
        answerability = question['answerability']
        _require((answerability == 'answerable' and all(state == 'supported' for state in states))
                 or (answerability == 'unanswerable' and all(state == 'missing' for state in states))
                 or (answerability == 'partially_answerable' and any(state != 'missing' for state in states)
                     and any(state != 'supported' for state in states)))
        labels[qid] = deepcopy(question)
    return labels


def _observation(packet, observation):
    _require(type(observation) is dict and set(observation) == {'revision','runtime','kind','receipts','rows','cleanup_verified'}
             and observation['revision'] == 'EVX-r1' and observation['runtime'] in ('python','node')
             and observation['kind'] in ('mechanics','provider','replay') and type(observation['cleanup_verified']) is bool)
    documents = sorted(packet['documents'],key=document_order)
    _require(type(observation['receipts']) is list)
    if not observation['receipts']:
        _require(observation['cleanup_verified'] is False and type(observation['rows']) is list
                 and len(observation['rows']) == len(packet['queries'])*len(MODES)
                 and all(type(row) is dict and type(row.get('result')) is dict
                         and row['result'].get('operational_failure') is True for row in observation['rows']))
        documents = []
    else:
        _require(len(observation['receipts']) == len(documents))
    aliases = {}
    expected_profile = 'fake_embedding_1536_v1' if observation['kind'] == 'mechanics' else 'openai_te3small_1536_r1'
    for document,receipt in zip(documents,observation['receipts'],strict=True):
        _require(type(receipt) is dict and set(receipt) == {'tenant_id','collection','document_id','logical_revision_id','revision_id','generation_id','canonical_sha256','embedding_profile','active'})
        _require(all(receipt[field] == document[field] for field in ('tenant_id','collection','document_id','canonical_sha256','active'))
                 and type(receipt['active']) is bool and receipt['logical_revision_id'] == document['revision_id']
                 and receipt['embedding_profile'] == expected_profile)
        for field in ('revision_id','generation_id'):
            _require(type(receipt[field]) is str and _HASH.fullmatch(receipt[field]) is not None)
        key = tuple(receipt[field] for field in ('tenant_id','collection','document_id','revision_id'))
        _require(key not in aliases)
        aliases[key] = receipt['logical_revision_id']
    _require(type(observation['rows']) is list and len(observation['rows']) == len(packet['queries'])*len(MODES))
    rows = {}
    expected = [(query['question_id'],mode) for query in packet['queries'] for mode in MODES]
    for row,pair in zip(observation['rows'],expected,strict=True):
        _require(type(row) is dict and set(row) == {'question_id','mode','result','latency_ms'}
                 and (row['question_id'],row['mode']) == pair and type(row['latency_ms']) in (int,float)
                 and 0 <= row['latency_ms'] <= 900000)
        result = row['result']
        if type(result) is dict and result.get('operational_failure') is True:
            _require(set(result) == {'operational_failure','error_code'} and type(result['error_code']) is str
                     and re.fullmatch('[a-z_]{1,100}',result['error_code']) is not None)
            rows[pair] = deepcopy(result)
        else:
            rows[pair] = parse_result(result).model_dump(mode='json')
    return aliases,rows



def validate_observation(packet, observation):
    """Validate the complete worker matrix without reading or accepting labels."""
    failed = False
    try:
        snapshot = validate_packet(packet)
        _observation(snapshot, observation)
    except Exception:
        failed = True
    if failed:
        raise EvaluationScoringError('invalid_evaluation_scoring')
    return None


def _metric_view(question, result, aliases):
    view = deepcopy(result)
    for evidence in view.get('evidence',[]):
        key = (question['tenant_id'],evidence['collection'],evidence['document_id'],evidence['revision_id'])
        # NUL cannot occur in a validated packet identity. Retain distinct invalid
        # rank slots even if an unmapped native ID resembles a logical alias.
        evidence['revision_id'] = aliases.get(key, '\0unmapped:'+evidence['revision_id'])
    return view


def _audits(packet, kind, values):
    groups, valid = {}, True
    expected_profile = 'fake_reranker_v1' if kind == 'mechanics' else 'cohere_v5fast_evaluation_v1'
    queries = {q['question_id']:q for q in packet['queries']}
    if type(values) not in (list,tuple) or len(values) > 180:
        return {},False
    for event in values:
        try:
            _require(type(event) is dict and set(event) == {'question_id','mode','query_sha256','profile_id','candidates'}
                     and event['question_id'] in queries and event['mode'] in ('reranked_hybrid','corrective')
                     and event['profile_id'] == expected_profile)
            query = queries[event['question_id']]['query']
            approved = [query] + ([item['query'] for item in query_variants(query)] if event['mode'] == 'corrective' else [])
            _require(event['query_sha256'] in {sha256(text.encode()).hexdigest() for text in approved})
            _require(type(event['candidates']) is list and 1 <= len(event['candidates']) <= 15)
            seen = set()
            for candidate in event['candidates']:
                _require(type(candidate) is dict and set(candidate) == {'candidate_id','text_sha256'})
                identity(candidate['candidate_id'])
                _require(candidate['candidate_id'] not in seen and type(candidate['text_sha256']) is str
                         and _HASH.fullmatch(candidate['text_sha256']) is not None)
                seen.add(candidate['candidate_id'])
            groups.setdefault((event['question_id'],event['mode']),[]).append(deepcopy(event))
        except Exception:
            valid = False
    return groups,valid


def _paired(left, right, field, expected, *, verified=True):
    values = [left[qid][field]-right[qid][field] for qid in left if qid in right
              if left[qid][field] is not None and right[qid][field] is not None]
    return dict(mean=fmean(values) if values and verified else None,
                denominator=len(values), expected_denominator=expected)


def score_observation(packet, reviewed_questions, observation, *, rerank_inputs=(), k=5):
    failed = False
    try:
        _require(type(k) is int and 1 <= k <= 1000)
        packet = validate_packet(packet)
        native_json(reviewed_questions)
        labels = _labels(packet,reviewed_questions)
        aliases,rows = _observation(packet,observation)
        manifest = dict(documents=[{key:doc[key] for key in ('tenant_id','collection','document_id','revision_id','canonical_sha256','active')}
                                   for doc in packet['documents']])
        sources = {(doc['tenant_id'],doc['collection'],doc['document_id'],doc['revision_id']):doc['text'].encode()
                   for doc in packet['documents']}
        by_mode,views = {},{}
        for mode in MODES:
            scores = []
            for query in packet['queries']:
                qid = query['question_id']
                views[qid,mode] = _metric_view(labels[qid],rows[qid,mode],aliases)
                scores.append(_METRICS.score_question(labels[qid],views[qid,mode],manifest=manifest,sources=sources,k=k))
            by_mode[mode] = dict(scores=scores,aggregate=_METRICS.aggregate(scores))
        audits,audits_valid = _audits(packet,observation['kind'],rerank_inputs)
        comparisons,baseline = [],[]
        for query in packet['queries']:
            qid = query['question_id']
            result = rows[qid,'reranked_hybrid']
            entries = audits.get((qid,'reranked_hybrid'),[])
            reason = None
            if not audits_valid:reason='invalid_audit'
            elif result.get('operational_failure') is True:reason='operational_failure'
            elif len(entries)>1:reason='multiple_audits'
            elif not entries and not result['evidence'] and result['usage']['provider_calls']<=1:
                ordered=[]
            elif not entries:reason='missing_audit'
            else:
                candidates=entries[0]['candidates']
                evidence={item['evidence_id']:item for item in result['evidence']}
                if set(evidence)!={item['candidate_id'] for item in candidates}:reason='candidate_membership_changed'
                elif any(evidence[item['candidate_id']]['text_sha256']!=item['text_sha256'] for item in candidates):reason='candidate_text_changed'
                else:ordered=[evidence[item['candidate_id']] for item in candidates]
            score=None
            if reason is None:
                original=deepcopy(result)
                original['evidence']=ordered
                original['usage']=None  # Counterfactual order has no measured usage.
                view=_metric_view(labels[qid],original,aliases)
                score=_METRICS.score_question(labels[qid],view,manifest=manifest,sources=sources,k=k)
                baseline.append(score)
            actual = next(row for row in by_mode['reranked_hybrid']['scores'] if row['question_id'] == qid)
            delta = (actual['reciprocal_rank']-score['reciprocal_rank']
                     if score is not None and actual['reciprocal_rank'] is not None and score['reciprocal_rank'] is not None else None)
            comparisons.append(dict(question_id=qid,verified=reason is None,reason=reason,
                baseline_score=score,reranked_score=actual,delta_reciprocal_rank=delta))
        verified=all(item['verified'] for item in comparisons)
        indexed={mode:{row['question_id']:row for row in by_mode[mode]['scores']} for mode in MODES}
        base_index={row['question_id']:row for row in baseline}
        positives=sum(row['positive_document_count']>0 for row in by_mode['lexical']['scores'])
        supported=sum(row['support_facet_count']>0 for row in by_mode['lexical']['scores'])
        deltas=dict(hybrid_document_recall_minus_lexical=_paired(indexed['hybrid'],indexed['lexical'],'document_recall_at_k',positives),
            reranked_mrr_minus_same_shortlist_hybrid=_paired(indexed['reranked_hybrid'],base_index,'reciprocal_rank',positives,verified=verified),
            corrective_support_recall_minus_reranked=_paired(indexed['corrective'],indexed['reranked_hybrid'],'facet_support_recall_at_k',supported))
        counts={name+'_violations':sum(mode['aggregate']['violation_counts'][name] for mode in by_mode.values())
                for name in ('identity','authorization','fidelity')}
        counts['invariant_violations']=sum(counts.values())
        counts['operational_failures']=sum(mode['aggregate']['operational_failure']['count'] for mode in by_mode.values())
        counts['false_sufficient']=sum(mode['aggregate']['false_sufficient']['count'] for mode in by_mode.values())
        targets=dict(invariant_violations_zero=counts['invariant_violations']==0,
            operational_failures_zero=counts['operational_failures']==0,false_sufficient_zero=counts['false_sufficient']==0,
            same_shortlist_verified=verified,cleanup_verified=observation['cleanup_verified'])
        targets.update({name:value['mean'] is not None and value['mean']>=0 and value['denominator']==value['expected_denominator']
                        for name,value in deltas.items()})
        report=dict(revision='ECR-r1',metric_version=_METRICS.METRIC_VERSION,k=k,question_count=len(labels),row_count=len(rows),
            modes=by_mode,same_shortlist=dict(verified=verified,comparisons=comparisons,
                baseline=dict(scores=baseline,aggregate=_METRICS.aggregate(baseline),verified_questions=len(baseline),expected_questions=len(labels))),
            paired_deltas=deltas,counts=counts,targets=targets,ready=all(targets.values()),
            limitations=['Metric targets only; parent must independently accept execution identity, provenance and origin.',
                'Counterfactual baseline usage is unmeasured; live model quality and account billing are not established.'])
    except Exception:
        failed=True
    if failed:
        raise EvaluationScoringError('invalid_evaluation_scoring')
    return report
