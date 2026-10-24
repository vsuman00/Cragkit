import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fuse } from '../dist/fusion.js';
import { InvalidRequest, IntegrityViolation } from '../dist/errors.js';
const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/identifier_fusion.json',import.meta.url),'utf8'));
for(const c of fixture.cases)test(c.id,()=>{
  const before=structuredClone(c.lists);const result=fuse(c.lists,c.options);
  assert.deepEqual(result.map(x=>x.candidate.document_id),c.expected.map(x=>x[0]));
  result.forEach((x,i)=>assert.ok(Math.abs(x.score-c.expected[i][1])<=fixture.tolerance));
  assert.deepEqual(c.lists,before);
});
for(const c of fixture.invalid)test(c.id,()=>assert.throws(()=>fuse(c.lists,c.options),c.error==='invalid_request'?InvalidRequest:IntegrityViolation));
test('strict limits, descriptors and detached snapshots',()=>{
  for(const options of [{k:true},{max_candidates:false},{k:-1},{max_candidates:1001},null,[]])assert.throws(()=>fuse([],options),InvalidRequest);
  const branches=structuredClone(fixture.cases[0].lists);const result=fuse(branches);const before=structuredClone(result);
  branches[0].candidates[0].document_id='changed';assert.deepEqual(result,before);
  const getter=structuredClone(fixture.cases[0].lists);Object.defineProperty(getter[0].candidates,'0',{get(){throw Error('must not read');},enumerable:true});
  assert.throws(()=>fuse(getter),InvalidRequest);
});
test('replays count once and provenance uses canonical list ID',()=>{
  const branch=structuredClone(fixture.cases[0].lists[0]);branch.list_id='z';branch.facet_id='facet';
  const replay=structuredClone(branch);replay.list_id='a';
  const result=fuse([branch,replay]);
  assert.ok(result.every(x=>x.contributions.length===1&&x.contributions[0].list_id==='a'&&x.contributions[0].profile==='fake_embedding_1536_v1'));
  delete branch.candidates[0].embedding_profile;assert.throws(()=>fuse([branch]),InvalidRequest);
});
test('bounded lists, entries and union',()=>{
  const branch=structuredClone(fixture.cases[1].lists[0]);
  branch.candidates=Array(1000).fill(branch.candidates[0]);assert.equal(fuse([branch]).length,1);
  branch.candidates.push(branch.candidates[0]);assert.throws(()=>fuse([branch]),InvalidRequest);
  const empty=Array.from({length:36},(_,index)=>({...branch,list_id:String(index),candidates:[]}));
  assert.deepEqual(fuse(empty),[]);assert.throws(()=>fuse([...empty,{...branch,list_id:'extra',candidates:[]}]),InvalidRequest);
  branch.candidates=Array.from({length:1000},(_,index)=>({...fixture.cases[1].lists[0].candidates[0],document_id:String(index)}));
  assert.equal(fuse([branch],{max_candidates:1000}).length,1000);
  assert.throws(()=>fuse([branch],{max_candidates:999}),InvalidRequest);
});

test('sparse arrays with replacement properties are rejected before traversal',()=>{
  const list=Array(1);list.extra=fixture.cases[1].lists[0];
  assert.throws(()=>fuse(list),InvalidRequest);
  const branch=structuredClone(fixture.cases[1].lists[0]);
  branch.candidates=Array(1);branch.candidates.extra=fixture.cases[1].lists[0].candidates[0];
  assert.throws(()=>fuse([branch]),InvalidRequest);
  class CustomArray extends Array {}
  assert.throws(()=>fuse(new CustomArray()),InvalidRequest);
});
