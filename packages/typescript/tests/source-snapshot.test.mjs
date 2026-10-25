import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {verify_source,source_snapshot} from '../dist/postgres-source.js';
import {IntegrityViolation,InvalidRequest,UnsupportedCapability} from '../dist/errors.js';
const sha=text=>createHash('sha256').update(text).digest('hex');
function data(){const text='Café🙂',canonical=text+' parent marker';return{
  candidate:{tenant_id:'t',collection:'c',document_id:'d',revision_id:'r',generation_id:'g',chunk_id:'chunk',start_byte:0,end_byte:Buffer.byteLength(text),text_sha256:sha(text),score:1},
  row:['t','c','d','r','g','chunk',sha(canonical),Buffer.byteLength(canonical),canonical,0,Buffer.byteLength(text),Buffer.byteLength(text),text,sha(text),'fixture','native_fts.v1',true],canonical};}
test('source capture is opt-in, verified and absent from serialized fetch shape',()=>{
  const {candidate,row,canonical}=data();
  const standard=verify_source(candidate,[row],100);
  assert.throws(()=>source_snapshot(standard),UnsupportedCapability);
  const full=verify_source(candidate,[row],100,true);
  assert.equal(source_snapshot(full).text,canonical);
  assert.deepEqual(full,standard);
  assert.equal(JSON.stringify(full).includes('parent marker'),false);
  assert.throws(()=>source_snapshot({...full}),UnsupportedCapability);
});
test('integrity, budget and option failures cannot expose unchecked sources',()=>{
  const {candidate,row}=data();
  const corrupt=[...row];corrupt[8]='modified';
  assert.throws(()=>verify_source(candidate,[corrupt],100,true),IntegrityViolation);
  const unloaded=[...row];unloaded[8]=null;
  assert.throws(()=>source_snapshot(verify_source(candidate,[unloaded],0,true)),UnsupportedCapability);
  assert.throws(()=>verify_source(candidate,[],100,1),InvalidRequest);
});
