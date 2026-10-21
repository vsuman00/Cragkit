import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { canonicalize } from '../dist/canonical.js';
import { InvalidRequest, UnsupportedCapability } from '../dist/errors.js';
const sha = value => createHash('sha256').update(value).digest('hex');
function exact(document) {
  const canonical = Buffer.from(document.canonical_text);
  let offset = 0;
  assert.ok(Object.isFrozen(document) && Object.isFrozen(document.chunks));
  for (const [ordinal, chunk] of document.chunks.entries()) {
    assert.ok(Object.isFrozen(chunk));assert.equal(chunk.ordinal, ordinal);assert.equal(chunk.start_byte, offset);
    assert.ok(chunk.end_byte > chunk.start_byte);
    assert.equal(canonical.subarray(chunk.start_byte,chunk.end_byte).toString('utf8'),chunk.text);
    assert.equal(chunk.text_sha256,sha(Buffer.from(chunk.text)));
    assert.equal(chunk.chunk_id,sha(`${document.canonical_sha256}:${chunk.start_byte}:${chunk.end_byte}:${document.chunker_profile}`));
    offset = chunk.end_byte;
  }
  assert.equal(offset,canonical.length);assert.equal(document.chunks.map(chunk=>chunk.text).join(''),document.canonical_text);
  assert.equal(document.canonical_sha256,sha(canonical));
}
test('source bytes and canonical bytes have distinct exact digests',()=>{
  const raw=Buffer.from('\uFEFFCafé\r\n🙂\rpreserved\u2028separator\u0301');const result=canonicalize(raw);
  assert.equal(result.source_sha256,sha(raw));assert.equal(result.canonical_text,'Café\n🙂\npreserved\u2028separator\u0301');
  assert.notEqual(result.source_sha256,result.canonical_sha256);assert.equal(result.parser_id,'cragkit.text.v1');exact(result);
});
test('normalization removes exactly one leading BOM and does not normalize Unicode',()=>{
  const result=canonicalize('\uFEFF\uFEFFe\u0301\uFEFF');assert.equal(result.canonical_text,'\uFEFFe\u0301\uFEFF');exact(result);
});
test('byte inputs are detached snapshots',()=>{
  const bytes=Buffer.from('immutable🙂');const result=canonicalize(bytes);bytes.fill(0);assert.equal(result.canonical_text,'immutable🙂');exact(result);
});
for(const input of ['', ' \t\r\n\f\v', '\uFEFF', '\0content', '\uD800', '\uDC00', Buffer.from([0xc0,0xaf]),Buffer.from([0xed,0xa0,0x80]),Buffer.from([0xf0,0x9f])])test(`reject malformed or empty input ${String(input).length}`,()=>assert.throws(()=>canonicalize(input),InvalidRequest));
test('non-ASCII whitespace is preserved rather than silently trimmed',()=>{
  const result=canonicalize('\u0085\u00A0\u2028');assert.equal(result.canonical_text,'\u0085\u00A0\u2028');exact(result);
});
test('unsupported formats are explicit without parser fallback',()=>{
  for(const format of ['application/pdf','text/html','TEXT/PLAIN','text/plain; charset=utf-8'])assert.throws(()=>canonicalize('synthetic',{format}),InvalidRequest);
});
for(const options of [{max_source_bytes:0},{max_source_bytes:16_777_217},{max_source_bytes:true},{target_bytes:0},{target_bytes:5,max_chunk_bytes:4},{max_chunk_bytes:3},{max_chunk_bytes:32769},{target_bytes:1.5},{unknown:true}])test(`invalid limits ${JSON.stringify(options)}`,()=>assert.throws(()=>canonicalize('source',options),InvalidRequest));
test('source size is measured in original UTF8 bytes including BOM and CRLF',()=>{
  assert.throws(()=>canonicalize('🙂',{max_source_bytes:3}),InvalidRequest);
  assert.equal(canonicalize('🙂',{max_source_bytes:4}).canonical_text,'🙂');
  assert.throws(()=>canonicalize('\uFEFFa\r\n',{max_source_bytes:5}),InvalidRequest);
});
test('paragraphs retain trailing blank lines and preserve leading blank lines',()=>{
  const text='\n\nfirst\n\nsecond\n';const result=canonicalize(text,{target_bytes:8,max_chunk_bytes:32});
  assert.deepEqual(result.chunks.map(chunk=>chunk.text),['\n\n','first\n\n','second\n']);assert.ok(result.chunks.every(chunk=>!chunk.oversized_split));exact(result);
});
test('Markdown heading and fenced code boundaries are structural',()=>{
  const text='# Heading\n\nparagraph\n\n```js\na\n\nb\n```\n\nlast';const result=canonicalize(text,{format:'text/markdown',target_bytes:4,max_chunk_bytes:64});
  assert.deepEqual(result.chunks.map(chunk=>chunk.text),['# Heading\n\n','paragraph\n\n','```js\na\n\nb\n```\n\n','last']);assert.ok(result.chunks.every(chunk=>!chunk.oversized_split));exact(result);
});
test('plain text does not interpret Markdown heading or fence markers',()=>{
  const result=canonicalize('# heading\n```\ncode\n```',{target_bytes:4,max_chunk_bytes:64});assert.equal(result.chunks.length,1);exact(result);
});
test('fence close must match character, length and trailing whitespace',()=>{
  const text='~~~~\na\n```\n~~~\n~~~~ trailing\n~~~~\nafter';const result=canonicalize(text,{format:'text/markdown',target_bytes:2,max_chunk_bytes:64});
  assert.deepEqual(result.chunks.map(chunk=>chunk.text),['~~~~\na\n```\n~~~\n~~~~ trailing\n~~~~\n','after']);exact(result);
});
test('unmatched Markdown fence includes all remaining lines',()=>{
  const result=canonicalize('```\none\n\ntwo',{format:'text/markdown',target_bytes:1,max_chunk_bytes:64});assert.equal(result.chunks.length,1);assert.equal(result.chunks[0].oversized_split,false);exact(result);
});
test('oversized structures split at scalar boundaries and soft targets',()=>{
  const result=canonicalize('a🙂ébc🙂',{target_bytes:5,max_chunk_bytes:8});assert.deepEqual(result.chunks.map(chunk=>chunk.text),['a🙂','ébc','🙂']);assert.ok(result.chunks.every(chunk=>chunk.oversized_split));exact(result);
});
test('one scalar may exceed soft target but never hard maximum',()=>{
  const result=canonicalize('🙂🙂🙂',{target_bytes:1,max_chunk_bytes:4});assert.deepEqual(result.chunks.map(chunk=>chunk.text),['🙂','🙂','🙂']);exact(result);
});
test('chunk count has a hard bound',()=>{
  assert.equal(canonicalize('a'.repeat(4096),{target_bytes:4,max_chunk_bytes:4}).chunks.length,1024);
  assert.throws(()=>canonicalize('a'.repeat(4100),{target_bytes:4,max_chunk_bytes:4}),InvalidRequest);
});
const tokenOptions = extra => ({token_counter:text=>[...text].length,tokenizer_id:'synthetic.scalar.v1',token_target:3,max_tokens:5,...extra});
test('token mode counts actual canonical document and every chunk',()=>{
  const result=canonicalize('abc🙂def',tokenOptions());assert.deepEqual(result.chunks.map(chunk=>chunk.text),['abc','🙂de','f']);
  assert.deepEqual(result.chunks.map(chunk=>chunk.token_count),[3,3,1]);assert.equal(result.token_count,7);assert.equal(result.tokenizer_id,'synthetic.scalar.v1');exact(result);
});
test('intact structure can exceed token target while fitting hard token cap',()=>{
  const result=canonicalize('abcd',tokenOptions());assert.equal(result.chunks.length,1);assert.equal(result.chunks[0].oversized_split,false);assert.equal(result.chunks[0].token_count,4);
});
test('all token declarations are required together',()=>{
  for(const key of ['token_counter','tokenizer_id','token_target','max_tokens']){const options=tokenOptions();delete options[key];assert.throws(()=>canonicalize('text',options),InvalidRequest);}
  for(const extra of [{tokenizer_id:'has spaces'},{tokenizer_id:'x'.repeat(65)},{token_target:0},{max_tokens:1_000_001},{token_target:6,max_tokens:5}])assert.throws(()=>canonicalize('text',tokenOptions(extra)),InvalidRequest);
});
for(const count of [NaN,Infinity,-1,1.5,true,Number.MAX_SAFE_INTEGER+1,Promise.resolve(1)])test(`invalid caller counter output ${String(count)}`,()=>assert.throws(()=>canonicalize('text',tokenOptions({token_counter:()=>count})),InvalidRequest));
test('counter exceptions and impossible scalar budgets fail without private details',()=>{
  for(const counter of [()=>{throw new Error('private-counter-input');},()=>{throw new UnsupportedCapability();},()=>6]) {
    assert.throws(()=>canonicalize('🙂',tokenOptions({token_counter:counter})),error=>error instanceof InvalidRequest&&error.cause===undefined&&!String(error).includes('private'));
  }
});
test('zero token counts are allowed and do not imply missing text',()=>{
  const result=canonicalize('text',tokenOptions({token_counter:()=>0}));assert.equal(result.token_count,0);assert.equal(result.chunks[0].token_count,0);exact(result);
});
test('counter calls are bounded without assuming monotonic counts',()=>{
  let calls=0;const options=tokenOptions({token_counter:()=>{calls++;return 100;},max_tokens:100,token_target:100,target_bytes:32768});
  assert.throws(()=>canonicalize('a'.repeat(70000),options),InvalidRequest);assert.equal(calls,65536);
});
test('parser options cannot execute getters or mutate output',()=>{
  let getter=false;const options={};Object.defineProperty(options,'format',{enumerable:true,get(){getter=true;return 'text/plain';}});
  assert.throws(()=>canonicalize('text',options),InvalidRequest);assert.equal(getter,false);
  const result=canonicalize('text');assert.throws(()=>{result.chunks[0].text='changed';},TypeError);exact(result);
});

