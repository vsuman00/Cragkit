import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {
  encode_manifest, encode_stage_intent, encode_security_intent, encode_purge_intent,
  encode_dense_replay, encode_sparse_replay, restore_dense_replay, restore_sparse_replay,
} from '../dist/qdrant-manifest.js';
import {verify_dense_readback,verify_sparse_readback} from '../dist/qdrant-vectors.js';
import {point_id} from '../dist/qdrant-contract.js';
import {InvalidRequest,IntegrityViolation,UnsupportedCapability,EmbeddingProfileMismatch} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const hash=value=>createHash('sha256').update(value).digest('hex');
const text=fixture.source_revision.canonical_utf8.value;
const denseProfile=fixture.profiles.dense;
const sparseProfile=fixture.profiles.sparse;
const unit=()=>Array.from({length:1536},(_,i)=>i===0?1:0);
for(const row of fixture.replay_goldens){
  test(`shared replay golden: ${row.id}`,()=>{
    let replay;
    if(row.kind==='dense'){
      const values=Array(row.original_encoding.dimensions).fill(0);
      for(const [index,value] of row.original_encoding.nonzero)values[index]=value;
      if(row.original_encoding.negative_zero_index!==undefined)values[row.original_encoding.negative_zero_index]=-0;
      replay=encode_dense_replay(values,denseProfile);
      const restored=restore_dense_replay(replay.blob,row.blob_sha256,row.input_sha256,denseProfile);
      assert.equal(restored.input_sha256,row.input_sha256);
    }else{
      replay=encode_sparse_replay(row.indices,row.values,sparseProfile);
      const restored=restore_sparse_replay(replay.blob,row.blob_sha256,row.input_sha256,sparseProfile);
      assert.equal(restored.input_sha256,row.input_sha256);
    }
    assert.equal(replay.blob.length,row.blob_bytes);
    assert.equal(replay.blob_sha256,row.blob_sha256);
    assert.equal(replay.input_sha256,row.input_sha256);
  });
}
for(const [id,row] of Object.entries(fixture.operation_goldens)){
  test(`shared operation golden: ${id}`,()=>{
    const encoder=id==='purge'?encode_purge_intent:id==='bootstrap_stage'?encode_stage_intent:encode_security_intent;
    const result=encoder(row.record);
    assert.deepEqual(result.value,row.value);
    assert.equal(result.sha256,row.sha256);
    assert.equal(result.encoded_bytes.length,row.encoded_bytes);
  });
}
function record(){
  return {
    ...fixture.physical,
    tenant_id:fixture.document.tenant_id,collection:fixture.document.collection,
    document_id:fixture.document.document_id,revision_id:fixture.source_revision.revision_id,
    generation_id:fixture.intent.generation_id,source_sha256:fixture.source_revision.source_sha256,
    source_bytes:fixture.source_revision.source_bytes,source_locator:fixture.source_revision.source_locator,
    parser_id:fixture.source_revision.parser_id,chunker_profile:fixture.intent.chunker_profile,
    dense_profile:structuredClone(denseProfile),sparse_profile:structuredClone(sparseProfile),
    members:fixture.members.map(member=>({chunk_id:member.chunk_id,point_id:member.point_id,
      start_byte:member.start_byte,end_byte:member.end_byte,text_sha256:member.text_sha256,
      dense_input_sha256:member.dense.vector_sha256,sparse_input_sha256:member.sparse.vector_sha256})),
  };
}
function stage(){
  return {intent_id:'intent-2',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
    manifest_sha256:fixture.intent.manifest_sha256,expected_active_generation_id:'gen-1',
    expected_authorization_revision:'auth-1',expected_mutation_epoch:1,initial_authorization:null};
}
function authorization(){
  return {authorization_revision:'auth-2',principal_ids:['z','a','a','雪','é'],grant_ids:['g2','g1'],
    language:null,kind:'guide',tag:null,tombstoned:false};
}
function security(){
  return {action:'update_authorization',intent_id:'security-2',tenant_id:'tenant-a',collection:'docs',
    document_id:'doc-1',expected_authorization_revision:'auth-1',expected_mutation_epoch:1,
    authorization:authorization()};
}
function assertEncoded(result){
  assert.ok(Object.isFrozen(result));
  assert.ok(Object.isFrozen(result.value));
  assert.ok(Object.isFrozen(result.encoded_bytes));
  assert.equal(hash(Buffer.from(result.encoded_bytes)),result.sha256);
  assert.deepEqual(JSON.parse(Buffer.from(result.encoded_bytes).toString('utf8')),result.value);
}

