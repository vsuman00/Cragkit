import test from 'node:test';
import assert from 'node:assert/strict';
import { CorrectiveRetriever } from '../dist/corrective.js';
import { configuration, profile_snapshot, select } from '../dist/hybrid.js';
import { EmbeddingAdapter, FAKE_PROFILE, OPENAI_PROFILE } from '../dist/embeddings.js';
import { PostgresRetriever } from '../dist/retrieval.js';
import { PostgresCorrectiveBackend } from '../dist/postgres-corrective.js';
import { parse_request, parse_scope } from '../dist/contracts.js';
import { ExecutionLedger } from '../dist/execution.js';
import { EXPECTED_HISTORY, _ROLE_SQL, _CATALOG_SQL, _HISTORY_SQL, _COLLECTION_SQL } from '../dist/postgres-session.js';
import { _VECTOR_CAPABILITY_SQL } from '../dist/vector-ingestion.js';
import { OPENAI_TABLE_SQL, OPENAI_VECTOR_HISTORY, PROFILE_ROWS, SETUP_HISTORY_SQL, PROFILE_REGISTRY_SQL } from '../dist/postgres-profiles.js';
import { IntegrityViolation, UnsupportedCapability } from '../dist/errors.js';
import { _PURGE_CATALOG_SQL } from '../dist/lifecycle.js';
const adapter=profile=>new EmbeddingAdapter(async()=>{throw Error('no transport');},{name:profile.tokenizer,count:()=>1},{profile});
test('public configuration keeps default profile separate and explicit live selections before IO',async()=>{
  const live=adapter(OPENAI_PROFILE);
  assert.equal(configuration({mode:'dense',embedder:live}).embedding_profile.provider,'fake');
  const f=selectedFixture();
  await assert.rejects(new PostgresRetriever({withLease(){throw Error('unexpected database IO');}},{mode:'dense',embedder:live}).retrieve(f.request,f.bound),error=>error.code==='embedding_profile_mismatch');
  assert.doesNotThrow(()=>new PostgresRetriever({}, {mode:'dense',embedder:live,embedding_profile:OPENAI_PROFILE}));
  assert.doesNotThrow(()=>new PostgresCorrectiveBackend({resource:{},mode:'dense',embedder:live,embedding_profile:OPENAI_PROFILE}));
  assert.throws(()=>profile_snapshot(live));
  assert.deepEqual(profile_snapshot(live,OPENAI_PROFILE),OPENAI_PROFILE);
  assert.deepEqual(configuration({}).embedding_profile,FAKE_PROFILE);
});
test('purge exact graph includes both complete live vector edges and leaf inbound checks',()=>{
  assert.match(_PURGE_CATALOG_SQL,/\('chunk_vectors_openai_te3small_1536','chunks',ARRAY\['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id'\]/);
  assert.match(_PURGE_CATALOG_SQL,/\('chunk_vectors_openai_te3small_1536','index_generations',ARRAY\['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile'\]/);
  assert.match(_PURGE_CATALOG_SQL,/WHERE EXISTS \(SELECT 1 FROM known_openai_vector_storage\)/);
  assert.match(_PURGE_CATALOG_SQL,/parent\.relname='chunk_vectors_openai_te3small_1536'/);
});
function selectedFixture({preflightFailure=false,transportFailure=false,policyFailure=false}={}) {
  let leased=false,dispatched=0;
  const order=[];
  const embedder=new EmbeddingAdapter(async()=>{
    assert.equal(leased,false);dispatched++;order.push('transport');
    if(transportFailure)throw Error('synthetic transport fault');
    return Buffer.from(JSON.stringify({model:OPENAI_PROFILE.model,data:[{index:0,embedding:[1,...Array(1535).fill(0)]}],usage:{prompt_tokens:1,total_tokens:1}}));
  },{name:'cl100k_base',count:()=>1},{profile:OPENAI_PROFILE,policy:{allow_live:!policyFailure,max_cost_usd:.01,usd_per_million_tokens:.02}});
  const session={
    async admit_embedding(){order.push('admit');if(preflightFailure)throw new UnsupportedCapability();},
    async transaction(request,bound,operation){leased=true;try{return await operation({candidate_branch:fn=>fn(),dense_candidates:async()=>[],lexical_candidates:async()=>[]});}finally{leased=false;}},
  };
  const request=parse_request({query:'tiny',collection:'c'});
  const bound={scope:parse_scope({tenant_id:'t',principal_id:'p',grant_ids:[],authorization_revision:'r'}),deadline:performance.now()/1000+10};
  const config=configuration({mode:'hybrid',allow_degraded:true,identifiers:false,embedder,embedding_profile:OPENAI_PROFILE});
  return {session,request,bound,config,order,dispatched:()=>dispatched};
}
test('live selection admits before disclosure and keeps reported usage separate from billing',async()=>{
  const f=selectedFixture();let hooks=0;
  const result=await select(f.session,f.request,f.bound,f.config,OPENAI_PROFILE,()=>{hooks++;f.order.push('dispatch');});
  assert.deepEqual(f.order,['admit','dispatch','transport']);
  assert.equal(hooks,1);assert.equal(result.provider_calls,1);
  assert.equal(result.input_tokens,1);assert.equal(result.output_tokens,0);
  assert.equal(result.cost_usd,null);assert.equal(result.cost_kind,'unknown');
});
test('legacy admission refusal cannot become lexical fallback or billed call',async()=>{
  const f=selectedFixture({preflightFailure:true});let hooks=0;
  await assert.rejects(select(f.session,f.request,f.bound,f.config,OPENAI_PROFILE,()=>{hooks++;}));
  assert.equal(f.dispatched(),0);assert.equal(hooks,0);assert.deepEqual(f.order,['admit']);
});
test('dispatched failure remains one unknown-usage call during explicit fallback',async()=>{
  const f=selectedFixture({transportFailure:true});
  const result=await select(f.session,f.request,f.bound,f.config,OPENAI_PROFILE);
  assert.equal(result.provider_calls,1);assert.equal(result.degraded,true);
  assert.equal(result.input_tokens,null);assert.equal(result.output_tokens,null);
  assert.equal(result.cost_usd,null);assert.equal(result.cost_kind,'unknown');
});
test('local policy refusal during explicit fallback retains zero actual calls and known zero work',async()=>{
  const f=selectedFixture({policyFailure:true});
  const result=await select(f.session,f.request,f.bound,f.config,OPENAI_PROFILE);
  assert.equal(f.dispatched(),0);assert.equal(result.provider_calls,0);
  assert.equal(result.input_tokens,0);assert.equal(result.output_tokens,0);
  assert.equal(result.cost_usd,0);assert.equal(result.cost_kind,'known');
});
test('validated reported usage is available before a later database failure',async()=>{
  const f=selectedFixture();const observations=[];
  f.session.transaction=async()=>{
    assert.equal(observations.length,1);
    throw new UnsupportedCapability();
  };
  await assert.rejects(select(f.session,f.request,f.bound,f.config,OPENAI_PROFILE,undefined,usage=>{observations.push(usage);}));
  assert.equal(f.dispatched(),1);assert.equal(observations[0].prompt_tokens,1);
  assert.equal(observations[0].cost_kind,'estimated');
});
test('generic corrective metadata is a validated immutable constructor snapshot',async()=>{
  const versions={model:OPENAI_PROFILE.model,index:'dense_openai.v1'};
  const backend={result_versions:versions,
    async search(){return {candidates:[],degraded:false};},
    async capture(){return {evidence:[],sources:[],source_bytes:0,stale:false,budget_exhausted:false};}};
  const retriever=new CorrectiveRetriever({backend});versions.model='changed';versions.index='changed';
  const f=selectedFixture();
  const response=await retriever.retrieve({...f.request,output_profile:{renderer:'cragkit.context.v2'}},f.bound);
  assert.equal(response.result.versions.model,OPENAI_PROFILE.model);
  assert.equal(response.result.versions.index,'dense_openai.v1');
  delete backend.result_versions;
  const legacy=await new CorrectiveRetriever({backend}).retrieve({...f.request,output_profile:{renderer:'cragkit.context.v2'}},f.bound);
  assert.equal(legacy.result.versions.model,null);assert.equal(legacy.result.versions.index,null);
});
test('backend metadata rejects extra fields and invalid existing wire versions before IO',()=>{
  for(const result_versions of [{model:'m',index:'i',engine:'override'},{model:'m'},{model:1,index:null}]) {
    assert.throws(()=>new CorrectiveRetriever({backend:{result_versions,search(){throw Error('no IO');},capture(){throw Error('no IO');}}}));
  }
});
for (const reconciliationFailure of [false,true]) test(reconciliationFailure
  ? 'native corrective settlement preserves typed reconciliation failure and reported usage'
  : 'native corrective ledger retains reported usage after the subsequent database lease fails',async()=>{
  const f=selectedFixture();let leases=0,status='I';
  const client={getTransactionStatus:()=>status,release(){},async query({text}){
    if(text.startsWith('BEGIN'))status='T';
    if(text==='ROLLBACK')status='I';
    if(leases===2 && text===_ROLE_SQL)throw Object.assign(Error('injected database fault'),{code:'08006'});
    if([_ROLE_SQL,_CATALOG_SQL,_VECTOR_CAPABILITY_SQL,OPENAI_TABLE_SQL].includes(text)||text.startsWith('SELECT has_table_privilege('))return {rows:[[true]]};
    if(text===_HISTORY_SQL)return {rows:EXPECTED_HISTORY};
    if(text===SETUP_HISTORY_SQL)return {rows:OPENAI_VECTOR_HISTORY};
    if(text===PROFILE_REGISTRY_SQL)return {rows:PROFILE_ROWS};
    if(text===_COLLECTION_SQL)return {rows:[['0.1','native_fts.v1']]};
    return {rows:[]};
  }};
  const resource={config:{release_timeout:.1},async withLease(options,operation){leases++;return operation(client,options.signal??new AbortController().signal);}};
  const backend=new PostgresCorrectiveBackend({resource,mode:'dense',embedder:f.config.embedder,embedding_profile:OPENAI_PROFILE});
  const failure=new IntegrityViolation();
  class ReconcileFailure extends ExecutionLedger {
    reconcile(token,usage) { super.reconcile(token,usage);throw failure; }
  }
  const Ledger=reconciliationFailure?ReconcileFailure:ExecutionLedger;
  const ledger=new Ledger({limits:f.request.limits,deadline:f.bound.deadline});
  await assert.rejects(backend.search(f.request,{...f.bound,ledger,limit:4}),error=>reconciliationFailure?error===failure:error.code==='provider_unavailable');
  const usage=ledger.snapshot();
  assert.equal(leases,reconciliationFailure?1:2);assert.equal(usage.provider_calls,1);assert.equal(usage.input_tokens,1);
  assert.equal(usage.output_tokens,0);assert.equal(usage.cost_usd,null);assert.equal(usage.pending,0);
});