const fixtures=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/canonical.json',import.meta.url),'utf8'));
for(const example of fixtures.cases)test(`shared canonical fixture: ${example.id}`,()=>{
  const source=example.source_hex===undefined?example.source:Buffer.from(example.source_hex,'hex');
  if(example.error)assert.throws(()=>canonicalize(source,example.options),error=>error.code===example.error);
  else {const result=canonicalize(source,example.options);assert.deepEqual(result,example.expected);exact(result);}
});
test('explicit null quartet means byte mode; scalar nulls are invalid',()=>{
  assert.equal(canonicalize('text',{token_counter:null,tokenizer_id:null,token_target:null,max_tokens:null}).tokenizer_id,null);
  for(const key of ['format','max_source_bytes','target_bytes','max_chunk_bytes'])assert.throws(()=>canonicalize('text',{[key]:null}),InvalidRequest);
});

test('byte-impossible merges preserve the shared token-counter work budget', () => {
  const calls = [];
  const document = canonicalize('a\n\nb\n\nc', { target_bytes: 1, max_chunk_bytes: 8,
    token_counter: text => { calls.push(text); return Array.from(text).length; },
    tokenizer_id: 'scalar.v1', token_target: 1, max_tokens: 8 });
  assert.equal(calls.length, 7);
  assert.equal(document.chunks.length, 3);
});

test('rejecting asynchronous counters cannot leave unhandled rejections', async () => {
  assert.throws(() => canonicalize('text', { token_counter: async () => { throw new Error('private counter detail'); },
    tokenizer_id: 'async.v1', token_target: 2, max_tokens: 4 }), InvalidRequest);
  await new Promise(resolve => setImmediate(resolve));
});
