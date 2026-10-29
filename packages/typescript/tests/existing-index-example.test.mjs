import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {ExistingIndexAdapter,demo_data} from '../../../examples/existing_index.mjs';
import {parse_result} from '../dist/contracts.js';
import {IntegrityViolation,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability} from '../dist/errors.js';

const hash=value=>createHash('sha256').update(value).digest('hex');
const retrieve=(adapter,query='retries')=>adapter.retrieve(query,{deadline:performance.now()/1000+5});

test('maps exact multibyte sources into the native result without claiming coverage',async()=>{
  const {records,source,scope}=demo_data(),calls=[];
  const adapter=new ExistingIndexAdapter(records,(...key)=>{calls.push(key);return structuredClone(source);},
    {scope,collection:'docs',required_filters:[{op:'eq',field:'tag',value:'public'}]});
  const result=await retrieve(adapter);assert.deepEqual(parse_result(result),result);
  assert.equal(result.status,'partial');assert.equal(result.execution,'complete');
  const item=result.evidence[0],raw=Buffer.from(source.text);
  assert.equal(item.text,'Café retries: at most three.');
  assert.equal(raw.subarray(item.start_byte,item.end_byte).toString('utf8'),item.text);
  assert.equal(item.source_sha256,hash(raw));assert.equal(item.text_sha256,hash(item.text));
  assert.deepEqual(calls,[['tenant-a','docs','retry','r1'],['tenant-a','docs','retry','r1']]);
  assert.equal(result.usage.provider_calls,0);assert.equal(result.usage.context_counting,'estimated');
  assert.equal(result.facets[0].state,'unknown');assert.equal(result.limitations[0].code,'coverage_unknown');
});

test('foreign records never reach source resolution even when the query names their tenant',async()=>{
  const {records,scope}=demo_data();records[0].tenant_id='tenant-b';records[0].search_text+=' tenant-b';
  const adapter=new ExistingIndexAdapter(records,()=>assert.fail('foreign source resolved'),{scope,collection:'docs'});
  const result=await retrieve(adapter,'tenant-b retries');assert.equal(result.status,'insufficient');assert.deepEqual(result.evidence,[]);
});

test('fresh source authorization and required filters are rechecked before release',async()=>{
  for(const change of [{tenant_id:'tenant-b'},{tag:'private'},{principal_ids:[],grant_ids:[]}]){
    const {records,source,scope}=demo_data();Object.assign(source,change);
    const adapter=new ExistingIndexAdapter(records,()=>source,{scope,collection:'docs',required_filters:[{op:'eq',field:'tag',value:'public'}]});
    await assert.rejects(()=>retrieve(adapter),UnauthorizedScope);
  }
});

test('packing cannot release a source revoked before the result returns',async()=>{
  const {records,source,scope}=demo_data();let calls=0;
  const adapter=new ExistingIndexAdapter(records,()=>++calls===1?structuredClone(source):({...source,principal_ids:[],grant_ids:[]}),{scope,collection:'docs'});
  await assert.rejects(()=>retrieve(adapter),UnauthorizedScope);assert.equal(calls,2);
});

test('missing immutable provenance fails before calling the source resolver',async()=>{
  for(const missing of ['revision_id','source_sha256','text_sha256']){
    const {records,scope}=demo_data();delete records[0][missing];
    const adapter=new ExistingIndexAdapter(records,()=>assert.fail('malformed provenance resolved'),{scope,collection:'docs'});
    await assert.rejects(()=>retrieve(adapter),IntegrityViolation);
  }
});

test('unsupported capabilities and missing source resolution cannot become empty success',async()=>{
  const {records,source,scope}=demo_data();
  for(const extra of [{mode:'dense'},{required_filters:[{op:'ne',field:'tag',value:'private'}]}]){
    assert.throws(()=>new ExistingIndexAdapter(records,()=>source,{scope,collection:'docs',...extra}),UnsupportedCapability);
  }
  assert.throws(()=>new ExistingIndexAdapter(records,null,{scope,collection:'docs'}),UnsupportedCapability);
  await assert.rejects(()=>retrieve(new ExistingIndexAdapter(records,()=>null,{scope,collection:'docs'})),ProviderUnavailable);
  await assert.rejects(()=>retrieve(new ExistingIndexAdapter(records,()=>{throw new Error('PRIVATE source failure');},{scope,collection:'docs'})),
    error=>error instanceof ProviderUnavailable&&!error.message.includes('PRIVATE'));
});

test('changed source digest or split UTF-8 span fails without evidence release',async()=>{
  const {records,source,scope}=demo_data();
  await assert.rejects(()=>retrieve(new ExistingIndexAdapter(records,()=>({...source,text:'changed canonical bytes'}),{scope,collection:'docs'})),IntegrityViolation);
  records[0].end_byte=4;records[0].text_sha256=hash(Buffer.from(source.text).subarray(0,4));
  await assert.rejects(()=>retrieve(new ExistingIndexAdapter(records,()=>source,{scope,collection:'docs'})),IntegrityViolation);
});

test('caller mutation cannot alter snapshotted scope, filters or index records',async()=>{
  const {records,source,scope}=demo_data(),filters=[{op:'eq',field:'tag',value:'public'}];
  const adapter=new ExistingIndexAdapter(records,()=>source,{scope,collection:'docs',required_filters:filters});
  records[0].tenant_id='tenant-b';filters[0].value='private';scope.tenant_id='tenant-b';
  assert.equal((await retrieve(adapter)).evidence[0].document_id,'retry');
});
