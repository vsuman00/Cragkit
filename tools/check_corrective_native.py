"""Restricted native corrective fixture and development-only synthetic ablation."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import re
import resource as process_resource
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation/runners'))
from v2_metrics import aggregate, score_question
from check_evidence_native import reviewed_policy
from check_hybrid import require, normalized, evaluation_profile, evaluation_limits


def approved_variants(question):
    from cragkit._identifiers import extract_identifiers
    identifiers = list(extract_identifiers(question['query']))
    variants = []
    for facet in question['facets']:
        if not facet['support']:
            continue
        # Oracle-assisted development probe: search hypotheses derive from answer support labels.
        words = re.findall(r'[A-Za-z][A-Za-z0-9_-]*', facet['support'][0]['text'])[:8]
        query = ' '.join(dict.fromkeys([*words, *identifiers]))
        if query:
            variants.append(dict(facet_id=facet['facet_id'], variant_id='reviewed-'+facet['facet_id'], query=query))
    return variants[:16]


async def run(resource, questions, receipts, scoped, collection, make_request, embedder, tombstone,
              *, evaluation_deadline_seconds=25):
    evaluation_profile(evaluation_deadline_seconds)
    from cragkit._postgres_session import PostgresSession
    from cragkit.context import Cl100kCounter
    from cragkit.contracts import parse_request
    from cragkit.corrective import CorrectiveRetriever
    from cragkit.planning import PlannerAdapter
    from cragkit.postgres_corrective import PostgresCorrectiveBackend
    from cragkit.reranking import RerankingAdapter
    import json
    loop = asyncio.get_running_loop()
    active = 0
    expected_filters = None
    base = PostgresSession(resource)
    class Tracked:
        @asynccontextmanager
        async def transaction(self, *args, **kwargs):
            nonlocal active
            if expected_filters is not None:
                require(kwargs.get('scope') is not None and args[0].required_filters == expected_filters, 'corrective_filters_changed')
            async with base.transaction(*args, **kwargs) as handle:
                active += 1
                try:
                    yield handle
                finally:
                    active -= 1
    async def rank(body, *, deadline, max_response_bytes):
        require(active == 0, 'corrective_model_held_lease')
        value = json.loads(body)
        return json.dumps([dict(candidate_id=item['candidate_id'], raw_score=len(value['candidates'])-index)
            for index, item in enumerate(value['candidates'])]).encode()
    async def plan(payload, *, deadline):
        missing = set(payload['missing_facets'])
        selected = [dict(facet_id=item['facet_id'], variant_id=item['variant_id'])
            for item in payload['variants'] if item['facet_id'] in missing][:payload['max_subqueries']-1]
        return dict(plan=dict(queries=selected), usage=dict(input_tokens=0, output_tokens=0, cost_usd=0))
    cases, records, scores = [], [], {mode: [] for mode in ('hybrid', 'reranked', 'corrective')}
    reverse = {(tenant, value['document_id'], value['revision_id']): logical
        for (tenant, doc, logical), value in receipts.items()}
    async def execute(question, mode, index, *, mechanics=False):
        nonlocal expected_filters
        value = make_request(question, 'hybrid').model_dump(mode='json')
        value['limits'] = evaluation_limits(evaluation_deadline_seconds, value['limits'])
        value['request_id'] = 'v4-native-'+question['question_id']+'-'+mode
        value['limits'].update(max_candidates=12, max_attempts=3, max_subqueries=3, max_provider_calls=8)
        value['output_profile'] = dict(renderer='cragkit.context.v2', tokenizer='cl100k_base' if index == 0 else None,
            counting_mode='strict' if index == 0 else 'estimated', envelope_reserve_tokens=256)
        policy = reviewed_policy(question, receipts, collection)
        variants = approved_variants(question)
        config = dict(mode='lexical' if mechanics else 'hybrid', reranked=mode != 'hybrid',
            corrective=mode == 'corrective', batch_size=4, policy=policy, variants=variants)
        backend = PostgresCorrectiveBackend(resource, mode=config['mode'],
            embedder=None if mechanics else embedder(), reranker=RerankingAdapter(rank) if config['reranked'] else None)
        backend._session = Tracked()
        counter = Cl100kCounter.from_file(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken') if index == 0 else None
        target = CorrectiveRetriever(backend, policy=policy, variants=variants,
            planner=PlannerAdapter(plan, cost_upper_usd=0) if config['corrective'] else None,
            batch_size=4, counter=counter)
        expected_filters = parse_request(value).required_filters
        started = time.perf_counter()
        output = await target.retrieve(parse_request(value), scope=scoped[question['tenant_id']], deadline=loop.time()+evaluation_deadline_seconds)
        elapsed = (time.perf_counter()-started)*1000
        result = output['result']
        require(result['usage']['provider_calls'] <= 8, 'corrective_calls_exceeded')
        require(output['diagnostics']['candidate_work'] <= 12, 'corrective_candidate_work_exceeded')
        require(result['usage']['context_tokens']+256 <= value['limits']['max_context_tokens'], 'corrective_context_exceeded')
        require(active == 0, 'corrective_lease_leaked')
        if question['answerability'] == 'unanswerable' or any(f['state'] == 'conflicting' for f in question['facets']):
            require(result['status'] != 'sufficient', 'corrective_false_sufficient')
        expected = deepcopy(output)
        expected['result'] = normalized(result)
        cases.append(dict(kind='mechanics' if mechanics else 'labelled', question_id=question['question_id'],
            mode=mode, configuration=config, request=value, scope=scoped[question['tenant_id']].model_dump(mode='json'), expected=expected))
        record = dict(status=result['status'], evidence_count=len(result['evidence']), question_id=question['question_id'], mode=mode, kind='mechanics' if mechanics else 'labelled',
            latency_ms=elapsed, provider_calls=result['usage']['provider_calls'], usage=result['usage'],
            candidate_work=output['diagnostics']['candidate_work'], stop_reason=output['diagnostics']['stop_reason'],
            rss_high_water_bytes=process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
        if not mechanics:
            metric_evidence = [dict(document_id=e['document_id'], revision_id=reverse[(question['tenant_id'],e['document_id'],e['revision_id'])], start_byte=e['start_byte'], end_byte=e['end_byte']) for e in result['evidence']]
            metric = score_question(question, metric_evidence, k=5)
            record['metrics'] = metric
            scores[mode].append(metric)
        records.append(record)
        return output
    require(len(questions) == 6, 'corrective_selection_changed')
    for index, question in enumerate(questions):
        for mode in scores:
            await execute(question, mode, index)
    # Separate mechanics probe: lexical nonsense cannot match; approved support can.
    source = next(q for q in questions if q['answerability'] == 'answerable' and any(f['support'] for f in q['facets']))
    weak = deepcopy(source)
    weak['question_id'] = 'weak-query-mechanics'
    weak['query'] = 'zzunfindablecorrectivetermzz'
    baseline = await execute(weak, 'hybrid', 1, mechanics=True)
    recovered = await execute(weak, 'corrective', 1, mechanics=True)
    require(not baseline['result']['evidence'] and bool(recovered['result']['evidence']), 'corrective_weak_query_did_not_recover')
    require(recovered['diagnostics']['queries_executed'] > baseline['diagnostics']['queries_executed'], 'corrective_weak_query_not_targeted')
    async def revoke(body, *, deadline, max_response_bytes):
        require(active == 0, 'corrective_revocation_held_lease')
        await tombstone(True)
        return await rank(body, deadline=deadline, max_response_bytes=max_response_bytes)
    backend = PostgresCorrectiveBackend(resource, mode='hybrid', embedder=embedder(), reranker=RerankingAdapter(revoke))
    backend._session = Tracked()
    parsed = parse_request(dict(query='ERR-17', collection=collection,
        required_filters=[dict(field='document_id',op='eq',value='retry-policy')],
        output_profile=dict(renderer='cragkit.context.v2'), limits=evaluation_limits(evaluation_deadline_seconds,
            dict(max_candidates=12,max_attempts=3,max_subqueries=3,max_provider_calls=8))))
    expected_filters = parsed.required_filters
    expected_filters = parsed.required_filters
    try:
        output = await CorrectiveRetriever(backend,batch_size=4).retrieve(parsed,scope=scoped['tenant-a'],deadline=loop.time()+evaluation_deadline_seconds)
        require(not output['result']['evidence'] and any(x['code']=='stale_evidence' for x in output['result']['limitations']), 'corrective_post_model_tombstone_release')
    finally:
        await tombstone(False)
    summary = {mode: dict(aggregate(scores[mode]), latency_ms_python_median=statistics.median(r['latency_ms'] for r in records if r['kind']=='labelled' and r['mode']==mode)) for mode in scores}
    labelled_gain = sum(1 for q in questions if next(r for r in records if r['question_id']==q['question_id'] and r['mode']=='corrective')['metrics']['facet_support_recall_at_k'] is not None
        and next(r for r in records if r['question_id']==q['question_id'] and r['mode']=='corrective')['metrics']['facet_support_recall_at_k'] > next(r for r in records if r['question_id']==q['question_id'] and r['mode']=='hybrid')['metrics']['facet_support_recall_at_k'])
    return cases, ['python_v4_18_development_ablation_requests_bounded_and_reassessed',
        'python_v4_separate_weak_query_targeted_recovery', 'python_v4_post_model_revocation_and_no_model_lease'], dict(
        kind='synthetic_mechanics_only', labelled_questions_with_improved_facet_recall=labelled_gain, question_ids=[q['question_id'] for q in questions], k=5,
        batch_size=4,max_candidates=12,max_attempts=3,max_provider_calls=8,modes=summary,records=records,
        limitations=['six_reviewed_development_questions_only','oracle_assisted_label_derived_variants_not_generalization',
            'synthetic_embeddings_reranking_and_planner_not_live_model_quality','held_out_not_evaluated',
            'rss_is_process_high_water_not_request_peak','hosting_cost_unmeasured','weak_query_probe_excluded_from_labelled_scores'])
