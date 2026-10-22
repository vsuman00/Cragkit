import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture,stage,input,deferred} from './helpers/vector-fixture.mjs';
import {now} from '../dist/postgres-pool.js';
import {DeadlineExceeded,IndexNotReady,IntegrityViolation,InvalidRequest,UnauthorizedScope} from '../dist/errors.js';

const publish=(indexer,changes={},source='synthetic source')=>indexer.publish(source,input(changes));
const clean=async f=>{assert.equal(f.pool.leases,f.client.releases.length);await f.resource.close();};

test('VG-r1 success-replay publishes ready barrier pointer and job atomically without provider',async()=>{
  const f=fixture();const staged=await stage(f.indexer),result=await publish(f.indexer);
  assert.equal(result.generation_id,staged.generation_id);assert.equal(result.provider_calls,0);assert.deepEqual(result.usage,[]);
  assert.deepEqual(f.client.document,[[result.generation_id,false,'auth']]);assert.equal(f.client.generation[0][1],'ready');assert.equal(f.client.jobs[0][2],'succeeded');assert.equal(f.transport.calls.length,1);
  const sql=f.client.calls.map(([query])=>query);assert.ok(sql.findIndex(q=>q.startsWith('UPDATE cragkit.index_generations'))<sql.findIndex(q=>q.startsWith('UPDATE cragkit.documents')));
  const replay=await publish(f.indexer);assert.equal(replay.replayed,true);assert.equal(replay.provider_calls,0);assert.equal(f.client.published.length,1);await clean(f);
});
for(const kind of ['chunks','lexical','vectors','mixed-profile','mixed-generation','chunker','lexical-profile'])test(`publication rejects incomplete or mixed manifest ${kind}`,async()=>{
  const f=fixture();await stage(f.indexer);
  if(kind==='chunks')f.client.counts=[[0,1]];if(kind==='lexical')f.client.counts=[[1,0]];if(kind==='vectors')f.client.vectorCounts=[[0]];
  if(['mixed-profile','mixed-generation','chunker','lexical-profile'].includes(kind))f.client.generation[0][{'mixed-profile':3,'mixed-generation':0,chunker:4,'lexical-profile':5}[kind]]='wrong';
  await assert.rejects(publish(f.indexer),IntegrityViolation);assert.deepEqual(f.client.document,[[null,false,'auth']]);assert.deepEqual(f.client.published,[]);assert.equal(f.client.jobs[0][2],'running');assert.equal(f.transport.calls.length,1);await clean(f);
});
for(const [barrier,kind] of [['readyRows',IntegrityViolation],['casRows',IndexNotReady],['jobRows',IntegrityViolation]])test(`missing publication transition row ${barrier} rolls back all mutations`,async()=>{
  const f=fixture();await stage(f.indexer);f.client[barrier]=[];await assert.rejects(publish(f.indexer),kind);
  assert.deepEqual(f.client.document,[[null,false,'auth']]);assert.equal(f.client.generation[0][1],'staging');assert.equal(f.client.jobs[0][2],'running');assert.deepEqual(f.client.published,[]);assert.ok(f.client.rollbacks>=1);await clean(f);
});
test('VG-r1 hook-interruption preserves exception identity and staged generation',async()=>{
  const f=fixture();await stage(f.indexer);const sentinel=Error('caller hook failure');
  await assert.rejects(publish(f.indexer,{before_publish:async()=>{assert.equal(f.client.generation[0][1],'staging');assert.deepEqual(f.client.published,[]);throw sentinel;}}),error=>error===sentinel);
  assert.deepEqual(f.client.document,[[null,false,'auth']]);assert.equal(f.client.generation[0][1],'staging');await clean(f);
});
for(const change of ['grants','revision','tombstone'])test(`publication rechecks ${change} after caller hook`,async()=>{
  const f=fixture();await stage(f.indexer);await assert.rejects(publish(f.indexer,{before_publish:async()=>{
    if(change==='grants')f.client.grants=[[false]];else if(change==='revision')f.client.document=[[null,false,'revoked']];else f.client.document=[[null,true,'auth']];
  }}),UnauthorizedScope);assert.deepEqual(f.client.published,[]);assert.equal(f.client.generation[0][1],'staging');assert.equal(f.transport.calls.length,1);await clean(f);
});
test('VG-r1 stale-cas retains newer pointer instead of publishing older staged build',async()=>{
  const f=fixture();await stage(f.indexer);f.client.document=[['newer-ready-generation',false,'auth']];await assert.rejects(publish(f.indexer),IndexNotReady);
  assert.equal(f.client.document[0][0],'newer-ready-generation');assert.equal(f.client.generation[0][1],'staging');assert.deepEqual(f.client.published,[]);await clean(f);
});
test('publication recomputes full source metadata and expected-pointer identity',async()=>{
  const f=fixture();await stage(f.indexer);for(const [changes,source] of [[{},'other source'],[{metadata:{changed:true}},'synthetic source'],[{expected_generation_id:'forged-pointer'},'synthetic source']])await assert.rejects(publish(f.indexer,changes,source),InvalidRequest);
  assert.deepEqual(f.client.published,[]);assert.equal(f.transport.calls.length,1);await clean(f);
});
test('publication without staged intent creates no rows and makes no provider call',async()=>{
  const f=fixture();await assert.rejects(publish(f.indexer),IndexNotReady);assert.deepEqual(f.client.staged,[]);assert.deepEqual(f.client.published,[]);assert.equal(f.transport.calls.length,0);await clean(f);
});
for(const mode of ['abort','deadline'])test(`interrupted publication ${mode} releases admission and leaves staged build retryable`,async()=>{
  const f=fixture();await stage(f.indexer);const entered=deferred(),controller=new AbortController();
  const pending=publish(f.indexer,{signal:controller.signal,deadline:now()+(mode==='deadline'?0.03:2),before_publish:async()=>{entered.resolve();await new Promise(()=>{});}});
  await entered.promise;if(mode==='abort')controller.abort('private reason');await assert.rejects(pending,mode==='deadline'?DeadlineExceeded:error=>error.name==='AbortError'&&!String(error).includes('private'));
  assert.deepEqual(f.client.published,[]);assert.equal(f.client.generation[0][1],'staging');assert.deepEqual(f.client.document,[[null,false,'auth']]);
  assert.ok(f.client.releases.includes(true));
  await publish(f.indexer);assert.equal(f.client.generation[0][1],'ready');assert.equal(f.transport.calls.length,1);await clean(f);
});
test('ingest combines stage usage into its publication receipt with one admission guard',async()=>{
  const f=fixture();const result=await f.indexer.ingest('synthetic source',input());assert.equal(result.provider_calls,1);assert.equal(result.usage.length,1);assert.equal(result.usage[0].cost_usd,0);
  assert.equal(f.transport.calls.length,1);assert.equal(f.client.document[0][0],result.generation_id);await clean(f);
});
test('retained succeeded generation replay never restores an older active pointer or grants',async()=>{
  const f=fixture();await stage(f.indexer);await publish(f.indexer);f.client.document=[['newer-ready-generation',false,'auth']];
  const replay=await publish(f.indexer);assert.equal(replay.replayed,true);assert.equal(replay.provider_calls,0);assert.equal(f.client.document[0][0],'newer-ready-generation');assert.equal(f.client.published.length,1);assert.equal(f.transport.calls.length,1);
  f.client.grants=[[false]];await assert.rejects(publish(f.indexer),UnauthorizedScope);assert.equal(f.client.document[0][0],'newer-ready-generation');await clean(f);
});
test('ingest retains zero-queue admission across staging and caller publication hook',async()=>{
  const f=fixture(),entered=deferred(),gate=deferred();const pending=f.indexer.ingest('synthetic source',input({before_publish:async()=>{entered.resolve();await gate.promise;}}));
  await entered.promise;await assert.rejects(stage(f.indexer),IndexNotReady);await assert.rejects(publish(f.indexer),IndexNotReady);gate.resolve();const result=await pending;assert.equal(result.provider_calls,1);await clean(f);
});
test('publication repeats complete manifest barrier after caller hook',async()=>{
  const f=fixture();await stage(f.indexer);await assert.rejects(publish(f.indexer,{before_publish:async()=>{f.client.vectorCounts=[[0]];}}),IntegrityViolation);
  assert.equal(f.client.generation[0][1],'staging');assert.deepEqual(f.client.published,[]);assert.equal(f.client.jobs[0][2],'running');await clean(f);
});

