import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {QdrantCorrectiveBackend} from '../dist/qdrant-corrective.js';
import {CorrectiveRetriever} from '../dist/corrective.js';
import {QdrantSearchStore} from '../dist/qdrant.js';
import {PostgresQdrantSourceStore} from '../dist/qdrant-source.js';
import {PoolResource,parse_pool_config} from '../dist/postgres-pool.js';
import {ExecutionLedger} from '../dist/execution.js';
import {parse_request,parse_scope} from '../dist/requests.js';
import {OPENAI_PROFILE} from '../dist/embeddings.js';
import {EmbeddingProfileMismatch,ProviderUnavailable,UnsupportedCapability} from '../dist/errors.js';
import {SOURCE_ROW_FIELDS} from '../dist/qdrant-source-contract.js';
import {AUTHORITY_HISTORY,AUTHORITY_ROLE_SQL,AUTHORITY_CATALOG_SQL,AUTHORITY_HISTORY_SQL,AUTHORITY_FINGERPRINT_SQL,EXPECTED_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_sources.json',import.meta.url)));
function expand(v){
  if(typeof v==='string'&&v.startsWith('$ref:'))return expand(v.slice(5).split('.').reduce((current,key)=>current[key],fixture));
  if(Array.isArray(v))return v.map(expand);
  if(v&&typeof v==='object'){
    if(v.encoding==='utf8')return Buffer.from(v.value);
    if(v.encoding==='hex')return Buffer.from(v.value,'hex');
    return Object.fromEntries(Object.entries(v).map(([key,item])=>[key,expand(item)]));
  }return v;
}
const config=Object.fromEntries(['backend_namespace','physical_collection','collection_incarnation','dense_profile','sparse_profile'].map(key=>[key,expand(fixture.base_row[key])]));
const request=parse_request({...fixture.request,request_id:'qcc',output_profile:{renderer:'cragkit.context.v2'},limits:{max_candidates:1,max_attempts:1,max_provider_calls:1}});
const scope=parse_scope(fixture.scope),counter={name:'fake-byte-v1',count:text=>Buffer.byteLength(text)};
const options=()=>({scope,deadline:performance.now()/1000+5,signal:new AbortController().signal});
const wire=result=>Buffer.from(JSON.stringify({result,status:'ok'}));

async function setup({broken=false}={}){
  const state={reads:0,searches:0,models:0,revoked:false,outage:false,wait:null,ends:0,entered:()=>{}};
  const transport={bounded_responses:true,cancellation_safe:true,closed:false,
    async request(method,path){
      if(path==='/')return Buffer.from('{"version":"1.20.0"}');
      if(path==='/cluster')return wire({status:'disabled'});
      if(method==='GET')return wire({config:{params:{vectors:{dense:{size:1536,distance:'Cosine'}},sparse_vectors:{sparse:{}},replication_factor:1,write_consistency_factor:1}}});
      state.searches++;const n=expand(fixture.nomination);return wire({points:[{id:n.point_id,score:n.score,payload:n.payload}]});
    },async close(){this.closed=true;}};
  const pool={async connect(){return {status:'I',getTransactionStatus(){return this.status;},release(){},async query(q){
    if(q.text.startsWith('BEGIN')){this.status='T';return {rows:[]};}
    if(q.text==='ROLLBACK'||q.text==='COMMIT'){this.status='I';return {rows:[]};}
    if(q.text===AUTHORITY_ROLE_SQL||q.text===AUTHORITY_CATALOG_SQL)return {rows:[[true]]};
    if(q.text===AUTHORITY_HISTORY_SQL)return {rows:AUTHORITY_HISTORY.map(row=>[...row])};
    if(q.text===AUTHORITY_FINGERPRINT_SQL)return {rows:[[EXPECTED_AUTHORITY_FINGERPRINT]]};
    if(q.text.includes('FROM cragkit_qdrant.members m')){
      state.reads++;state.entered();if(state.wait)await state.wait;if(state.outage)throw new Error('private authority details');
      const row=expand(fixture.base_row);
      if(state.revoked&&state.reads>1){row.principal_ids=[];row.grant_ids=[];}
      if(row.source_bytes>q.values[0]){row.canonical_utf8=null;row.excerpt_utf8=null;}
      return {rows:[SOURCE_ROW_FIELDS.map(key=>row[key])]};
    }return {rows:[]};
  }};},async end(){state.ends++;}};
  const resource=new PoolResource(parse_pool_config({host:'example.invalid',dbname:'fixture',user:'reader',sslrootcert:'/fake/ca',passfile:'/fake/pass'}),{pool});
  const candidates=new QdrantSearchStore(config,transport),sources=new PostgresQdrantSourceStore(resource,config),o=options();
  await candidates.initialize({deadline:o.deadline,signal:o.signal});await sources.initialize({deadline:o.deadline,signal:o.signal});
  const embedding=async()=>{
    state.models++;if(broken)throw new Error('private provider failure');
    return Buffer.from(JSON.stringify({model:config.dense_profile.model,data:[{index:0,embedding:[1,...Array(1535).fill(0)]}],
      usage:{prompt_tokens:Buffer.byteLength(request.query),total_tokens:Buffer.byteLength(request.query)}}));
  };
  const backend=new QdrantCorrectiveBackend(candidates,sources,{embedding_transport:embedding,token_counter:counter});
  const close=async()=>{await sources.close();await candidates.close();await resource.close();assert.equal(state.ends,0);};
  return {backend,candidates,sources,resource,state,transport,embedding,o,close};
}

test('native composition charges once and returns exact source with borrowed ownership',async()=>{
  const x=await setup();try{
    const result=await new CorrectiveRetriever({backend:x.backend,batch_size:1}).retrieve(request,x.o),usage=result.diagnostics.ledger;
    assert.equal(result.result.status,'partial');assert.equal(result.result.evidence.length,1);
    const item=result.result.evidence[0],canonical=expand(fixture.base_row.canonical_utf8);
    assert.equal(item.text,canonical.subarray(item.start_byte,item.end_byte).toString('utf8'));
    assert.equal(usage.candidates,1);assert.equal(usage.attempts,1);assert.equal(usage.provider_calls,1);
    assert.equal(x.state.models,1);assert.equal(x.state.searches,1);assert.equal(x.state.reads,2);
    const fresh=x.sources.open_request(request,x.o);await fresh.close();assert.equal(x.transport.closed,false);
    assert(!JSON.stringify(result.result).includes('nomination'));assert(!JSON.stringify(result.result).includes('private_source'));
  }finally{await x.close();}
});
for(const mode of ['lexical','hybrid'])test(`unsupported ${mode} refuses before provider`,async()=>{
  const x=await setup();try{
    assert.throws(()=>new QdrantCorrectiveBackend(x.candidates,x.sources,{embedding_transport:x.embedding,token_counter:counter,mode}),UnsupportedCapability);
    assert.equal(x.state.models+x.state.searches+x.state.reads,0);
  }finally{await x.close();}
});
test('zero provider budget prevents transport and search',async()=>{
  const x=await setup();try{
    const result=await new CorrectiveRetriever({backend:x.backend,batch_size:1}).retrieve({...request,limits:{...request.limits,max_provider_calls:0}},x.o);
    assert.equal(result.result.status,'insufficient');assert.equal(x.state.models+x.state.searches+x.state.reads,0);
    assert.equal(result.diagnostics.ledger.candidates,0);assert.equal(result.diagnostics.ledger.provider_calls,0);
  }finally{await x.close();}
});
for(const fault of ['revoked','outage','bytes'])test(`capture ${fault} never becomes released source`,async()=>{
  const x=await setup();try{
    const ledger=new ExecutionLedger({limits:request.limits,deadline:x.o.deadline});
    const selected=(await x.backend.search(request,{...x.o,limit:1,ledger})).candidates;
    x.state.revoked=fault==='revoked';x.state.outage=fault==='outage';
    const work=()=>x.backend.capture(selected,{...x.o,request,ledger,max_source_bytes:fault==='bytes'?expand(fixture.base_row).source_bytes:16777216});
    if(fault==='outage')await assert.rejects(work(),ProviderUnavailable);
    else {const result=await work();assert.deepEqual(result.evidence,[]);assert.deepEqual(result.sources,[]);assert(fault==='revoked'?result.stale:result.budget_exhausted);}
    const handle=x.sources.open_request(request,x.o);await handle.close();
  }finally{await x.close();}
});
test('profile mismatch rejects before work',async()=>{
  const x=await setup();try{
    const other=new QdrantSearchStore({...config,dense_profile:OPENAI_PROFILE,sparse_profile:null},x.transport);
    assert.throws(()=>new QdrantCorrectiveBackend(other,x.sources,{embedding_transport:x.embedding,token_counter:counter}),EmbeddingProfileMismatch);
    assert.equal(x.state.models+x.state.searches+x.state.reads,0);await other.close();
  }finally{await x.close();}
});
test('source cancellation drains its handle and preserves caller stores',async()=>{
  const x=await setup();try{
    const ledger=new ExecutionLedger({limits:request.limits,deadline:x.o.deadline});
    const selected=(await x.backend.search(request,{...x.o,limit:1,ledger})).candidates;
    let release,enter;x.state.wait=new Promise(resolve=>release=resolve);const entered=new Promise(resolve=>enter=resolve);x.state.entered=enter;
    const controller=new AbortController();
    const pending=x.backend.capture(selected,{...x.o,signal:controller.signal,request,ledger,max_source_bytes:16777216});
    const rejected=assert.rejects(pending,error=>error.name==='AbortError');await entered;
    controller.abort();release();await rejected;
    const handle=x.sources.open_request(request,x.o);await handle.close();
  }finally{await x.close();}
});
test('dispatched provider failure preserves unknown usage without search',async()=>{
  const x=await setup({broken:true});try{
    const ledger=new ExecutionLedger({limits:request.limits,deadline:x.o.deadline});
    await assert.rejects(x.backend.search(request,{...x.o,ledger,limit:1}),ProviderUnavailable);
    const usage=ledger.snapshot();assert.equal(usage.provider_calls,1);assert.equal(usage.pending,0);assert.equal(usage.input_tokens,null);
    assert.equal(x.state.searches+x.state.reads,0);
  }finally{await x.close();}
});
