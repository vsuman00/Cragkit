import test from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { EventSink,new_trace } from '../dist/events.js';
import { InvalidRequest } from '../dist/errors.js';
const trace='12345678-1234-4234-8234-123456789abc';
const fields=(extra={})=>({trace_id:trace,attempt:0,elapsed_ms:0,...extra});
const deadline=()=>performance.now()/1000+1;

test('emit is synchronous, bounded and never calls exporter; ordinal includes overflow',()=>{
  let calls=0;const sink=new EventSink({capacity:1,exporter:async()=>{calls++;}});
  assert.equal(sink.emit('start',fields()),true);assert.equal(calls,0);
  assert.equal(sink.emit('search',fields({attempt:1})),false);
  const first=sink.drain();assert.equal(first[0].event_id,trace+':1');assert.ok(Object.isFrozen(first[0]));
  assert.equal(sink.emit('stop',fields({stop_reason:'no_plan'})),true);
  assert.equal(sink.drain()[0].event_id,trace+':3');
  assert.deepEqual(sink.snapshot(),{queued:0,dropped:3,exported:0});
});

test('fixed fields reject raw source, query, DSN and secret injection',()=>{
  const sink=new EventSink();
  for(const value of [fields({query:'private query'}),fields({source:'private source'}),fields({dsn:'postgres://secret'}),
    fields({stop_reason:'api-key-private'}),fields({trace_id:'request-source-id'}),fields({attempt:true}),
    fields({candidate_count:Infinity}),fields({elapsed_ms:300001}),Object.defineProperty(fields(),'secret',{enumerable:true,get(){throw new Error('do not invoke');}})])
    assert.throws(()=>sink.emit('search',value),InvalidRequest);
  for(const [stage,reason]of [['error','private provider message'],['stop','provider_unavailable'],['cancelled',null],['start','sufficient']])
    assert.throws(()=>sink.emit(stage,fields({stop_reason:reason})),InvalidRequest);
  assert.deepEqual(sink.snapshot(),{queued:0,dropped:0,exported:0});
  assert.equal(sink.emit('error',fields({stop_reason:'provider_unavailable'})),true);
  assert.equal(sink.emit('cancelled',fields({stop_reason:'cancelled'})),true);
});

test('traces are fresh UUIDs and snapshots and drains are detached',()=>{
  const a=new_trace(),b=new_trace();assert.notEqual(a,b);assert.match(a,/^[0-9a-f-]{36}$/);
  const sink=new EventSink(),input=fields();sink.emit('start',input);input.trace_id=b;
  const snapshot=sink.snapshot(),events=sink.drain();assert.ok(Object.isFrozen(snapshot));assert.ok(Object.isFrozen(events));
  assert.equal(snapshot.queued,1);assert.equal(sink.snapshot().queued,0);assert.equal(events[0].trace_id,trace);
});

test('explicit flush counts only completed deliveries and catches exporter faults',async()=>{
  const delivered=[];const sink=new EventSink({exporter:async(event,options)=>{
    assert.ok(Object.isFrozen(event));assert.ok(options.signal instanceof AbortSignal);assert.ok(options.deadline<=deadline());
    delivered.push(event.event_id);if(event.stage==='search')throw new Error('private exporter fault');
  }});
  sink.emit('start',fields());sink.emit('search',fields());sink.emit('stop',fields({stop_reason:'no_plan'}));
  assert.deepEqual(await sink.flush({deadline:deadline()}),{queued:0,dropped:1,exported:2});assert.equal(delivered.length,3);
});

test('flush processes at most its starting queue size while newly emitted events remain queued',async()=>{
  let sink;const seen=[];
  sink=new EventSink({exporter:async event=>{seen.push(event);sink.emit('search',fields());}});
  sink.emit('start',fields());await sink.flush({deadline:deadline()});
  assert.equal(seen.length,1);assert.deepEqual(sink.snapshot(),{queued:1,dropped:0,exported:1});
});

test('hanging exporter is timed out and no second delivery starts while it remains unsettled',async()=>{
  let calls=0,release;const gate=new Promise(resolve=>{release=resolve;});
  const sink=new EventSink({timeout_ms:5,exporter:async()=>{calls++;await gate;}});
  sink.emit('start',fields());sink.emit('search',fields());
  assert.deepEqual(await sink.flush({deadline:deadline()}),{queued:0,dropped:2,exported:0});assert.equal(calls,1);
  sink.emit('search',fields());await sink.flush({deadline:deadline()});assert.equal(calls,1);assert.equal(sink.snapshot().dropped,3);
  release();await gate;await new Promise(resolve=>setImmediate(resolve));
  assert.equal(sink.snapshot().exported,0);
  sink.emit('stop',fields({stop_reason:'no_plan'}));await sink.flush({deadline:deadline()});assert.equal(calls,2);assert.equal(sink.snapshot().exported,1);
});

test('concurrent flushes never run two exporter calls',async()=>{
  let calls=0,release;const gate=new Promise(resolve=>{release=resolve;});
  const sink=new EventSink({timeout_ms:100,exporter:async()=>{calls++;await gate;}});sink.emit('start',fields());
  const first=sink.flush({deadline:deadline()});await Promise.resolve();
  const second=await sink.flush({deadline:deadline()});assert.equal(second.exported,0);assert.equal(calls,1);
  release();await first;assert.equal(sink.snapshot().exported,1);
});

test('expired deadline and absent exporter drop events without dispatch',async()=>{
  let calls=0;const sink=new EventSink({exporter:async()=>{calls++;}});sink.emit('start',fields());
  assert.deepEqual(await sink.flush({deadline:-1}),{queued:0,dropped:1,exported:0});assert.equal(calls,0);
  const absent=new EventSink();absent.emit('start',fields());await absent.flush({deadline:deadline()});assert.equal(absent.snapshot().dropped,1);
});

test('caller cancellation is native, drops remaining events and observes late exporter rejection',async()=>{
  const controller=new AbortController();let rejectLate,child;
  const sink=new EventSink({timeout_ms:100,exporter:async(_event,{signal})=>{child=signal;controller.abort();await new Promise((_,reject)=>{rejectLate=reject;});}});
  sink.emit('start',fields());sink.emit('search',fields());
  await assert.rejects(sink.flush({deadline:deadline(),signal:controller.signal}),{name:'AbortError'});
  assert.ok(child.aborted);assert.deepEqual(sink.snapshot(),{queued:0,dropped:2,exported:0});
  rejectLate(new Error('late private failure'));await new Promise(resolve=>setImmediate(resolve));assert.equal(sink.snapshot().exported,0);
});

test('close is idempotent, aborts active export and rejects future emits',async()=>{
  let child;const sink=new EventSink({exporter:async(_event,{signal})=>{child=signal;sink.close();return new Promise(()=>{});}});
  sink.emit('start',fields());sink.emit('search',fields());await sink.flush({deadline:deadline()});sink.close();
  assert.ok(child.aborted);assert.deepEqual(sink.snapshot(),{queued:0,dropped:2,exported:0});
  assert.throws(()=>sink.emit('start',fields()),InvalidRequest);
});
