import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CorrectiveRetriever} from '../dist/corrective.js';
import {IntegrityViolation} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_sources.json',import.meta.url)));
fixture.request={...fixture.request,output_profile:{renderer:'cragkit.context.v2'}};
function expand(value){
  if(typeof value==='string'&&value.startsWith('$ref:'))return expand(value.slice(5).split('.').reduce((current,key)=>current[key],fixture));
  if(Array.isArray(value))return value.map(expand);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,expand(item)]));
  return value;
}
function candidate(branch='dense',score=-.5){
  const nomination={...expand(fixture.nomination),branch,score,score_kind:branch==='dense'?'cosine_similarity':'dot_product'};
  return {...Object.fromEntries(['tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','text_sha256']
    .map(key=>[key,nomination.payload[key]])),backend:'qdrant',score,nomination};
}
function engine(value,observe=()=>{}){
  return new CorrectiveRetriever({batch_size:1,backend:{
    async search(){return {candidates:[value],degraded:false};},
    async capture(items){observe(items);return {evidence:[],sources:[],source_bytes:0,stale:false,budget_exhausted:false};}
  }});
}
const options=()=>({scope:fixture.scope,deadline:performance.now()/1000+2});
for(const [branch,score] of [['dense',-.5],['dense',1],['sparse',-20],['sparse',20]])test(`native ${branch} score ${score} keeps nomination unverified`,async()=>{
  const result=await engine(candidate(branch,score),items=>{
    assert.equal(items[0].score,score);assert.equal(items[0].nomination.score,score);
    assert.equal(items[0].nomination.payload.dense_profile.profile_id,'fake_embedding_1536_v1');
    assert(Object.isFrozen(items[0].nomination.payload));
  }).retrieve(fixture.request,options());
  assert.equal(result.result.status,'insufficient');assert.deepEqual(result.result.evidence,[]);
  assert(!JSON.stringify(result.result).includes('nomination'));
});
for(const field of ['document_id','text_sha256','start_byte','score','point_id','kind','dense_bound'])test(`contradictory handoff ${field} rejects`,async()=>{
  const value=candidate();
  if(field==='point_id')value.nomination.point_id='00000000-0000-5000-8000-000000000001';
  else if(field==='kind')value.nomination.score_kind='dot_product';
  else if(field==='dense_bound')value.score=value.nomination.score=1.01;
  else if(field==='score')value.score=.25;
  else if(field==='text_sha256')value[field]='0'.repeat(64);
  else if(field==='start_byte')value[field]++;
  else value[field]='different-document';
  await assert.rejects(engine(value).retrieve(fixture.request,options()),IntegrityViolation);
});
test('foreign nomination cannot become a corrective candidate',async()=>{
  await assert.rejects(engine(candidate()).retrieve(fixture.request,{...options(),scope:{...fixture.scope,tenant_id:'foreign'}}),IntegrityViolation);
});
