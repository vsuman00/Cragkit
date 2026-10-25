import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {PostgresRetriever} from '../dist/retrieval.js';
import {PostgresSession,EXPECTED_HISTORY,_ROLE_SQL,_CATALOG_SQL,_HISTORY_SQL,_COLLECTION_SQL,_SCOPE_SQL} from '../dist/postgres-session.js';
import {parse_request,parse_scope} from '../dist/contracts.js';
import {now} from '../dist/postgres-pool.js';
import {RerankingAdapter,FAKE_RERANK_PROFILE} from '../dist/reranking.js';
import {Cl100kCounter} from '../dist/context.js';
import {EmbeddingAdapter,FAKE_PROFILE} from '../dist/embeddings.js';
import {InvalidRequest,IntegrityViolation,UnsupportedCapability,DeadlineExceeded,ProviderUnavailable} from '../dist/errors.js';
const sha=value=>createHash('sha256').update(value).digest('hex');
const sourceText='Café🙂';
const candidate=()=>({tenant_id:'tenant',collection:'collection',document_id:'document',revision_id:'revision',generation_id:'generation',chunk_id:'chunk',start_byte:0,end_byte:Buffer.byteLength(sourceText),text_sha256:sha(sourceText),score:1});
const sourceRow=(text=sourceText)=>['tenant','collection','document','revision','generation','chunk',sha(text),Buffer.byteLength(text),text,0,Buffer.byteLength(sourceText),Buffer.byteLength(sourceText),sourceText,sha(sourceText),'source:1','native_fts.v1',true];
const request=extra=>parse_request({request_id:'request',query:'Café',collection:'collection',output_profile:{renderer:'cragkit.context.v2'},...extra});
const bound=()=>({deadline:now()+2,scope:parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['grant']})});
class Client {
  status='I';calls=[];candidates=[candidate()];sourceRows=[sourceRow()];revoked=false;
  getTransactionStatus(){return this.status;}
  release(){}
  async query(query){
    this.calls.push(query);
    if(query.text.startsWith('BEGIN'))this.status='T';if(query.text==='ROLLBACK')this.status='I';
    if(query.text===_ROLE_SQL||query.text===_CATALOG_SQL)return {rows:[[true]]};
    if(query.text===_HISTORY_SQL)return {rows:EXPECTED_HISTORY.map(value=>[...value])};
    if(query.text===_COLLECTION_SQL)return {rows:[['0.1','native_fts.v1']]};
    if(query.text===_SCOPE_SQL)return {rows:[]};
    if(query.text.includes('WITH search AS'))return {rows:this.candidates.map(value=>[value.tenant_id,value.collection,value.document_id,value.revision_id,value.generation_id,value.chunk_id,value.start_byte,value.end_byte,value.text_sha256,value.score,'native_fts.v1','pg_catalog.simple'])};
    if(query.text.includes('r.canonical_sha256')){
      if(this.revoked)return {rows:[]};
      const rows=structuredClone(typeof this.sourceRows==='function'?this.sourceRows(query.values):this.sourceRows);
      for(const row of rows)if(row[7]>query.values[0])row[8]=null;
      return {rows};
    }
    return {rows:[]};
  }
}
class Resource {
  config={release_timeout:0.05};leases=0;active=0;client=new Client();
  async withLease(options,body){this.leases++;this.active++;try{return await body(this.client,options.signal??new AbortController().signal);}finally{this.active--;}}
}
const transport=callback=>async(body,options)=>{
  const parsed=JSON.parse(new TextDecoder().decode(body));await callback?.(parsed,options);
  return new TextEncoder().encode(JSON.stringify(parsed.candidates.map((item,index)=>({candidate_id:item.candidate_id,raw_score:100-index}))));
};
function reviewedPolicy(){
  return {policy_id:'reviewed',version:'1',query_sha256:sha('Café'),facets:[{facet_id:'meaning',question:'Meaning?',required:true,absence:'missing',anchors:[{claim_id:'support',collection:'collection',document_id:'document',revision_id:'revision',source_sha256:sha(sourceText),start_byte:0,end_byte:Buffer.byteLength(sourceText),text:sourceText}]}]};
}

