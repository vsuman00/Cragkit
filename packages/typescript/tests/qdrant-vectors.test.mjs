import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {encode_dense,encode_sparse,verify_dense_readback,verify_sparse_readback} from '../dist/qdrant-vectors.js';
import {InvalidRequest,EmbeddingProfileMismatch,IntegrityViolation} from '../dist/errors.js';
import {OPENAI_PROFILE} from '../dist/embeddings.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const denseProfile=fixture.profiles.dense;
const sparseProfile=fixture.profiles.sparse;
function expand(spec){
  const values=Array(spec.dimensions).fill(0);
  if(spec.encoding==='basis_float32')values[spec.basis_index]=spec.value;
  for(const [index,value] of spec.nonzero??[])values[index]=value;
  if(spec.negative_zero_index!==undefined)values[spec.negative_zero_index]=-0;
  return values;
}
function unit(){return expand({dimensions:1536,nonzero:[[0,1]]});}
function normalized(values){
  let sum=0;
  for(let i=0;i<values.length;i++)sum+=values[i]*values[i];
  const norm=Math.sqrt(sum);
  return values.map(value=>value/norm);
}

for(const row of fixture.numeric_cases){
  test(`QW numeric fixture: ${row.id}`,()=>{
    const input=expand(row.input_encoding);
    const run=()=>{
      const encoded=encode_dense(input,denseProfile);
      for(const expected of row.expected_float32_bits_le??[]){
        const bytes=Buffer.alloc(4);
        bytes.writeFloatLE(encoded.values[expected.index]);
        assert.equal(bytes.toString('hex'),expected.hex);
      }
      const observed=row.readback_encoding?expand(row.readback_encoding):normalized(encoded.values);
      verify_dense_readback(encoded,observed);
    };
    if(row.expected_error)assert.throws(run,{name:row.expected_error});
    else assert.doesNotThrow(run);
  });
}

test('four golden seals bind named vectors and complete profiles',()=>{
  for(const member of fixture.members){
    const dense=encode_dense(expand(member.dense),denseProfile);
    const sparse=encode_sparse(member.sparse.indices,member.sparse.values,sparseProfile);
    assert.equal(dense.input_sha256,member.dense.vector_sha256);
    assert.equal(sparse.input_sha256,member.sparse.vector_sha256);
    for(const encoded of [dense,sparse]){
      assert.equal(createHash('sha256').update(Buffer.from(encoded.sealed_bytes)).digest('hex'),encoded.input_sha256);
      assert.ok(Object.isFrozen(encoded));
      assert.ok(Object.isFrozen(encoded.values));
      assert.ok(Object.isFrozen(encoded.profile));
      assert.ok(Object.isFrozen(encoded.sealed_bytes));
    }
    verify_sparse_readback(sparse,member.sparse.indices,member.sparse.values);
  }
});

test('snapshots remain immutable after caller mutation',()=>{
  const vector=unit(),profile={...denseProfile},indices=[2,7],values=[1,.5];
  const dense=encode_dense(vector,profile),sparse=encode_sparse(indices,values,{...sparseProfile});
  vector[0]=0;profile.model='changed';indices[0]=4;values[0]=9;
  assert.equal(dense.values[0],1);
  assert.equal(dense.profile.model,denseProfile.model);
  assert.deepEqual(sparse.indices,[2,7]);
  assert.deepEqual(sparse.values,[1,.5]);
  for(const mutate of [()=>{dense.values[0]=9;},()=>{dense.profile.model='changed';},()=>{dense.sealed_bytes[0]=0;},()=>{sparse.indices[0]=9;}])assert.throws(mutate,TypeError);
});

test('native container guards reject accessors and proxies without evaluating traps',()=>{
  let calls=0;
  const accessor=unit();Object.defineProperty(accessor,'0',{get(){calls++;return 1;}});
  const proxy=new Proxy(unit(),{get(){calls++;throw Error('private');},ownKeys(){calls++;throw Error('private');}});
  const profileAccessor={...denseProfile};Object.defineProperty(profileAccessor,'model',{get(){calls++;return 'private';}});
  for(const [vector,profile] of [[accessor,denseProfile],[proxy,denseProfile],[unit(),profileAccessor],[unit(),new Proxy(denseProfile,{ownKeys(){calls++;return [];}})]])assert.throws(()=>encode_dense(vector,profile),InvalidRequest);
  assert.equal(calls,0);
});

test('dense malformed values, shapes and containers fail admission',()=>{
  const hole=unit();delete hole[1];
  const extra=unit();extra.extra=1;
  class Custom extends Array{}
  for(const vector of [null,{},'vector',new Float32Array(unit()),new Custom(...unit()),hole,extra,Array(100000).fill(0),[1],Array(1536).fill(0),unit().map((v,i)=>i===1?true:v),unit().map((v,i)=>i===1?'0':v),unit().map((v,i)=>i===1?NaN:v),unit().map((v,i)=>i===1?Infinity:v)])assert.throws(()=>encode_dense(vector,denseProfile),InvalidRequest);
});

