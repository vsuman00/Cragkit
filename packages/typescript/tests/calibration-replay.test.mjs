import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {replay,PROFILE} from '../../../tools/check_typescript_rerank_calibration.mjs';
import {InvalidRequest} from '../dist/errors.js';
import {RerankingAdapter} from '../dist/reranking.js';
const sha=value=>createHash('sha256').update(value).digest('hex');
const query='What is the reviewed requirement?';
function item(id,body){return {evidence_id:id,collection:'public',document_id:id,revision_id:'r1',chunk_id:id,source_locator:'synthetic:local',start_byte:0,end_byte:Buffer.byteLength(body),text:body,source_sha256:sha(body),text_sha256:sha(body)};}
const source=value=>Object.fromEntries(['collection','document_id','revision_id','source_sha256','text'].map(key=>[key,value[key]]));
const anchor=(value,claim_id='support')=>({...Object.fromEntries(['collection','document_id','revision_id','source_sha256','start_byte','end_byte','text'].map(key=>[key,value[key]])),claim_id});
const facet=(id,anchors,extra={})=>({facet_id:id,question:id,required:true,absence:'missing',anchors,...extra});
const policy=facets=>({policy_id:'synthetic-reviewed',version:'1',query_sha256:sha(query),facets});
const example=(question_id,evidence,configured=null)=>({question_id,query,evidence,sources:evidence.map(source),policy:configured});
const recording=(items,scores=[])=>items.map((value,index)=>({candidate_id:value.evidence_id,raw_score:scores[index]??index}));

test('replay uses fixed profile and exact recording identity mapping through native pipeline',async()=>{
  const a=item('a','αlpha'),b=item('b','bravo');
  const input=example('synthetic-supported',[a,b],policy([facet('a',[anchor(a)]),facet('b',[anchor(b)])]));
  const originalFetch=globalThis.fetch;globalThis.fetch=()=>assert.fail('replay attempted network fetch');
  try{
    const [result]=await replay([input],{[input.question_id]:[{candidate_id:'b',raw_score:9},{candidate_id:'a',raw_score:1}]});
    assert.deepEqual(result.order,['b','a']);
    assert.deepEqual(result.scores,[{candidate_id:'a',raw_score:1},{candidate_id:'b',raw_score:9}]);
    assert.equal(result.before.status,'sufficient');assert.equal(result.after.status,'sufficient');
    assert.equal(result.before.counting_mode,'strict');assert.equal(result.after.tokenizer,'cl100k_base');
    assert.equal(result.after.total_tokens,result.after.context_tokens+256);
    assert.ok(result.after.total_tokens<=20000);assert.ok(Object.isFrozen(result.after));
    assert.deepEqual(PROFILE,{profile_id:'cohere_v5fast_development_v1',provider:'cohere',model:'rerank-v5.0-fast',model_revision:'mutable_alias:rerank-v5.0-fast',score_kind:'relevance_score',score_direction:'higher_is_better',preprocessing_revision:'utf8-development-r1',truncation_policy:'reject'});
  }finally{globalThis.fetch=originalFetch;}
});

test('recorded ordering preserves unknown, missing, known conflict and empty abstention',async()=>{
  const a=item('a','limit three'),b=item('b','limit five'),absent=item('absent','delay ten');
  const cases=[
    example('unknown',[a]),
    example('missing',[a],policy([facet('delay',[anchor(absent)])])),
    example('conflict',[a,b],policy([facet('limit',[anchor(a,'three'),anchor(b,'five')])])),
    example('empty',[],policy([facet('delay',[anchor(absent)])])),
  ];
  const recordings=Object.fromEntries(cases.map(value=>[value.question_id,recording(value.evidence)]));
  let emptyInvocations=0;
  const original=RerankingAdapter.prototype.rank;
  RerankingAdapter.prototype.rank=async function(query,candidates,options){const result=await original.call(this,query,candidates,options);if(!candidates.length){emptyInvocations++;assert.equal(result.provider_calls,0);}return result;};
  try{
    const results=await replay(cases,recordings);
    assert.deepEqual(results.map(value=>value.after.facets[0].state),['unknown','missing','conflicting','missing']);
    assert.deepEqual(results.map(value=>value.after.status),['partial','partial','partial','insufficient']);
    assert.equal(emptyInvocations,1);assert.deepEqual(results.at(-1).order,[]);assert.deepEqual(results.at(-1).scores,[]);
    for(const result of results)assert.equal(result.after.status,result.before.status);
  }finally{RerankingAdapter.prototype.rank=original;}
});

