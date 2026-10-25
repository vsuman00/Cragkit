import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { createHash } from 'node:crypto';
import { PostgresCorrectiveBackend } from '../dist/postgres-corrective.js';
import { CorrectiveRetriever } from '../dist/corrective.js';
import { PlannerAdapter } from '../dist/planning.js';
import { EmbeddingAdapter } from '../dist/embeddings.js';
import { ExecutionLedger,BudgetExhausted } from '../dist/execution.js';
import { InvalidRequest } from '../dist/errors.js';
import { parse_request,parse_scope } from '../dist/contracts.js';
const hash=text=>createHash('sha256').update(text).digest('hex');
const scope=parse_scope({tenant_id:'t',principal_id:'reader',authorization_revision:'acl'});
function forbiddenBackend(){
  let embeddings=0,sessions=0;
  class Embedder extends EmbeddingAdapter{async embed_query(){embeddings++;throw new Error('unexpected model call');}}
  const embedder=new Embedder(async()=>{throw new Error('unexpected transport');},{name:'fake-byte-v1',count:()=>0});
  const resource={async withLease(){sessions++;throw new Error('unexpected database lease');}};
  return {backend:new PostgresCorrectiveBackend({resource,mode:'hybrid',embedder}),counts:()=>({embeddings,sessions})};
}
for(const [query,minimum]of [['ordinary query',2],['API-42 query',3]]){
  test(`original hybrid request below ${minimum} required branches is invalid without dispatch`,async()=>{
    const {backend,counts}=forbiddenBackend();
    const request=parse_request({query,collection:'c',limits:{max_candidates:minimum-1}}),deadline=performance.now()/1000+1;
    const ledger=new ExecutionLedger({limits:request.limits,deadline});
    await assert.rejects(backend.search(request,{scope,deadline,ledger,limit:minimum-1}),InvalidRequest);
    assert.deepEqual(counts(),{embeddings:0,sessions:0});assert.equal(ledger.snapshot().provider_calls,0);assert.equal(ledger.snapshot().pending,0);
  });
  for(let limit=1;limit<minimum;limit++)test(`remaining hybrid work ${limit} below branch floor ${minimum} is budget exhaustion before dispatch`,async()=>{
    const {backend,counts}=forbiddenBackend();
    const request=parse_request({query,collection:'c',limits:{max_candidates:5}}),deadline=performance.now()/1000+1;
    const ledger=new ExecutionLedger({limits:request.limits,deadline});
    const previous=ledger.reserve({candidates:5-limit});ledger.dispatch(previous);ledger.reconcile(previous);
    await assert.rejects(backend.search(request,{scope,deadline,ledger,limit}),BudgetExhausted);
    assert.deepEqual(counts(),{embeddings:0,sessions:0});assert.equal(ledger.snapshot().provider_calls,0);
    assert.equal(ledger.snapshot().cost_usd,0);assert.equal(ledger.snapshot().pending,0);assert.equal(ledger.snapshot().candidates,5-limit);
  });
}

test('core retains fresh useful evidence when targeted hybrid branch work cannot fit',async()=>{
  const query='API-42 query',text='Known retry count.',digest=hash(text),{backend:limited,counts}=forbiddenBackend();
  const candidate={tenant_id:'t',collection:'c',document_id:'d',revision_id:'r',generation_id:'g',chunk_id:'chunk',start_byte:0,end_byte:Buffer.byteLength(text),text_sha256:digest,score:1};
  const evidence={evidence_id:'e',collection:'c',document_id:'d',revision_id:'r',chunk_id:'chunk',source_locator:'source:d',start_byte:0,end_byte:Buffer.byteLength(text),text,source_sha256:digest,text_sha256:digest};
  const source={collection:'c',document_id:'d',revision_id:'r',source_sha256:digest,text};
  const policy={policy_id:'reviewed',version:'1',query_sha256:hash(query),facets:[
    {facet_id:'known',question:'Known count?',required:true,absence:'missing',anchors:[{claim_id:'a',collection:'c',document_id:'d',revision_id:'r',source_sha256:digest,start_byte:0,end_byte:Buffer.byteLength(text),text}]},
    {facet_id:'missing',question:'Missing delay?',required:true,absence:'missing',anchors:[]}]};
  let searches=0,captures=0;
  const bridge={async search(request,o){if(++searches===1)return {candidates:[candidate],degraded:false};assert.equal(o.limit,1);return limited.search(request,o);},
    async capture(){captures++;return {evidence:[evidence],sources:[source],source_bytes:Buffer.byteLength(text),stale:false,budget_exhausted:false};}};
  const planner=new PlannerAdapter({cost_upper_usd:0,transport:async()=>({plan:{queries:[{facet_id:'missing',variant_id:'v'}]},usage:{input_tokens:0,output_tokens:0,cost_usd:0}})});
  const result=await new CorrectiveRetriever({backend:bridge,policy,variants:[{facet_id:'missing',variant_id:'v',query:'API-42 delay'}],planner,batch_size:4})
    .retrieve({query,collection:'c',limits:{max_candidates:5},output_profile:{renderer:'cragkit.context.v2'}},{scope,deadline:performance.now()/1000+1});
  assert.equal(result.diagnostics.stop_reason,'budget_exhausted');assert.equal(result.result.status,'partial');assert.equal(result.result.evidence[0].text,text);
  assert.equal(result.diagnostics.candidate_work,5);assert.equal(result.result.usage.provider_calls,1);assert.equal(result.result.usage.cost_usd,0);
  assert.equal(searches,2);assert.equal(captures,3);assert.deepEqual(counts(),{embeddings:0,sessions:0});
});
