import test from 'node:test';
import assert from 'node:assert/strict';
import { PostgresRetriever } from '../dist/retrieval.js';
import { PostgresSession } from '../dist/postgres-session.js';
import { EmbeddingAdapter, FAKE_PROFILE, OPENAI_PROFILE } from '../dist/embeddings.js';
import { parse_request,parse_scope } from '../dist/contracts.js';
import { now } from '../dist/postgres-pool.js';
import { InvalidRequest, ProviderUnavailable, UnauthorizedScope, EmbeddingProfileMismatch } from '../dist/errors.js';
const input=()=>parse_request({request_id:'r',query:'GET /v1/item',collection:'c',limits:{max_candidates:8}});
const bound=()=>({scope:parse_scope({tenant_id:'t',principal_id:'p',authorization_revision:'a',grant_ids:['g']}),deadline:now()+2});
const batch=()=>({profile:FAKE_PROFILE,vectors:[[1,...Array(1535).fill(0)]],usage:{prompt_tokens:4,total_tokens:4,cost_usd:0,cost_kind:'known'},provider_calls:1,synthetic:true});
function adapter(action=async()=>batch()) { const value=new EmbeddingAdapter(async()=>new Uint8Array(),{name:'fake-byte-v1',count:()=>1});value.embed_query=action;return value; }
async function harness(body) {
  const original=PostgresSession.prototype.transaction;
  const calls=[];
  PostgresSession.prototype.transaction=async function(request,options,callback){
    calls.push(['transaction',request.required_filters]);
    return callback({candidate_branch:async operation=>operation(),dense_candidates:async(_,o)=>{calls.push(['dense',o.limit]);return [];},lexical_candidates:async o=>{calls.push(['lexical',o.limit]);return [];},identifier_candidates:async(token,o)=>{calls.push(['identifier',o.limit,token]);return [];}});
  };
  try { await body(calls); } finally { PostgresSession.prototype.transaction=original; }
}
test('constructor rejects unsafe trusted options before invoking getters',()=>{
  for(const options of [{mode:null},{mode:'dense'},{mode:'lexical',embedder:adapter()},{mode:'dense',embedder:adapter(),allow_degraded:true},{identifiers:null},{unknown:true}]) assert.throws(()=>new PostgresRetriever({},options),InvalidRequest);
  let read=false;assert.throws(()=>new PostgresRetriever({},{get mode(){read=true;return 'dense';}}),InvalidRequest);assert.equal(read,false);
});
test('hybrid embeds before one candidate lease and divides branch ceilings',async()=>harness(async calls=>{
  const embedder=adapter(async()=>{assert.equal(calls.length,0);return batch();});
  const result=await new PostgresRetriever({},{mode:'hybrid',embedder}).retrieve(input(),bound());
  assert.deepEqual(calls.map(v=>v.slice(0,2)),[['transaction',[]],['dense',3],['lexical',3],['identifier',2]]);
  assert.equal(result.usage.provider_calls,1);assert.equal(result.usage.provider_input_tokens,4);assert.equal(result.execution,'complete');assert.equal(result.versions.index,'hybrid_rrf.v1');assert.ok(Object.isFrozen(result));
}));
test('only explicit hybrid fallback recovers provider failure and keeps original budgets',async()=>harness(async calls=>{
  const embedder=adapter(async()=>{throw new ProviderUnavailable();});
  await assert.rejects(new PostgresRetriever({},{mode:'hybrid',embedder}).retrieve(input(),bound()),ProviderUnavailable);assert.equal(calls.length,0);
  const result=await new PostgresRetriever({},{mode:'hybrid',embedder,allow_degraded:true}).retrieve(input(),bound());
  assert.deepEqual(calls.filter(v=>v[0]!=='transaction').map(v=>v.slice(0,2)),[['lexical',3],['identifier',2]]);
  assert.equal(result.execution,'degraded');assert.equal(result.status,'insufficient');assert.equal(result.usage.provider_input_tokens,null);assert.equal(result.usage.provider_calls,1);assert.ok(result.limitations.some(v=>v.code==='degraded_search'));
}));
test('admission, profile and malformed usage fail before a candidate lease',async()=>harness(async calls=>{
  let invoked=0;const embedder=adapter(async()=>{invoked++;return batch();});
  for(const limits of [{max_candidates:2},{max_provider_calls:0}]) await assert.rejects(new PostgresRetriever({},{mode:'hybrid',embedder}).retrieve(parse_request({...input(),limits}),bound()),InvalidRequest);
  assert.equal(invoked,0);
  const other=new EmbeddingAdapter(async()=>new Uint8Array(),{name:'cl100k_base',count:()=>1},{profile:OPENAI_PROFILE});
  await assert.rejects(new PostgresRetriever({},{mode:'dense',embedder:other}).retrieve(input(),bound()),EmbeddingProfileMismatch);
  await assert.rejects(new PostgresRetriever({},{mode:'hybrid',embedder:adapter(async()=>({...batch(),usage:{...batch().usage,prompt_tokens:-1}})),allow_degraded:true}).retrieve(input(),bound()),InvalidRequest);
  assert.equal(calls.length,0);
}));
test('fatal scope error from embedding is never recovered',async()=>harness(async calls=>{
  await assert.rejects(new PostgresRetriever({},{mode:'hybrid',embedder:adapter(async()=>{throw new UnauthorizedScope();}),allow_degraded:true}).retrieve(input(),bound()),UnauthorizedScope);assert.equal(calls.length,0);
}));
test('embedding override ignoring deadline remains bounded and never falls back',async()=>harness(async calls=>{
  const embedder=adapter(async()=>{await new Promise(resolve=>setTimeout(resolve,30));return batch();});
  await assert.rejects(new PostgresRetriever({},{mode:'hybrid',embedder,allow_degraded:true}).retrieve(
    parse_request({...input(),limits:{...input().limits,deadline_ms:1}}),bound()),error=>error.code==='deadline_exceeded');
  assert.equal(calls.length,0);
}));
test('source operational failure remains fatal with explicit search fallback',async()=>{
  const original=PostgresSession.prototype.transaction;
  let transactions=0;
  PostgresSession.prototype.transaction=async function(request,options,body){
    transactions++;
    return body({candidate_branch:async operation=>operation(),dense_candidates:async()=>[
      {tenant_id:'t',collection:'c',document_id:'d',revision_id:'r',generation_id:'g',chunk_id:'chunk',start_byte:0,end_byte:4,
        text_sha256:'a'.repeat(64),score:0,embedding_profile:FAKE_PROFILE.profile_id,score_kind:'cosine_distance',score_direction:'lower_is_better'}],
      lexical_candidates:async()=>[],identifier_candidates:async()=>[],fetch_evidence:async()=>{throw new ProviderUnavailable();}});
  };
  try{
    await assert.rejects(new PostgresRetriever({},{mode:'hybrid',embedder:adapter(),allow_degraded:true}).retrieve(input(),bound()),ProviderUnavailable);
    assert.equal(transactions,2);
  }finally{PostgresSession.prototype.transaction=original;}
});