test('manifest and stage match shared exact tuple goldens',()=>{
  const manifest=encode_manifest(record(),text);
  assertEncoded(manifest);
  assert.deepEqual(manifest.value,fixture.canonical_tuples.manifest);
  assert.equal(manifest.sha256,fixture.intent.manifest_sha256);
  const intent=encode_stage_intent(stage());
  assertEncoded(intent);
  assert.deepEqual(intent.value,fixture.canonical_tuples.stage_intent);
  assert.equal(intent.sha256,fixture.intent.payload_sha256);
});

test('member ordering and all returned nested values are immutable snapshots',()=>{
  const input=record();input.members.reverse();
  const encoded=encode_manifest(input,text);
  input.members[0].chunk_id='changed';input.dense_profile.model='changed';
  assert.equal(encoded.sha256,fixture.intent.manifest_sha256);
  assert.throws(()=>{encoded.value[17][0][0][0]='changed';},TypeError);
  assert.throws(()=>{encoded.encoded_bytes[0]=0;},TypeError);
});

test('canonical UTF8 preserves BOM CRLF NUL and multibyte excerpt bytes',()=>{
  const source='\uFEFFa\0café\r\n雪';
  const bytes=Buffer.from(source,'utf8');
  const input=record();
  input.source_bytes=bytes.length;input.source_sha256=hash(bytes);
  input.members=input.members.slice(0,1);
  input.members[0].start_byte=0;input.members[0].end_byte=bytes.length;
  input.members[0].text_sha256=input.source_sha256;
  assert.doesNotThrow(()=>encode_manifest(input,source));
  assert.throws(()=>encode_manifest(input,'\uD800'),InvalidRequest);
  assert.throws(()=>encode_manifest(input,Buffer.from(source)),InvalidRequest);
});

test('source and member contradictions fail integrity while malformed shapes fail admission',()=>{
  const mutations=[
    r=>{r.source_sha256='0'.repeat(64);},r=>{r.source_bytes++;},
    r=>{r.members[0].text_sha256='0'.repeat(64);},r=>{r.members[0].end_byte=6;},
    r=>{r.members[0].point_id=r.members[1].point_id;},
    r=>{r.members.push({...r.members[0]});},
    r=>{r.sparse_profile=null;},
  ];
  for(const mutate of mutations){const input=record();mutate(input);assert.throws(()=>encode_manifest(input,text),IntegrityViolation);}
  for(const mutate of [r=>{delete r.source_locator;},r=>{r.extra='x';},r=>{r.members=[];},
    r=>{r.members[0].start_byte=true;},r=>{r.source_sha256='bad';},
    r=>{r.members=Array(65).fill(r.members[0]);},r=>{r.members[0].end_byte=1.5;}]){
    const input=record();mutate(input);assert.throws(()=>encode_manifest(input,text),InvalidRequest);
  }
  const unsupported=record();unsupported.dense_profile.model='other-model';
  assert.throws(()=>encode_manifest(unsupported,text),UnsupportedCapability);
});

test('dense-only manifest binds null sparse descriptor and seal with empty tuple profile ID',()=>{
  const input=record();input.sparse_profile=null;
  for(const member of input.members){
    member.sparse_input_sha256=null;
    const tuple=[...fixture.members.find(row=>row.chunk_id===member.chunk_id).identity_tuple];
    tuple[11]='';member.point_id=point_id(tuple);
  }
  assert.doesNotThrow(()=>encode_manifest(input,text));
});

test('source and metadata size limits are checked before retaining large copies',()=>{
  assert.throws(()=>encode_manifest(record(),'a'.repeat(16777217)),InvalidRequest);
  const input=record();input.source_locator='x'.repeat(257);
  assert.throws(()=>encode_manifest(input,text),InvalidRequest);
  const long=record();long.members[0].end_byte=32771;
  const source='a'.repeat(32771);long.source_bytes=source.length;long.source_sha256=hash(source);
  assert.throws(()=>encode_manifest(long,source),InvalidRequest);
});

test('malformed point IDs fail admission while well-formed contradictions fail integrity', () => {
  const malformed = record();
  malformed.members[0].point_id = 'not-a-uuid';
  assert.throws(() => encode_manifest(malformed, text), InvalidRequest);
  const contradictory = record();
  contradictory.members[0].point_id = '00000000-0000-4000-8000-000000000000';
  assert.throws(() => encode_manifest(contradictory, text), IntegrityViolation);
});

test('native metadata guards reject cycles proxies accessors and custom containers without hooks',()=>{
  let calls=0;
  const accessor=record();Object.defineProperty(accessor,'members',{get(){calls++;return [];}});
  const proxy=new Proxy(record(),{ownKeys(){calls++;throw Error('private');}});
  const cycle=record();cycle.members[0].extra=cycle;
  class Custom{}
  const custom=Object.assign(new Custom(),record());
  for(const input of [accessor,proxy,cycle,custom])assert.throws(()=>encode_manifest(input,text),InvalidRequest);
  assert.equal(calls,0);
});