test('opt-in V3 returns assessed exact text outside source leases and retains legacy behavior',async()=>{
  const resource=new Resource(),configured=reviewedPolicy();
  const retriever=new PostgresRetriever(resource,{evidence_options:{policy:configured,surrounding_bytes:0}});
  configured.facets.length=0;
  const result=await retriever.retrieve(request(),bound());
  assert.equal(result.status,'sufficient');assert.equal(result.versions.policy,'reviewed:1');assert.equal(result.context,JSON.stringify(result.evidence));
  assert.equal(result.usage.context_tokens,Math.ceil(Buffer.byteLength(result.context)/4));assert.equal(result.usage.provider_calls,0);
  assert.equal(resource.active,0);assert.equal(resource.leases,2);assert.equal(result.usage.stage_durations.at(-1).stage,'packing_complete');
  const legacy=await new PostgresRetriever(new Resource()).retrieve(parse_request({request_id:'legacy',query:'Café',collection:'collection'}),bound());
  assert.deepEqual(legacy.facets,[]);assert.equal(legacy.versions.policy,'unassessed.v0');
});

test('preflight rejects profile, policy, counter, call and live strict spend failures without leasing',async()=>{
  const liveProfile={...FAKE_RERANK_PROFILE,provider:'application',profile_id:'live-v1'};
  const live=new RerankingAdapter(transport(),{profile:liveProfile,allow_live:true});
  const cases=[
    [{},request({output_profile:{renderer:'cragkit.context.v1'}}),UnsupportedCapability],
    [{policy:{...reviewedPolicy(),query_sha256:sha('wrong')}},request(),InvalidRequest],
    [{},request({output_profile:{renderer:'cragkit.context.v2',counting_mode:'strict',tokenizer:'cl100k_base'}}),UnsupportedCapability],
    [{reranker:new RerankingAdapter(transport())},request({limits:{max_provider_calls:0}}),InvalidRequest],
    [{reranker:live},request({limits:{max_spend_usd:1}}),UnsupportedCapability],
  ];
  for(const [evidence_options,input,error] of cases){const resource=new Resource();await assert.rejects(new PostgresRetriever(resource,{evidence_options}).retrieve(input,bound()),error);assert.equal(resource.leases,0);}
  let calls=0;
  assert.throws(()=>new PostgresRetriever(new Resource(),{evidence_options:{get policy(){calls++;return null;}}}),InvalidRequest);
  assert.equal(calls,0);
  for(const rerank_limit of [0,41,1.5,true])assert.throws(()=>new PostgresRetriever(new Resource(),{evidence_options:{rerank_limit}}),InvalidRequest);
});

test('reranking closes leases before dispatch and freshly reauthorizes final source release',async()=>{
  const resource=new Resource();let dispatches=0;
  const reranker=new RerankingAdapter(transport(()=>{dispatches++;assert.equal(resource.active,0);assert.equal(resource.client.status,'I');resource.client.revoked=true;}));
  const result=await new PostgresRetriever(resource,{evidence_options:{reranker,policy:reviewedPolicy()}}).retrieve(request(),bound());
  assert.equal(dispatches,1);assert.equal(resource.leases,3);assert.equal(result.evidence.length,0);assert.equal(result.status,'insufficient');
  assert.ok(result.limitations.some(item=>item.code==='stale_evidence'));
  assert.equal(result.usage.provider_calls,1);assert.equal(result.usage.provider_input_tokens,null);assert.equal(result.usage.provider_output_tokens,null);
  assert.equal(result.usage.cost_kind,'known');assert.equal(result.usage.cost_usd,0);assert.equal(result.versions.model,FAKE_RERANK_PROFILE.profile_id);
  assert.equal(resource.client.calls.filter(query=>query.text.includes('r.canonical_sha256')).length,2);
});

test('each source round reuses immutable scope and required filters',async()=>{
  const resource=new Resource();const reranker=new RerankingAdapter(transport(()=>assert.equal(resource.active,0)));
  const input=request({required_filters:[{op:'eq',field:'document_id',value:"document' OR true --"}]});
  const result=await new PostgresRetriever(resource,{evidence_options:{reranker}}).retrieve(input,bound());assert.equal(result.evidence.length,1);
  const reads=resource.client.calls.filter(query=>query.text.includes('r.canonical_sha256'));
  assert.equal(reads.length,2);
  for(const read of reads){assert.equal(read.values.at(-1),"document' OR true --");assert.equal(read.values[7],'tenant');assert.equal(read.values[9],'auth');assert.ok(!read.text.includes('OR true'));}
  assert.equal(reads[1].values[0],16777216-Buffer.byteLength(sourceText));
});

