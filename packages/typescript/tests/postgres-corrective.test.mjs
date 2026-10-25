import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { PostgresCorrectiveBackend } from '../dist/postgres-corrective.js';
import { PostgresSession } from '../dist/postgres-session.js';
import { verify_source } from '../dist/postgres-source.js';
import { parse_request, parse_scope } from '../dist/contracts.js';
import { ExecutionLedger } from '../dist/execution.js';
import { IntegrityViolation } from '../dist/errors.js';
import { now } from '../dist/postgres-pool.js';
const request=()=>parse_request({request_id:'request',query:'Café',collection:'collection'});
const scope=()=>parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['grant']});
const text='Café🙂',size=Buffer.byteLength(text),digest=createHash('sha256').update(text).digest('hex');
const candidate=()=>({tenant_id:'tenant',collection:'collection',document_id:'document',revision_id:'revision',generation_id:'generation',chunk_id:'chunk',start_byte:0,end_byte:size,text_sha256:digest,score:1});
const row=()=>['tenant','collection','document','revision','generation','chunk',digest,size,text,0,size,size,text,digest,'synthetic:source','native_fts.v1',true];
test('lexical search and captures freshly reauthorize with zero provider calls',async()=>{
  const original=PostgresSession.prototype.transaction;
  let rows=[row()],leases=0,fetches=0;
  PostgresSession.prototype.transaction=async function(input,bound,body){
    leases++;try{return await body({lexical_candidates:async({limit})=>{assert.equal(limit,2);return [candidate()];},fetch_evidence:async(c,o)=>{fetches++;return verify_source(c,rows,o.max_source_bytes,o.include_source);}});}finally{leases--;}
  };
  try{
    const backend=new PostgresCorrectiveBackend({resource:{}}),input=request(),deadline=now()+2,ledger=new ExecutionLedger({limits:input.limits,deadline}),bound={scope:scope(),deadline,ledger};
    const found=await backend.search(input,{...bound,limit:2});assert.equal(found.degraded,false);
    const first=await backend.capture(found.candidates,{...bound,request:input,max_source_bytes:100});
    assert.equal(first.sources[0].text,text);assert.equal(first.source_bytes,size);
    rows=[];
    const revoked=await backend.capture(found.candidates,{...bound,request:input,max_source_bytes:100});
    assert.deepEqual(revoked.evidence,[]);assert.equal(revoked.stale,true);assert.equal(fetches,2);assert.equal(leases,0);assert.equal(ledger.snapshot().provider_calls,0);
  }finally{PostgresSession.prototype.transaction=original;}
});
test('zero source allowance and forged tenant fail before source disclosure',async()=>{
  const backend=new PostgresCorrectiveBackend({resource:{}}),input=request(),deadline=now()+2,ledger=new ExecutionLedger({limits:input.limits,deadline}),bound={scope:scope(),deadline,ledger,request:input,max_source_bytes:0};
  const result=await backend.capture([candidate()],bound);assert.equal(result.budget_exhausted,true);assert.equal(result.source_bytes,0);
  await assert.rejects(backend.capture([{...candidate(),tenant_id:'other'}],bound),IntegrityViolation);
});

import { RerankingAdapter } from '../dist/reranking.js';
test('overridden reranker runs without lease and fresh capture honors revocation',async()=>{
  const original=PostgresSession.prototype.transaction;
  let rows=[row()],leases=0,fetches=0;
  PostgresSession.prototype.transaction=async function(input,bound,body){leases++;try{return await body({fetch_evidence:async(c,o)=>{fetches++;return verify_source(c,rows,o.max_source_bytes,o.include_source);}});}finally{leases--;}};
  class Ranker extends RerankingAdapter {
    async rank(query,views){assert.equal(leases,0);assert.equal(views[0].text,text);rows=[];const id=views[0].candidate_id;return {profile:this.profile,order:[id],scores:[{candidate_id:id,raw_score:1}],truncations:[],degraded:false,provider_calls:1,synthetic:true};}
  }
  try{
    const backend=new PostgresCorrectiveBackend({resource:{},reranker:new Ranker(async()=>{throw Error('unused');})}),input=request(),deadline=now()+2,ledger=new ExecutionLedger({limits:input.limits,deadline});
    const result=await backend.capture([candidate()],{scope:scope(),deadline,ledger,request:input,max_source_bytes:100});
    assert.deepEqual(result.evidence,[]);assert.equal(result.stale,true);assert.equal(fetches,2);assert.equal(ledger.snapshot().provider_calls,1);assert.equal(leases,0);
  }finally{PostgresSession.prototype.transaction=original;}
});
for(const fault of ['scores','nonfinite','truncations','extra','cycle','duplicate','direction'])test(`rejects overridden malformed rerank: ${fault}`,async()=>{
  const original=PostgresSession.prototype.transaction;let fetches=0;
  PostgresSession.prototype.transaction=async function(input,bound,body){return body({fetch_evidence:async(c,o)=>{fetches++;return verify_source(c,[row()],o.max_source_bytes,o.include_source);}});};
  class Ranker extends RerankingAdapter {
    async rank(query,views){
      const id=views[0].candidate_id,result={profile:structuredClone(this.profile),order:[id],scores:[{candidate_id:id,raw_score:1}],truncations:[],degraded:false,provider_calls:1,synthetic:true};
      if(fault==='scores')result.scores=[];
      if(fault==='nonfinite')result.scores[0].raw_score=NaN;
      if(fault==='truncations')result.truncations=[{candidate_id:id,original_bytes:9,view_bytes:8}];
      if(fault==='extra')result.tenant_id='forged';
      if(fault==='cycle')result.scores=result;
      if(fault==='duplicate')result.order=[id,id];
      if(fault==='direction')result.profile.score_direction='lower_is_better';
      return result;
    }
  }
  try{
    const backend=new PostgresCorrectiveBackend({resource:{},reranker:new Ranker(async()=>{throw Error('unused');})}),input=request(),deadline=now()+2,ledger=new ExecutionLedger({limits:input.limits,deadline});
    await assert.rejects(backend.capture([candidate()],{scope:scope(),deadline,ledger,request:input,max_source_bytes:100}),IntegrityViolation);assert.equal(fetches,1);
  }finally{PostgresSession.prototype.transaction=original;}
});
test('two chunks share one full source snapshot and charge both fetches',async()=>{
  const original=PostgresSession.prototype.transaction;
  PostgresSession.prototype.transaction=async function(input,bound,body){return body({fetch_evidence:async(c,o)=>{const data=row();data[5]=c.chunk_id;return verify_source(c,[data],o.max_source_bytes,o.include_source);}});};
  try{
    const backend=new PostgresCorrectiveBackend({resource:{}}),input=request(),deadline=now()+2,ledger=new ExecutionLedger({limits:input.limits,deadline});
    const result=await backend.capture([candidate(),{...candidate(),chunk_id:'chunk-2'}],{scope:scope(),deadline,ledger,request:input,max_source_bytes:100});
    assert.equal(result.evidence.length,2);assert.equal(result.sources.length,1);assert.equal(result.source_bytes,size*2);
  }finally{PostgresSession.prototype.transaction=original;}
});
