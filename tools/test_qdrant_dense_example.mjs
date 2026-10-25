/** Example accounting checks use injected, in-memory provider/backend spies only. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {retrieve_candidates} from '../examples/qdrant_dense.mjs';
import {FAKE_PROFILE,OPENAI_PROFILE} from '../packages/typescript/dist/embeddings.js';
import {ExecutionLedger,BudgetExhausted} from '../packages/typescript/dist/execution.js';
import {ProviderUnavailable,UnsupportedCapability} from '../packages/typescript/dist/errors.js';
import {QdrantSearchStore} from '../packages/typescript/dist/qdrant.js';
const fixture=JSON.parse(readFileSync(new URL('../contracts/fixtures/qdrant_candidates.json',import.meta.url)));
async function setup(profile=FAKE_PROFILE,limits={max_candidates:2,max_provider_calls:1}){
  const calls=[];
  const transport={bounded_responses:true,cancellation_safe:true,async request(method,path,options){
    calls.push({method,path,options});
    const value=path==='/'?{version:'1.20.0'}:path==='/cluster'?{status:'ok',result:{status:'disabled'}}:method==='GET'?{status:'ok',result:{config:{params:{vectors:{dense:{size:1536,distance:'Cosine'}},replication_factor:1,write_consistency_factor:1}}}}:{status:'ok',result:{points:[]}};
    return Buffer.from(JSON.stringify(value));
  }};
  const store=new QdrantSearchStore({backend_namespace:'fixture-local',physical_collection:'cragkit_qc_r1',collection_incarnation:'inc-1',dense_profile:profile,sparse_profile:null},transport);
  const deadline=performance.now()/1000+2;
  await store.initialize({deadline});
  const request={request_id:'example',query:'fixture',collection:'docs',required_filters:[],limits};
  return {store,calls,request,scope:fixture.trusted_scope,ledger:new ExecutionLedger({limits,deadline}),deadline,token_counter:{name:profile.tokenizer,count:text=>Buffer.byteLength(text)}};
}
function response(body,usage=true){const req=JSON.parse(Buffer.from(body));return Buffer.from(JSON.stringify({model:req.model,data:[{index:0,embedding:[1,...Array(1535).fill(0)]}],...(usage?{usage:{prompt_tokens:7,total_tokens:7}}:{})}));}
test('fake provider and candidate slots are accounted separately',async()=>{
  const s=await setup(),sent=[];
  try{
    const result=await retrieve_candidates(s.store,s.request,{...s,transport:async(body,options)=>{sent.push(options);return response(body);}});
    assert.deepEqual(result.nominations,[]);assert.equal(sent.length,1);
    assert.deepEqual(result.ledger,{provider_calls:1,candidates:2,attempts:0,input_tokens:7,output_tokens:0,cost_usd:0,cost_kind:'known',pending:0});
    assert.equal(sent[0].deadline,s.calls.at(-1).options.deadline);
  }finally{await s.store.close();}
});
for(const usage of [true,false])test(`real profile spy preserves ${usage?'estimated':'unknown'} billing`,async()=>{
  const s=await setup(OPENAI_PROFILE),sent=[];
  try{
    const result=await retrieve_candidates(s.store,s.request,{...s,policy:{allow_live:true,max_cost_usd:0.01,usd_per_million_tokens:0.02},transport:async body=>{sent.push(JSON.parse(Buffer.from(body)));return response(body,usage);}});
    assert.equal(sent[0].model,OPENAI_PROFILE.model);assert.equal(sent[0].dimensions,1536);
    assert.equal(result.embedding_usage.cost_kind,usage?'estimated':'unknown');
    assert.equal(result.ledger.cost_kind,'unknown');assert.equal(result.ledger.cost_usd,null);
    assert.equal(result.ledger.input_tokens,usage?7:null);assert.equal(result.ledger.provider_calls,1);assert.equal(result.ledger.candidates,2);
    assert.equal(s.calls.length,4);
  }finally{await s.store.close();}
});
test('default live policy refuses before provider or query dispatch',async()=>{
  const s=await setup(OPENAI_PROFILE);let sent=0;
  try{
    await assert.rejects(retrieve_candidates(s.store,s.request,{...s,transport:async()=>{sent++;throw new Error();}}),UnsupportedCapability);
    assert.equal(sent,0);assert.equal(s.calls.length,3);assert.equal(s.ledger.snapshot().provider_calls,0);assert.equal(s.ledger.snapshot().candidates,0);
  }finally{await s.store.close();}
});
test('ledger refusal retains BudgetExhausted and no dispatch',async()=>{
  const s=await setup(FAKE_PROFILE,{max_candidates:2,max_provider_calls:0});let sent=0;
  try{
    await assert.rejects(retrieve_candidates(s.store,s.request,{...s,transport:async()=>{sent++;throw new Error();}}),BudgetExhausted);
    assert.equal(sent,0);assert.equal(s.ledger.snapshot().provider_calls,0);assert.equal(s.calls.length,3);
  }finally{await s.store.close();}
});
for(const failure of ['transport','malformed','cancel'])test(`dispatched ${failure} retains unknown usage`,async()=>{
  const s=await setup(),controller=new AbortController();let start;
  const started=new Promise(resolve=>{start=resolve;});
  try{
    const pending=retrieve_candidates(s.store,s.request,{...s,signal:controller.signal,transport:async(body,{signal})=>{
      start();
      if(failure==='cancel')await new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{const e=new Error('private cancellation');e.name='AbortError';reject(e);},{once:true}));
      if(failure==='transport')throw new Error('PRIVATE TRANSPORT CANARY');
      return Buffer.from('not-json');
    }});
    const assertion=assert.rejects(pending,error=>{
      assert.equal(String(error).includes('PRIVATE'),false);
      return failure==='cancel'?error.name==='AbortError':error instanceof ProviderUnavailable;
    });
    await started;if(failure==='cancel')controller.abort();await assertion;
    const snap=s.ledger.snapshot();assert.equal(snap.provider_calls,1);assert.equal(snap.candidates,0);assert.equal(snap.pending,0);assert.equal(snap.input_tokens,null);assert.equal(snap.cost_usd,null);assert.equal(s.calls.length,3);
  }finally{await s.store.close();}
});
