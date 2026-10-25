import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { CorrectiveRetriever } from '../dist/corrective.js';
import { EventSink } from '../dist/events.js';
import { PlannerAdapter } from '../dist/planning.js';
import { ProviderUnavailable,InvalidRequest } from '../dist/errors.js';
const query='Private API-42 query';
const request=()=>({request_id:'private-request',query,collection:'private-collection',output_profile:{renderer:'cragkit.context.v2'}});
const options=extra=>({scope:{tenant_id:'private-tenant',principal_id:'private-reader',authorization_revision:'acl'},deadline:performance.now()/1000+1,...extra});
const backend=()=>({async search(){return {candidates:[],degraded:false};},async capture(){return {evidence:[],sources:[],source_bytes:0,stale:false,budget_exhausted:false};}});
const policy={policy_id:'trusted',version:'1',query_sha256:createHash('sha256').update(query).digest('hex'),facets:[{facet_id:'missing',question:'Required answer?',required:true,absence:'missing',anchors:[]}]};

test('retrieval queues fixed events without invoking the exporter or leaking raw inputs',async()=>{
  let exports=0;const sink=new EventSink({exporter:async()=>{exports++;return new Promise(()=>{});}});
  const result=await new CorrectiveRetriever({backend:backend(),event_sink:sink}).retrieve(request(),options());
  assert.equal(exports,0);assert.deepEqual(result.diagnostics.events,{trace_id:result.diagnostics.events.trace_id,queued:4,dropped:0,exported:0});
  const events=sink.drain();assert.deepEqual(events.map(e=>e.stage),['start','search','capture','stop']);
  assert.equal(events.at(-1).stop_reason,'coverage_unknown');assert.equal(events[1].attempt,1);assert.equal(events[1].candidate_count,16);
  const serialized=JSON.stringify(events);for(const secret of ['Private','API-42','private-request','private-tenant','private-reader','private-collection'])assert.ok(!serialized.includes(secret));
  assert.ok(events.every(e=>e.trace_id===result.diagnostics.events.trace_id));
});

test('default diagnostics are unchanged and optional sink overflow or closure cannot alter retrieval',async()=>{
  const plain=await new CorrectiveRetriever({backend:backend()}).retrieve(request(),options());assert.ok(!Object.hasOwn(plain.diagnostics,'events'));
  const full=new EventSink({capacity:1});const r=await new CorrectiveRetriever({backend:backend(),event_sink:full}).retrieve(request(),options());
  assert.equal(r.result.status,plain.result.status);assert.equal(r.diagnostics.events.queued,1);assert.equal(r.diagnostics.events.dropped,3);
  const closed=new EventSink();closed.close();const done=await new CorrectiveRetriever({backend:backend(),event_sink:closed}).retrieve(request(),options());
  assert.equal(done.result.status,plain.result.status);assert.equal(done.diagnostics.events.queued,0);
  class Subclass extends EventSink{}
  assert.throws(()=>new CorrectiveRetriever({backend:backend(),event_sink:new Subclass()}),InvalidRequest);
});

test('planning and retry stage ordering uses request-local ledger counts',async()=>{
  const sink=new EventSink(),b=backend();let calls=0;
  b.search=async()=>{if(++calls===1)throw new ProviderUnavailable();return {candidates:[],degraded:false};};
  const adapter=new PlannerAdapter({transport:async()=>({plan:{queries:[]},usage:{input_tokens:0,output_tokens:0,cost_usd:0}})});
  const result=await new CorrectiveRetriever({backend:b,policy,variants:[{facet_id:'missing',variant_id:'v',query:'API-42 approved'}],planner:adapter,max_retries:1,event_sink:sink}).retrieve(request(),options());
  const events=sink.drain();assert.deepEqual(events.map(e=>e.stage),['start','search','retry','search','capture','planning','capture','stop']);
  assert.equal(events[2].attempt,1);assert.equal(events[3].attempt,2);assert.equal(events[6].provider_calls,1);
  assert.equal(result.diagnostics.events.queued,8);assert.equal(result.diagnostics.stop_reason,'no_plan');
});

test('typed and arbitrary failures emit fixed codes while native cancellation emits cancelled',async()=>{
  for(const error of [new ProviderUnavailable(),new Error('private credential-bearing provider details')]){
    const sink=new EventSink(),b=backend();b.search=async()=>{throw error;};
    await assert.rejects(new CorrectiveRetriever({backend:b,event_sink:sink}).retrieve(request(),options()),e=>e===error);
    const events=sink.drain();assert.deepEqual(events.map(e=>e.stage),['start','search','error']);
    assert.equal(events.at(-1).stop_reason,'provider_unavailable');assert.ok(!JSON.stringify(events).includes('private credential'));
  }
  const sink=new EventSink(),controller=new AbortController(),b=backend();
  b.search=async()=>{controller.abort();return new Promise(()=>{});};
  await assert.rejects(new CorrectiveRetriever({backend:b,event_sink:sink}).retrieve(request(),options({signal:controller.signal})),{name:'AbortError'});
  assert.deepEqual(sink.drain().map(e=>e.stage),['start','search','cancelled']);
});

test('concurrent requests sharing a sink receive separate traces without request text',async()=>{
  const sink=new EventSink(),retriever=new CorrectiveRetriever({backend:backend(),event_sink:sink});
  const [a,b]=await Promise.all([retriever.retrieve(request(),options()),retriever.retrieve({...request(),request_id:'second-private-request'},options())]);
  assert.notEqual(a.diagnostics.events.trace_id,b.diagnostics.events.trace_id);
  const events=sink.drain();for(const result of [a,b])assert.deepEqual(events.filter(e=>e.trace_id===result.diagnostics.events.trace_id).map(e=>e.stage),['start','search','capture','stop']);
  assert.equal(new Set(events.map(e=>e.event_id)).size,8);assert.ok(!JSON.stringify(events).includes('private-request'));
});
