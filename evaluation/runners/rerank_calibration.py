"""In-sample reviewed-anchor calibration with local recorded reranker replay."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

from cragkit.assessment import assess_evidence, validate_assessment
from cragkit.canonical import canonicalize
from cragkit.context import Cl100kCounter, render_context
from cragkit.contracts._validation import identity, native_json, text
from cragkit.evidence import pack_and_assess
from cragkit.reranking import RerankProfile, RerankingAdapter

_SPEC = importlib.util.spec_from_file_location('cragkit_dense_metrics', Path(__file__).with_name('dense_metrics.py'))
assert _SPEC is not None and _SPEC.loader is not None
_METRICS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_METRICS)
aggregate, score_question = _METRICS.aggregate, _METRICS.score_question

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / 'evaluation/policies/V3-reviewed-span-v1.json'
PROFILE = RerankProfile(profile_id='cohere_v5fast_development_v1', provider='cohere',
    model='rerank-v5.0-fast', model_revision='mutable_alias:rerank-v5.0-fast',
    score_kind='relevance_score', score_direction='higher_is_better',
    preprocessing_revision='utf8-development-r1', truncation_policy='reject')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(baseline: dict) -> dict:
    """Reconstruct the frozen same-shortlist comparison from verified development data."""
    try:
        protocol_bytes = PROTOCOL.read_bytes()
        protocol = json.loads(protocol_bytes)
        manifest_bytes = (ROOT / 'evaluation/corpus/manifest.json').read_bytes()
        labels_bytes = (ROOT / 'evaluation/questions/dev.json').read_bytes()
        manifest, labels = json.loads(manifest_bytes), json.loads(labels_bytes)
        if type(baseline) is not dict or baseline.get('state') != 'passed' or baseline.get('cleanup_verified') is not True:
            raise ValueError()
        evaluation = baseline['evaluation']
        if (evaluation['manifest_sha256'] != _sha(manifest_bytes)
                or evaluation['development_labels_sha256'] != _sha(labels_bytes)
                or evaluation['question_ids'] != protocol['question_ids']
                or evaluation['encoder'] != protocol['search']['encoder']
                or evaluation['max_candidates'] != protocol['search']['max_candidates']
                or evaluation['k'] != protocol['ranking_metric_k']
                or labels['human_review']['state'] != 'approved'):
            raise ValueError()
        questions = {q['question_id']: q for q in labels['questions']}
        records = {}
        for record in evaluation['records']:
            if record['mode'] != 'hybrid':
                continue
            qid = record['metrics']['question_id']
            if qid in records or qid not in protocol['question_ids']:
                raise ValueError()
            records[qid] = record
        if set(records) != set(protocol['question_ids']):
            raise ValueError()
        cases = []
        selected_questions = []
        for qid in protocol['question_ids']:
            question = questions[qid]
            selected_questions.append(copy.deepcopy(question))
            documents = {}
            # Never open held-out files, even when they appear in the manifest.
            for document in manifest['documents']:
                if (document['split'] != 'development' or document['tenant_id'] != question['tenant_id']
                        or document['collection'] != question['collection']):
                    continue
                key = document['document_id'], document['revision_id']
                if key in documents:
                    raise ValueError()
                documents[key] = document
            evidence, sources = [], []
            ranked = records[qid]['ranked']
            if type(ranked) is not list or len(ranked) > 15 or any(
                type(pair) is not list or len(pair) != 2 or any(type(part) is not str for part in pair)
                for pair in ranked):
                raise ValueError()
            if len({tuple(pair) for pair in ranked}) != len(ranked):
                raise ValueError()
            for index, pair in enumerate(ranked[:protocol['shortlist']]):
                document = documents[tuple(pair)]
                path = (ROOT / 'evaluation/corpus' / document['path']).resolve()
                path.relative_to((ROOT / 'evaluation/corpus/documents').resolve())
                canonical = canonicalize(path.read_bytes(), target_bytes=2048, max_chunk_bytes=4096)
                if (canonical.canonical_sha256 != document['canonical_sha256'] or len(canonical.chunks) != 1
                        or canonical.chunks[0].start_byte != 0
                        or canonical.chunks[0].end_byte != len(canonical.canonical_text.encode('utf-8'))):
                    raise ValueError()
                chunk = canonical.chunks[0]
                eid = f'{qid}-{index}'
                source = dict(collection=question['collection'], document_id=document['document_id'],
                    revision_id=document['revision_id'], source_sha256=canonical.canonical_sha256,
                    text=canonical.canonical_text)
                sources.append(source)
                evidence.append(dict(**source, evidence_id=eid, chunk_id=eid,
                    source_locator='synthetic:v3-calibration', start_byte=0, end_byte=chunk.end_byte,
                    text_sha256=chunk.text_sha256))
            facets = []
            for facet in question['facets']:
                anchors = []
                for index, support in enumerate(facet['support']):
                    anchors.append(dict(claim_id=f'claim-{index}' if facet['state'] == 'conflicting' else 'claim',
                        collection=question['collection'], document_id=support['document_id'],
                        revision_id=support['revision_id'], source_sha256=support['canonical_sha256'],
                        start_byte=support['start_byte'], end_byte=support['end_byte'], text=support['text']))
                facets.append(dict(facet_id=facet['facet_id'], question=facet['question'], required=True,
                    absence='unknown' if facet['state'] == 'unknown' else 'missing', anchors=anchors))
            policy = dict(policy_id='reviewed-development', version='1', query_sha256=_sha(question['query'].encode()), facets=facets)
            assess_evidence(question['query'], evidence, policy)
            cases.append(dict(question_id=qid, query=question['query'], evidence=evidence, sources=sources, policy=policy))
        return dict(cases=cases, protocol_sha256=_sha(protocol_bytes), manifest_sha256=_sha(manifest_bytes),
                    development_labels_sha256=_sha(labels_bytes), questions=selected_questions,
                    baseline=copy.deepcopy(evaluation))
    except Exception:
        raise ValueError('invalid_calibration_baseline') from None


async def replay(cases: list, recordings: dict) -> list:
    """Use the real adapter and packing paths with recorded local bytes only."""
    try:
        if type(cases) is not list or not 1 <= len(cases) <= 6 or type(recordings) is not dict:
            raise ValueError()
        qids = []
        for case in cases:
            if type(case) is not dict or set(case) != {'question_id', 'query', 'evidence', 'sources', 'policy'}:
                raise ValueError()
            qid = case['question_id']
            if type(qid) is not str:
                raise ValueError()
            identity(qid)
            if type(case['query']) is not str:
                raise ValueError()
            text(case['query'], 8192)
            qids.append(qid)
            render_context(case['evidence'])
            native_json(case['sources'])
            if type(case['sources']) is not list or len(case['sources']) > 64:
                raise ValueError()
            assess_evidence(case['query'], case['evidence'], case['policy'])
            scores = recordings[qid]
            ids = {item['evidence_id'] for item in case['evidence']}
            if type(scores) is not list or len(scores) != len(ids) or len(scores) > 40:
                raise ValueError()
            seen = set()
            for score in scores:
                if (type(score) is not dict or set(score) != {'candidate_id', 'raw_score'}
                        or type(score['candidate_id']) is not str or score['candidate_id'] not in ids
                        or score['candidate_id'] in seen or type(score['raw_score']) not in (int, float)
                        or not math.isfinite(score['raw_score'])):
                    raise ValueError()
                seen.add(score['candidate_id'])
        if len(set(qids)) != len(qids) or set(recordings) != set(qids):
            raise ValueError()
        cases, recordings = copy.deepcopy(cases), copy.deepcopy(recordings)
    except Exception:
        raise ValueError('invalid_calibration_recording') from None
    counter = Cl100kCounter.from_file(ROOT / 'artifacts/tokenizers/cl100k_base.tiktoken')
    results = []
    for case in cases:
        qid = case['question_id']
        async def transport(body, *, deadline, max_response_bytes):
            return json.dumps(recordings[qid], allow_nan=False, separators=(',', ':')).encode()
        adapter = RerankingAdapter(transport, profile=PROFILE, allow_live=True)
        options = dict(deadline=time.monotonic() + 30, max_tokens=20000, reserve=256, counter=counter,
                       counting_mode='strict', surrounding_bytes=256, rebalance=True, policy=case['policy'])
        before = await pack_and_assess(case['query'], case['evidence'], case['sources'], **options)
        ranked = await adapter.rank(case['query'], [dict(candidate_id=item['evidence_id'], text=item['text'])
                                   for item in case['evidence']], deadline=options['deadline'])
        mapping = {item['evidence_id']: item for item in case['evidence']}
        after = await pack_and_assess(case['query'], [mapping[ref] for ref in ranked['order']], case['sources'], **options)
        results.append(dict(question_id=qid, before=before, after=after, order=ranked['order'], scores=ranked['scores']))
    return results


def _label_sufficient(question: dict, evidence: list) -> bool:
    """Compare emitted bytes directly with reviewed labels, independently of AS-r1."""
    if question['answerability'] != 'answerable' or not question['facets'] or not evidence:
        return False
    for facet in question['facets']:
        if facet['state'] != 'supported':
            return False
        covered = False
        for support in facet['support']:
            for item in evidence:
                if (item['collection'] != question['collection']
                        or item['document_id'] != support['document_id']
                        or item['revision_id'] != support['revision_id']
                        or item['source_sha256'] != support['canonical_sha256']
                        or item['start_byte'] > support['start_byte']
                        or item['end_byte'] < support['end_byte']):
                    continue
                start, end = support['start_byte'] - item['start_byte'], support['end_byte'] - item['start_byte']
                if item['text'].encode('utf-8')[start:end] == support['text'].encode('utf-8'):
                    covered = True
                    break
            if covered:
                break
        if not covered:
            return False
    return True


def evaluate(prepared: dict, results: list) -> dict:
    """Report counts with explicit denominators and same-shortlist ranking metrics."""
    protocol = json.loads(PROTOCOL.read_bytes())
    if prepared['protocol_sha256'] != _sha(PROTOCOL.read_bytes()):
        raise ValueError('invalid_calibration_protocol')
    questions = {q['question_id']: q for q in prepared['questions']}
    cases = {case['question_id']: case for case in prepared['cases']}
    if (type(results) is not list or [result['question_id'] for result in results] != protocol['question_ids']
            or list(cases) != protocol['question_ids'] or list(questions) != protocol['question_ids']):
        raise ValueError('invalid_calibration_results')
    report = {}
    for phase in ['before', 'after']:
        counts = dict(false_sufficient=0, abstention=0, answerable_abstention=0, conflict_error=0)
        rows, packed_rows = [], []
        answerable = conflicts = 0
        for result in results:
            qid = result['question_id']
            question, case = questions[qid], cases[qid]
            actual = result[phase]
            if actual['status'] not in ('sufficient', 'partial', 'insufficient'):
                raise ValueError('invalid_calibration_results')
            validate_assessment(actual['evidence'], actual['facets'])
            sufficient = actual['status'] == 'sufficient'
            counts['false_sufficient'] += int(sufficient and not _label_sufficient(question, actual['evidence']))
            counts['abstention'] += int(not sufficient)
            if question['answerability'] == 'answerable':
                answerable += 1
                counts['answerable_abstention'] += int(not sufficient)
            if any(facet['state'] == 'conflicting' for facet in question['facets']):
                conflicts += 1
                actual_states = {facet['facet_id']: facet['state'] for facet in actual['facets']}
                counts['conflict_error'] += int(any(actual_states.get(facet['facet_id']) != 'conflicting'
                    for facet in question['facets'] if facet['state'] == 'conflicting'))
            packed_rows.append(score_question(question, actual['evidence'], k=protocol['ranking_metric_k']))
            mapping = {item['evidence_id']: item for item in case['evidence']}
            if (type(result['order']) is not list or len(result['order']) != len(mapping)
                    or set(result['order']) != set(mapping)):
                raise ValueError('invalid_calibration_order')
            ranked = case['evidence'] if phase == 'before' else [mapping[ref] for ref in result['order']]
            rows.append(score_question(question, ranked, k=protocol['ranking_metric_k']))
        denominators = dict(false_sufficient=len(results), abstention=len(results),
                            answerable_abstention=answerable, conflict_error=conflicts)
        report[phase] = {name: dict(count=count, denominator=denominators[name],
                                   rate=count / denominators[name] if denominators[name] else None)
                         for name, count in counts.items()}
        report[phase].update(ranking=aggregate(rows), ranking_records=rows,
                             packed_ranking=aggregate(packed_rows), packed_ranking_records=packed_rows)
    report['historical_V2_full_candidate_baseline'] = copy.deepcopy(prepared['baseline']['modes'])
    report['limitations'] = protocol['limitations']
    return report