test('full profiles are strictly shaped and checked before sealing',()=>{
  for(const profile of [null,{}, {...denseProfile,extra:'x'},{...denseProfile,model:true},{...denseProfile,model:'x'.repeat(1025)}])assert.throws(()=>encode_dense(unit(),profile),InvalidRequest);
  for(const profile of [{...denseProfile,model:'another-model'},{...denseProfile,dimensions:2}])assert.throws(()=>encode_dense(unit(),profile),EmbeddingProfileMismatch);
  assert.doesNotThrow(()=>encode_dense(unit(),OPENAI_PROFILE));
  assert.notEqual(encode_dense(unit(),OPENAI_PROFILE).input_sha256,encode_dense(unit(),denseProfile).input_sha256);
  assert.throws(()=>encode_sparse([1],[1],{...sparseProfile,revision:'2'}),EmbeddingProfileMismatch);
});

test('float32 conversion preserves ties, subnormals and canonical zero',()=>{
  const vector=unit();vector[1]=-0;vector[2]=2**-149;
  const encoded=encode_dense(vector,denseProfile);
  assert.equal(Object.is(encoded.values[1],-0),false);
  assert.equal(encoded.values[2],2**-149);
  const tiny=unit();tiny[1]=2**-151;
  assert.throws(()=>encode_dense(tiny,denseProfile),InvalidRequest);
  assert.throws(()=>encode_sparse([1],[2**-151],sparseProfile),InvalidRequest);
  assert.throws(()=>encode_sparse([1],[1e39],sparseProfile),InvalidRequest);
  const original=unit();original[0]=1.00099999;
  const rounded=encode_dense(original,denseProfile);
  assert.ok(Math.abs(rounded.values[0]-1)>0.001,'do not recheck E-r1 norm after rounding');
});

test('nearest float32 boundary respects fixed dense guard',()=>{
  const expected=encode_dense(unit(),denseProfile);
  const inside=unit();inside[0]=1.0001999139785767;
  const outside=unit();outside[0]=1.0002000331878662;
  assert.doesNotThrow(()=>verify_dense_readback(expected,inside));
  assert.throws(()=>verify_dense_readback(expected,outside),IntegrityViolation);
});

test('readback rejects malformed and forged expected objects safely',()=>{
  const dense=encode_dense(unit(),denseProfile),sparse=encode_sparse([1],[1],sparseProfile);
  for(const observed of [null,{},[1],new Float32Array(unit()),unit().map((v,i)=>i===1?NaN:v),unit().map((v,i)=>i===1?1e-50:v)])assert.throws(()=>verify_dense_readback(dense,observed),IntegrityViolation);
  for(const expected of [{...dense},JSON.parse(JSON.stringify(dense)),sparse,null])assert.throws(()=>verify_dense_readback(expected,unit()),IntegrityViolation);
  assert.throws(()=>verify_sparse_readback({...sparse},[1],[1]),IntegrityViolation);
});

test('sparse mapping is exact, bounded and positive',()=>{
  for(const [indices,values] of [[[],[]],[[1,1],[1,2]],[[2,1],[1,2]],[[-1],[1]],[[2**32],[1]],[[true],[1]],[[1.5],[1]],[[1],[0]],[[1],[-1]],[[1],[true]],[[1],['1']],[[1],[NaN]],[[1,2],[1]],[Array.from({length:17},(_,i)=>i),Array(17).fill(1)]])assert.throws(()=>encode_sparse(indices,values,sparseProfile),InvalidRequest);
  const expected=encode_sparse([0,4294967295],[2**-149,1],sparseProfile);
  verify_sparse_readback(expected,[0,4294967295],[2**-149,1]);
  for(const [indices,values] of [[[1,4294967295],[2**-149,1]],[[0,4294967295],[2**-149,1.0000001192092896]],[[0],[2**-149]],[[0,4294967295],[0,1]]])assert.throws(()=>verify_sparse_readback(expected,indices,values),IntegrityViolation);
});

test('sparse negative-zero index has canonical positive-zero identity', () => {
  const negativeZero = encode_sparse([-0], [1], sparseProfile);
  const positiveZero = encode_sparse([0], [1], sparseProfile);
  assert.equal(Object.is(negativeZero.indices[0], -0), false);
  assert.equal(negativeZero.input_sha256, positiveZero.input_sha256);
  assert.deepEqual(negativeZero.sealed_bytes, positiveZero.sealed_bytes);
  verify_sparse_readback(negativeZero, [-0], [1]);
});

test('readback preserves operational failures rather than reporting corrupt data', () => {
  const dense = encode_dense(unit(), denseProfile);
  const sparse = encode_sparse([1], [1], sparseProfile);
  const originalFround = Math.fround;
  const failure = new RangeError('synthetic operational failure');
  try {
    Math.fround = () => { throw failure; };
    assert.throws(() => verify_dense_readback(dense, unit()), error => error === failure);
    assert.throws(() => verify_sparse_readback(sparse, [1], [1]), error => error === failure);
  } finally {
    Math.fround = originalFround;
  }
});