test('known incompatible group omission stays unknown and equal scores retain input order',async()=>{
  const a=item('a','limit three'),b=item('b','limit five');
  const input=example('projection',[a],policy([facet('limit',[anchor(a,'three'),anchor(b,'five')])]));
  const [result]=await replay([input],{projection:recording([a])});
  assert.equal(result.after.facets[0].state,'unknown');assert.equal(result.after.status,'partial');
  const ties=example('ties',[b,a]);const [tied]=await replay([ties],{ties:recording([a,b],[1,1])});
  assert.deepEqual(tied.order,['b','a']);
});

test('malformed recording maps, invented references and unsupported shapes fail closed',async()=>{
  const a=item('a','support'),input=example('case',[a]);
  const badMaps=[{}, {extra:[]}, {case:[],extra:[]}, {case:[]}, {case:[{candidate_id:'invented',raw_score:1}]}, {case:[{candidate_id:'a',raw_score:NaN}]}, {case:[{candidate_id:'a',raw_score:Infinity}]}, {case:[{candidate_id:'a',raw_score:'1'}]}, {case:[{candidate_id:'a',raw_score:1,extra:true}]}];
  for(const value of badMaps)await assert.rejects(replay([input],value),InvalidRequest);
  await assert.rejects(replay([],{}),InvalidRequest);
  await assert.rejects(replay(Array(7).fill(input),{case:recording([a])}),InvalidRequest);
  await assert.rejects(replay([input,input],{case:recording([a])}),InvalidRequest);
  await assert.rejects(replay([{...input,hidden_api:'no'}],{case:recording([a])}),InvalidRequest);
  await assert.rejects(replay([{...input,query:'x'.repeat(8193)}],{case:recording([a])}),InvalidRequest);
});

test('recording accessors never execute and caller mutation cannot alter replay snapshots',async()=>{
  const a=item('a','support'),input=example('case',[a]);let calls=0;
  const map={};Object.defineProperty(map,'case',{enumerable:true,get(){calls++;return recording([a]);}});
  await assert.rejects(replay([input],map),InvalidRequest);
  const score={candidate_id:'a',get raw_score(){calls++;return 1;}};
  await assert.rejects(replay([input],{case:[score]}),InvalidRequest);assert.equal(calls,0);
  const scores=recording([a]);const pending=replay([input],{case:scores});
  input.evidence.length=0;input.sources.length=0;scores[0].candidate_id='invented';
  const [result]=await pending;assert.deepEqual(result.order,['a']);assert.equal(result.before.evidence[0].text,'support');
});


test('CLI executes through a symlink in a directory with spaces',async()=>{
  const fs=await import('node:fs'),os=await import('node:os'),path=await import('node:path');
  const {fileURLToPath}=await import('node:url');
  const {spawnSync}=await import('node:child_process');
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'cragkit replay '));
  try{
    const entry=path.join(directory,'linked replay.mjs'),payload=path.join(directory,'public.json');
    fs.symlinkSync(fileURLToPath(new URL('../../../tools/check_typescript_rerank_calibration.mjs',import.meta.url)),entry);
    const a=item('a','public synthetic evidence'),input=example('symlink-case',[a]);
    fs.writeFileSync(payload,JSON.stringify({cases:[input],recordings:{'symlink-case':recording([a])}}));
    const result=spawnSync(process.execPath,[entry,'--replay',payload],{encoding:'utf8',timeout:10000});
    assert.equal(result.status,0,result.stderr);
    assert.equal(JSON.parse(result.stdout)[0].question_id,'symlink-case');
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