test('stage creation binds initial sorted ACL and exact bootstrap fences',()=>{
  const input=stage();input.expected_active_generation_id=null;
  input.initial_authorization={...authorization(),authorization_revision:'auth-1'};
  const encoded=encode_stage_intent(input);assertEncoded(encoded);
  assert.deepEqual(encoded.value.at(-1),['auth-1',['a','z','é','雪'],['g1','g2'],null,'guide',null,'false']);
  for(const mutate of [r=>{r.expected_active_generation_id='old';},r=>{r.expected_mutation_epoch=2;},
    r=>{r.initial_authorization.authorization_revision='other';},r=>{r.initial_authorization.tombstoned=true;}]){
    const invalid=structuredClone(input);mutate(invalid);assert.throws(()=>encode_stage_intent(invalid),InvalidRequest);
  }
});

test('security and purge tuples bind complete replacement security and safe epochs',()=>{
  const input=security();const encoded=encode_security_intent(input);assertEncoded(encoded);
  assert.deepEqual(encoded.value,['cragkit.qdrant.intent.v1','update_authorization','security-2','tenant-a','docs','doc-1','auth-1','1',
    ['auth-2',['a','z','é','雪'],['g1','g2'],null,'guide',null,'false']]);
  const tombstone=security();tombstone.action='tombstone';tombstone.authorization.tombstoned=true;
  const tombstoneEncoded=encode_security_intent(tombstone);
  const purge={intent_id:'purge-2',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
    tombstone_intent_payload_sha256:tombstoneEncoded.sha256,expected_authorization_revision:'auth-2',expected_mutation_epoch:2};
  const result=encode_purge_intent(purge);assertEncoded(result);
  assert.deepEqual(result.value,['cragkit.qdrant.intent.v1','purge','purge-2','tenant-a','docs','doc-1',tombstoneEncoded.sha256,'auth-2','2']);
  const bad=security();bad.action='tombstone';assert.throws(()=>encode_security_intent(bad),InvalidRequest);
  for(const epoch of [true,-1,.5,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>encode_stage_intent({...stage(),expected_mutation_epoch:epoch}),InvalidRequest);
  const excessive=security();excessive.authorization.principal_ids=Array(65).fill('same');
  assert.throws(()=>encode_security_intent(excessive),InvalidRequest);
  const metadata=security();metadata.authorization.kind='é'.repeat(513);
  assert.throws(()=>encode_security_intent(metadata),InvalidRequest);
});

test('original replay preserves float64 signed zero and near-norm-boundary admission',()=>{
  const original=unit();original[0]=1.00099999;original[1]=-0;
  const replay=encode_dense_replay(original,denseProfile);
  assert.ok(Object.isFrozen(replay));assert.ok(Object.isFrozen(replay.blob));
  assert.equal(hash(Buffer.from(replay.blob)),replay.blob_sha256);
  const bytes=Buffer.from(replay.blob);
  assert.equal(Object.is(bytes.readDoubleLE(bytes.length-1536*8+8),-0),true);
  const restored=restore_dense_replay(replay.blob,replay.blob_sha256,replay.input_sha256,denseProfile);
  assert.equal(restored.input_sha256,replay.encoded.input_sha256);
  assert.ok(restored.values[0]-1>0.001);
  verify_dense_readback(restored,unit());
  original[0]=0;assert.notEqual(replay.encoded.values[0],0);
  assert.throws(()=>{replay.blob[0]=0;},TypeError);
});

test('sparse original replay restores exact B1 identity and canonical zero indices',()=>{
  const replay=encode_sparse_replay([-0,7],[1.00000001,.5],sparseProfile);
  const restored=restore_sparse_replay(replay.blob,replay.blob_sha256,replay.input_sha256,sparseProfile);
  assert.equal(restored.input_sha256,replay.input_sha256);
  verify_sparse_readback(restored,[0,7],[1,.5]);
});

test('replay strict layouts and authority expected hashes reject corruption',()=>{
  const replay=encode_dense_replay(unit(),denseProfile);
  const cases=[[],[...replay.blob,0],replay.blob.slice(0,-1),Uint8Array.from(replay.blob),Array(20000).fill(0),
    replay.blob.map((value,i)=>i===0?0:value),replay.blob.map((value,i)=>i===0?true:value)];
  for(const blob of cases)assert.throws(()=>restore_dense_replay(blob,replay.blob_sha256,replay.input_sha256,denseProfile),IntegrityViolation);
  assert.throws(()=>restore_dense_replay(replay.blob,'0'.repeat(64),replay.input_sha256,denseProfile),IntegrityViolation);
  assert.throws(()=>restore_dense_replay(replay.blob,replay.blob_sha256,'0'.repeat(64),denseProfile),IntegrityViolation);
  assert.throws(()=>restore_dense_replay(replay.blob,replay.blob_sha256,replay.input_sha256,{...denseProfile,model:'other'}),IntegrityViolation);
  const sparse=encode_sparse_replay([1],[1],sparseProfile);
  assert.throws(()=>restore_dense_replay(sparse.blob,sparse.blob_sha256,sparse.input_sha256,denseProfile),IntegrityViolation);
  assert.throws(()=>encode_dense_replay(unit(),{...denseProfile,model:'other'}),EmbeddingProfileMismatch);
});

test('restore rejects forged domain count nonfinite originals even with recomputed blob hash',()=>{
  const replay=encode_dense_replay(unit(),denseProfile);
  for(const mutate of [bytes=>{bytes[0]=0;},bytes=>{bytes.writeUInt32LE(1535,34);},
    bytes=>{bytes.writeDoubleLE(Infinity,bytes.length-8);}]){
    const bytes=Buffer.from(replay.blob);mutate(bytes);
    assert.throws(()=>restore_dense_replay(Array.from(bytes),hash(bytes),replay.input_sha256,denseProfile),IntegrityViolation);
  }
});

test('restore preserves unknown operational errors',()=>{
  const replay=encode_dense_replay(unit(),denseProfile);
  const sparse=encode_sparse_replay([1],[1],sparseProfile);
  const original=Math.fround;const failure=new RangeError('synthetic operational failure');
  try{
    Math.fround=()=>{throw failure;};
    assert.throws(()=>restore_dense_replay(replay.blob,replay.blob_sha256,replay.input_sha256,denseProfile),error=>error===failure);
    assert.throws(()=>restore_sparse_replay(sparse.blob,sparse.blob_sha256,sparse.input_sha256,sparseProfile),error=>error===failure);
  }finally{Math.fround=original;}
});

test('existing wire identities accept non-ASCII whitespace and reject ASCII-only blank', () => {
  for (const id of ['\u00a0', '\ufeff']) {
    const input = stage();
    input.intent_id = id;
    assert.equal(encode_stage_intent(input).value[2], id);
    const change = security();
    change.authorization.principal_ids = [id];
    assert.deepEqual(encode_security_intent(change).value.at(-1)[1], [id]);
  }
  assert.throws(() => encode_stage_intent({...stage(), intent_id: ' \t\r\n\f\v'}), InvalidRequest);
});

test('integral contradictory spans fail integrity before excerpt size admission', () => {
  for (const [start, end] of [[0, 0], [2, 1], [0, 40000]]) {
    const input = record();
    input.members[0].start_byte = start;
    input.members[0].end_byte = end;
    assert.throws(() => encode_manifest(input, text), IntegrityViolation);
  }
});

test('digest and UUID syntax rejects final line terminators', () => {
  for (const suffix of ['\n', '\r', '\u2028', '\u2029']) {
    const source = record();
    source.source_sha256 += suffix;
    assert.throws(() => encode_manifest(source, text), InvalidRequest);
    const excerpt = record();
    excerpt.members[0].text_sha256 += suffix;
    assert.throws(() => encode_manifest(excerpt, text), InvalidRequest);
    const manifest = record();
    manifest.members[0].dense_input_sha256 += suffix;
    assert.throws(() => encode_manifest(manifest, text), InvalidRequest);
    const sparse = record();
    sparse.members[0].sparse_input_sha256 += suffix;
    assert.throws(() => encode_manifest(sparse, text), InvalidRequest);
    const intent = stage();
    intent.manifest_sha256 += suffix;
    assert.throws(() => encode_stage_intent(intent), InvalidRequest);
    const purge = {intent_id: 'purge-2', tenant_id: 'tenant-a', collection: 'docs', document_id: 'doc-1',
      tombstone_intent_payload_sha256: 'a'.repeat(64) + suffix,
      expected_authorization_revision: 'auth-2', expected_mutation_epoch: 2};
    assert.throws(() => encode_purge_intent(purge), InvalidRequest);
    const uuid = record();
    uuid.members[0].point_id += suffix;
    assert.throws(() => encode_manifest(uuid, text), InvalidRequest);
  }
});

test('replay byte admission enforces kind-specific caps before reading array slots', () => {
  const dense = encode_dense_replay(unit(), denseProfile);
  const sparse = encode_sparse_replay([1], [1], sparseProfile);
  let calls = 0;
  for (const [length, restore, replay, profile] of [
    [12327, restore_dense_replay, dense, denseProfile],
    [232, restore_sparse_replay, sparse, sparseProfile],
  ]) {
    const blob = Array(length).fill(0);
    Object.defineProperty(blob, '0', {get() { calls++; throw Error('must not evaluate'); }});
    assert.throws(() => restore(blob, replay.blob_sha256, replay.input_sha256, profile), IntegrityViolation);
  }
  assert.equal(calls, 0);
});