test('shared source byte ceiling includes both authorization rounds',async()=>{
  const resource=new Resource();resource.client.sourceRows=[sourceRow(sourceText+'x'.repeat(8388608))];
  const reranker=new RerankingAdapter(transport());
  const result=await new PostgresRetriever(resource,{evidence_options:{reranker}}).retrieve(request(),bound());
  assert.deepEqual(result.evidence,[]);assert.ok(result.limitations.some(value=>value.code==='budget_exhausted'));
  const reads=resource.client.calls.filter(query=>query.text.includes('r.canonical_sha256'));
  assert.equal(reads[1].values[0],16777216-resource.client.sourceRows[0][7]);
});

test('strict output counts final serialized context with issued local counter',async()=>{
  const counter=await Cl100kCounter.create(new URL('../../../artifacts/tokenizers/cl100k_base.tiktoken',import.meta.url));
  try{
    const result=await new PostgresRetriever(new Resource(),{evidence_options:{counter,policy:reviewedPolicy()}}).retrieve(request({output_profile:{renderer:'cragkit.context.v2',tokenizer:'cl100k_base',counting_mode:'strict',envelope_reserve_tokens:7}}),bound());
    assert.equal(result.usage.context_tokens,counter.count(result.context));assert.equal(result.usage.context_counting,'strict');assert.equal(result.versions.tokenizer,'cl100k_base');assert.equal(result.status,'sufficient');
  }finally{counter.close();}
});

test('empty retrieval never invokes reranker and live cost remains unknown only when dispatched',async()=>{
  const resource=new Resource();resource.client.candidates=[];let calls=0;
  const live=new RerankingAdapter(transport(()=>calls++),{profile:{...FAKE_RERANK_PROFILE,provider:'application'},allow_live:true});
  const empty=await new PostgresRetriever(resource,{evidence_options:{reranker:live}}).retrieve(request(),bound());
  assert.equal(calls,0);assert.equal(empty.usage.provider_calls,0);assert.equal(empty.usage.cost_kind,'known');
  const result=await new PostgresRetriever(new Resource(),{evidence_options:{reranker:live}}).retrieve(request(),bound());
  assert.equal(calls,1);assert.equal(result.usage.cost_kind,'unknown');assert.equal(result.usage.cost_usd,null);
});

test('recognized explicit fallback is degraded while corruption remains fatal',async()=>{
  const adapter=new RerankingAdapter(async()=>{throw new ProviderUnavailable();});
  const result=await new PostgresRetriever(new Resource(),{evidence_options:{reranker:adapter,rerank_fallback:true}}).retrieve(request(),bound());
  assert.equal(result.execution,'degraded');assert.ok(result.limitations.some(value=>value.code==='degraded_search'));assert.equal(result.usage.provider_calls,1);
  const bad=new RerankingAdapter(async()=>new TextEncoder().encode('[{"candidate_id":"invented","raw_score":1}]'));
  await assert.rejects(new PostgresRetriever(new Resource(),{evidence_options:{reranker:bad,rerank_fallback:true}}).retrieve(request(),bound()),IntegrityViolation);
});

test('overridden adapter output is revalidated and uncooperative work is bounded and aborted',async()=>{
  for(const change of [result=>({...result,provider_calls:0}),result=>({...result,synthetic:false}),result=>({...result,order:['invented']}),result=>({...result,scores:[{candidate_id:result.order[0],raw_score:NaN}]})]){
    const adapter=new RerankingAdapter(transport());const original=adapter.rank.bind(adapter);adapter.rank=async(...args)=>change(await original(...args));
    await assert.rejects(new PostgresRetriever(new Resource(),{evidence_options:{reranker:adapter}}).retrieve(request(),bound()),IntegrityViolation);
  }
  for(const cancel of [false,true]){
    const resource=new Resource(),controller=new AbortController();let entered,signal;
    const ready=new Promise(resolve=>entered=resolve);
    const adapter=new RerankingAdapter(transport());adapter.rank=async(q,c,options)=>{signal=options.signal;entered();return new Promise(()=>{});};
    const pending=new PostgresRetriever(resource,{evidence_options:{reranker:adapter}}).retrieve(request(),{...bound(),deadline:now()+0.1,signal:controller.signal});
    const rejected=assert.rejects(pending,error=>cancel?error.name==='AbortError':error instanceof DeadlineExceeded);
    await ready;if(cancel)controller.abort();await rejected;assert.equal(signal.aborted,true);assert.equal(resource.active,0);
    assert.equal(resource.client.calls.filter(query=>query.text.includes('r.canonical_sha256')).length,1);
  }
});


