/** Native corrective fixture child. The caller owns resource lifetime and credentials. */
import assert from 'node:assert/strict';
import { CorrectiveRetriever } from '../packages/typescript/dist/corrective.js';
import { PostgresCorrectiveBackend } from '../packages/typescript/dist/postgres-corrective.js';
import { PostgresSession } from '../packages/typescript/dist/postgres-session.js';
import { PlannerAdapter } from '../packages/typescript/dist/planning.js';
import { RerankingAdapter } from '../packages/typescript/dist/reranking.js';
import { Cl100kCounter } from '../packages/typescript/dist/context.js';
import { parse_request, parse_scope } from '../packages/typescript/dist/contracts.js';
import { now } from '../packages/typescript/dist/postgres-pool.js';
const normalized=value=>{const copy=structuredClone(value);for(const stage of copy.result.usage.stage_durations)stage.duration_ms=0;return copy;};
export async function runCorrective(resource,cases,embedder,tombstone,evaluation_deadline_seconds=25){
  assert.ok(Number.isInteger(evaluation_deadline_seconds)&&[25,60].includes(evaluation_deadline_seconds));
  const acceptance_profile=evaluation_deadline_seconds===60?'high_latency_admin':'default';
  const effective_evaluation_deadline_ms=evaluation_deadline_seconds===60?60000:10000;
  assert.equal(cases.filter(entry=>entry.kind==='labelled').length,18);
  const base=new PostgresSession(resource);let active=0,expectedFilters=null;
  const tracked={transaction(request,options,body){if(expectedFilters!==null)assert.deepEqual(request.required_filters,expectedFilters);return base.transaction(request,options,async handle=>{active++;try{return await body(handle);}finally{active--;}});}};
  const rank=async body=>{assert.equal(active,0);const value=JSON.parse(Buffer.from(body).toString('utf8'));return Buffer.from(JSON.stringify(value.candidates.map((item,index)=>({candidate_id:item.candidate_id,raw_score:value.candidates.length-index}))));};
  const plan=async payload=>({plan:{queries:payload.variants.filter(item=>payload.missing_facets.includes(item.facet_id)).slice(0,payload.max_subqueries-1).map(item=>({facet_id:item.facet_id,variant_id:item.variant_id}))},usage:{input_tokens:0,output_tokens:0,cost_usd:0}});
  const records=[],checks=[];
  for(const entry of cases){
    const config=entry.configuration,request=parse_request(entry.request),scope=parse_scope(entry.scope);
    assert.equal(request.limits.deadline_ms,effective_evaluation_deadline_ms);
    const options={resource,mode:config.mode};if(config.mode!=='lexical')options.embedder=embedder();if(config.reranked)options.reranker=new RerankingAdapter(rank);
    const backend=new PostgresCorrectiveBackend(options);backend.session=tracked;
    let counter;
    try{
      if(request.output_profile.counting_mode==='strict')counter=await Cl100kCounter.create('artifacts/tokenizers/cl100k_base.tiktoken');
      const target=new CorrectiveRetriever({backend,policy:config.policy,variants:config.variants,
        planner:config.corrective?new PlannerAdapter({transport:plan,cost_upper_usd:0}):null,batch_size:4,counter});
      expectedFilters=request.required_filters;
      const start=now(),result=await target.retrieve(request,{scope,deadline:now()+evaluation_deadline_seconds});
      const elapsed=(now()-start)*1000;
      assert.deepEqual(normalized(result),entry.expected);
      assert.ok(result.diagnostics.candidate_work<=12&&result.result.usage.provider_calls<=8);
      assert.ok(result.result.usage.context_tokens+request.output_profile.envelope_reserve_tokens<=request.limits.max_context_tokens);
      assert.equal(active,0);
      records.push({status:result.result.status,evidence_count:result.result.evidence.length,question_id:entry.question_id,mode:entry.mode,kind:entry.kind,latency_ms:elapsed,
        provider_calls:result.result.usage.provider_calls,usage:result.result.usage,candidate_work:result.diagnostics.candidate_work,
        stop_reason:result.diagnostics.stop_reason,rss_current_bytes:process.memoryUsage().rss});
    }finally{counter?.close();}
  }
  const first=cases.find(entry=>entry.scope.tenant_id===cases[0].scope.tenant_id);
  assert.ok(first);
  const revoke=async body=>{assert.equal(active,0);await tombstone(true);return rank(body);};
  const backend=new PostgresCorrectiveBackend({resource,mode:'hybrid',embedder:embedder(),reranker:new RerankingAdapter(revoke)});backend.session=tracked;
  const request=parse_request({query:'ERR-17',collection:first.request.collection,required_filters:[{field:'document_id',op:'eq',value:'retry-policy'}],
    output_profile:{renderer:'cragkit.context.v2'},limits:{max_candidates:12,max_attempts:3,max_subqueries:3,max_provider_calls:8,
      ...(evaluation_deadline_seconds===60?{deadline_ms:60000}:{})}});
  expectedFilters=request.required_filters;
  try{
    const result=await new CorrectiveRetriever({backend,batch_size:4}).retrieve(request,{scope:parse_scope(first.scope),deadline:now()+evaluation_deadline_seconds});
    assert.equal(result.result.evidence.length,0);assert.ok(result.result.limitations.some(item=>item.code==='stale_evidence'));assert.equal(active,0);
  }finally{await tombstone(false);}
  checks.push('node_v4_18_development_ablation_results_exact_native_parity','node_v4_separate_weak_query_targeted_recovery_parity','node_v4_post_model_revocation_and_no_model_lease');
  return {checks,records,acceptance_profile,evaluation_deadline_seconds,effective_evaluation_deadline_ms};
}