test('ingest snapshots source metadata options and publication hook before authorization await',async()=>{
  const entered=deferred(),gate=deferred();let first=true,originalHook=0;
  const f=fixture({authorize:async()=>{if(first){first=false;entered.resolve();await gate.promise;}return true;}});
  const source=Buffer.from('synthetic source'),metadata={nested:[1]},canonical_options={target_bytes:2048};
  const options=input({metadata,canonical_options,before_publish:async()=>{originalHook++;}});const pending=f.indexer.ingest(source,options);
  await entered.promise;source.fill(0);metadata.nested[0]=2;canonical_options.target_bytes=0;options.before_publish=async()=>assert.fail('mutated callback invoked');gate.resolve();
  const result=await pending;assert.equal(originalHook,1);assert.deepEqual(f.transport.calls[0].input,['synthetic source']);assert.equal(f.client.document[0][0],result.generation_id);await clean(f);
});
test('publication driver authorization failure remains typed and preserves staged generation',async()=>{
  const f=fixture();await stage(f.indexer);f.client.failure=['UPDATE cragkit.documents',Object.assign(Error('private-driver-secret'),{code:'42501'})];
  await assert.rejects(publish(f.indexer),error=>error instanceof UnauthorizedScope&&!String(error).includes('private'));
  assert.equal(f.client.generation[0][1],'staging');assert.deepEqual(f.client.published,[]);assert.equal(f.client.jobs[0][2],'running');await clean(f);
});
