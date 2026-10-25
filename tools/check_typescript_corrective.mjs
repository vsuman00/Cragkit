import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {CorrectiveRetriever} from '../packages/typescript/dist/corrective.js';
import {PlannerAdapter} from '../packages/typescript/dist/planning.js';
import {ProviderUnavailable,UnauthorizedScope} from '../packages/typescript/dist/errors.js';
import {parse_request} from '../packages/typescript/dist/contracts.js';
const fixture=JSON.parse(readFileSync(new URL('../contracts/fixtures/corrective.json',import.meta.url),'utf8')),outputs=[];
for(const example of fixture.cases){
 const rows=fixture.rows,revoked=new Set(),calls=[];
 const raw=structuredClone(fixture.request);raw.limits=example.limits;const original=parse_request(raw);
 const backend={
  async search(request,{scope,limit,ledger}){
   assert.deepEqual(request.required_filters,original.required_filters);assert.equal(scope.tenant_id,'t');
   const entry=example.searches[Math.min(calls.length,example.searches.length-1)];calls.push(request.query);
   if(entry.reserve_call){const token=ledger.reserve({provider_calls:1,cost_upper_usd:0});ledger.dispatch(token);
    if(entry.failure)ledger.abandon(token);else ledger.reconcile(token,{input_tokens:0,output_tokens:0,cost_usd:0});}
   if(entry.failure)throw new ({provider_unavailable:ProviderUnavailable,unauthorized_scope:UnauthorizedScope}[entry.failure])();
   return {candidates:entry.ids.map(k=>structuredClone(rows[k].candidate)),degraded:false};
  },
  async capture(refs,{max_source_bytes}){
   if(calls.length>1)for(const id of example.revoke_after_search??[])revoked.add(id);
   let keys=refs.map(c=>c.document_id).filter(k=>!revoked.has(k)),size=keys.reduce((n,k)=>n+Buffer.byteLength(rows[k].source.text),0);
   const exhausted=size>max_source_bytes;if(exhausted){keys=[];size=0;}
   return {evidence:keys.map(k=>structuredClone(rows[k].evidence)),sources:keys.map(k=>structuredClone(rows[k].source)),source_bytes:size,stale:revoked.size>0,budget_exhausted:exhausted};
  }
 };
 const plan=async payload=>{
  for(const id of example.revoke_on_plan??[])revoked.add(id);
  if(example.planner==='fallback')throw new ProviderUnavailable();
  const queries=example.planner==='empty'?[]:payload.variants.filter(v=>payload.missing_facets.includes(v.facet_id)).map(v=>({facet_id:v.facet_id,variant_id:v.variant_id}));
  return {plan:{queries},usage:{input_tokens:1,output_tokens:1,cost_usd:0}};
 };
 const planner=example.planner==='none'?null:new PlannerAdapter({transport:plan,allow_fallback:example.planner==='fallback',cost_upper_usd:0});
 const variants=example.queries.map((query,index)=>({facet_id:'second',variant_id:'v'+index,query}));
 try{const value=await new CorrectiveRetriever({backend,policy:example.policy_none?null:fixture.policy,variants,planner,batch_size:2,...example.options}).retrieve(original,{scope:fixture.scope,deadline:performance.now()/1000+10});outputs.push(value);}
 catch(error){outputs.push({error:error.code??error.name});}
}
process.stdout.write(JSON.stringify(outputs));