test('embedding and reranking reserve shared call allowance before either dispatch',async()=>{
  let calls=0;
  const embedder=new EmbeddingAdapter(async()=>new Uint8Array(),{name:'fake-byte-v1',count:()=>1});
  embedder.embed_query=async()=>{calls++;return {profile:FAKE_PROFILE,vectors:[[1,...Array(1535).fill(0)]],usage:{prompt_tokens:4,total_tokens:4,cost_usd:0,cost_kind:'known'},provider_calls:1,synthetic:true};};
  const reranker=new RerankingAdapter(transport(()=>assert.fail('empty candidate rerank')));
  const resource=new Resource();
  await assert.rejects(new PostgresRetriever(resource,{mode:'dense',embedder,evidence_options:{reranker}}).retrieve(request({limits:{max_provider_calls:1}}),bound()),InvalidRequest);
  assert.equal(calls,0);assert.equal(resource.leases,0);
  const original=PostgresSession.prototype.transaction;
  PostgresSession.prototype.transaction=async function(input,options,body){return body({candidate_branch:async operation=>operation(),dense_candidates:async()=>[]});};
  try{
    const result=await new PostgresRetriever(resource,{mode:'dense',embedder,evidence_options:{reranker}}).retrieve(request({limits:{max_provider_calls:2}}),bound());
    assert.equal(calls,1);assert.equal(result.usage.provider_calls,1);assert.equal(result.usage.provider_input_tokens,4);
  }finally{PostgresSession.prototype.transaction=original;}
});

test('configured rerank candidate cap retains visible truncation',async()=>{
  const resource=new Resource();resource.client.candidates.push({...candidate(),chunk_id:'second'});
  const adapter=new RerankingAdapter(transport(parsed=>assert.equal(parsed.candidates.length,1)));
  const result=await new PostgresRetriever(resource,{evidence_options:{reranker:adapter,rerank_limit:1}}).retrieve(request(),bound());
  assert.equal(result.evidence.length,1);assert.ok(result.limitations.some(value=>value.code==='truncated_evidence'));
});


test('large authorized seed arrays omit whole spans before the renderer input ceiling',async()=>{
  const resource=new Resource(),text='a'.repeat(32768),digest=sha(text);
  resource.client.candidates=Array.from({length:9},(_,i)=>({...candidate(),document_id:`d${i}`,chunk_id:`k${i}`,end_byte:32768,text_sha256:digest}));
  resource.client.sourceRows=values=>[[values[1],values[2],values[3],values[4],values[5],values[6],digest,32768,text,0,32768,32768,text,digest,'source:1','native_fts.v1',true]];
  const result=await new PostgresRetriever(resource,{evidence_options:{surrounding_bytes:0}}).retrieve(request({limits:{max_context_tokens:1000000}}),bound());
  assert.ok(result.evidence.length>0&&result.evidence.length<9);assert.ok(Buffer.byteLength(result.context)<=262144);
  assert.ok(result.limitations.some(value=>value.code==='truncated_evidence'));assert.ok(result.limitations.some(value=>value.code==='budget_exhausted'));
  assert.equal(resource.client.calls.filter(query=>query.text.includes('r.canonical_sha256')).length,9);
});


test('adapter mutation cannot hide original inference truncation metadata',async()=>{
  const resource=new Resource(),text='x'.repeat(20000);
  resource.client.candidates=[{...candidate(),end_byte:Buffer.byteLength(text),text_sha256:sha(text)}];
  resource.client.sourceRows=[['tenant','collection','document','revision','generation','chunk',sha(text),Buffer.byteLength(text),text,0,Buffer.byteLength(text),Buffer.byteLength(text),text,sha(text),'source:1','native_fts.v1',true]];
  const profile={...FAKE_RERANK_PROFILE,truncation_policy:'utf8_prefix'};
  const adapter=new RerankingAdapter(transport(),{profile});
  adapter.rank=async(query,views)=>{
    const id=views[0].candidate_id;
    views[0].text='x';
    return {profile,order:[id],scores:[{candidate_id:id,raw_score:1}],truncations:[],degraded:false,provider_calls:1,synthetic:true};
  };
  await assert.rejects(new PostgresRetriever(resource,{evidence_options:{reranker:adapter}}).retrieve(request(),bound()),IntegrityViolation);
  assert.equal(resource.active,0);
});
