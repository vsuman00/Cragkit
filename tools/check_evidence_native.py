"""EP-r1 additions inside the restricted, explicitly authorized hybrid fixture."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def reviewed_policy(question, receipts, collection):
    facets=[]
    for facet in question['facets']:
        anchors=[]
        for index, support in enumerate(facet['support']):
            receipt=receipts[(question['tenant_id'],support['document_id'],support['revision_id'])]
            anchors.append(dict(claim_id=str(index) if facet['state']=='conflicting' else 'compatible',
                collection=collection,document_id=support['document_id'],revision_id=receipt['revision_id'],
                source_sha256=support['canonical_sha256'],start_byte=support['start_byte'],
                end_byte=support['end_byte'],text=support['text']))
        facets.append(dict(facet_id=facet['facet_id'],question=facet['question'],required=True,
                           absence='unknown' if facet['state']=='unknown' else 'missing',anchors=anchors))
    return dict(policy_id='reviewed-development',version='1',query_sha256=sha256(question['query'].encode()).hexdigest(),facets=facets)


async def run(resource, questions, receipts, scoped, collection, make_request, embedder, tombstone,
              *, evaluation_deadline_seconds=25):
    from check_hybrid import require, normalized, evaluation_profile, evaluation_limits
    evaluation_profile(evaluation_deadline_seconds)
    from cragkit._postgres_session import PostgresSession
    from cragkit.context import Cl100kCounter
    from cragkit.contracts import parse_request
    from cragkit.reranking import RerankingAdapter
    from cragkit.retrieval import PostgresRetriever
    loop=asyncio.get_running_loop()
    active=0
    base=PostgresSession(resource)
    class Tracked:
        @asynccontextmanager
        async def transaction(self,*args,**kwargs):
            nonlocal active
            async with base.transaction(*args,**kwargs) as handle:
                active+=1
                try:yield handle
                finally:active-=1
    async def rank(body,*,deadline,max_response_bytes):
        require(active==0,'evidence_model_held_lease')
        value=json.loads(body)
        return json.dumps([dict(candidate_id=item['candidate_id'],raw_score=len(value['candidates'])-index)
                           for index,item in enumerate(value['candidates'])]).encode()
    cases=[]
    for index,question in enumerate(questions):
        value=make_request(question,'hybrid').model_dump(mode='json')
        value['limits']=evaluation_limits(evaluation_deadline_seconds,value['limits'])
        value['request_id']='v3-native-'+question['question_id']
        value['output_profile']=dict(renderer='cragkit.context.v2',tokenizer='cl100k_base' if index==0 else None,
            counting_mode='strict' if index==0 else 'estimated',envelope_reserve_tokens=256)
        policy=reviewed_policy(question,receipts,collection)
        options=dict(policy=policy,rebalance=True,reranker=RerankingAdapter(rank))
        if index==0:options['counter']=Cl100kCounter.from_file(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')
        target=PostgresRetriever(resource,mode='hybrid',embedder=embedder(),evidence_options=options)
        target._session=Tracked()
        result=await target.retrieve(parse_request(value),scope=scoped[question['tenant_id']],deadline=loop.time()+evaluation_deadline_seconds)
        require(result.usage.provider_calls<=2,'evidence_calls_exceeded')
        require(result.usage.context_tokens+value['output_profile']['envelope_reserve_tokens']<=value['limits']['max_context_tokens'],'evidence_context_exceeded')
        if question['question_id']=='q19':require(result.status!='sufficient','evidence_conflict_false_sufficient')
        if question['answerability']=='unanswerable':require(result.status!='sufficient','evidence_absent_false_sufficient')
        cases.append(dict(mode='hybrid',request=value,scope=scoped[question['tenant_id']].model_dump(mode='json'),
            evidence_options=dict(policy=policy,rebalance=True),expected=normalized(result.model_dump(mode='json'))))
    question=questions[0]
    parsed=parse_request(dict(query='ERR-17',collection=collection,
        required_filters=[dict(field='document_id',op='eq',value='retry-policy')],
        limits=evaluation_limits(evaluation_deadline_seconds),
        output_profile=dict(renderer='cragkit.context.v2')))
    async def revoked(body,*,deadline,max_response_bytes):
        require(active==0,'evidence_revocation_held_lease')
        await tombstone(True)
        return await rank(body,deadline=deadline,max_response_bytes=max_response_bytes)
    target=PostgresRetriever(resource,mode='hybrid',embedder=embedder(),evidence_options=dict(reranker=RerankingAdapter(revoked)))
    target._session=Tracked()
    try:
        result=await target.retrieve(parsed,scope=scoped[question['tenant_id']],deadline=loop.time()+evaluation_deadline_seconds)
        require(not result.evidence and result.status=='insufficient'
                and any(item.code=='stale_evidence' for item in result.limitations),'evidence_post_model_tombstone_release')
    finally:await tombstone(False)
    return cases,['python_v3_six_query_packed_assessment_strict_budget_and_accounting',
                  'python_v3_no_model_lease_and_post_model_tombstone_denied']
