/** Synthetic SDK doubles check the harness; native database evidence is separate. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { runResourceWorkload } from '../resource_workload.mjs';

const syntheticSDK = `
import {createHash} from 'node:crypto';
const hash=x=>createHash('sha256').update(x).digest('hex');
export const state={fault:null,resources:[],ingests:0,retrievals:0,closedCounters:0,authorized:0};
export const version='synthetic-test';
export const now=()=>performance.now()/1000;
export const FAKE_PROFILE={model:'fake',tokenizer:'fake-byte-v1',profile_id:'fake_embedding_1536_v1'};
export const parse_pool_config=x=>x;
export const parse_scope=x=>x;
export const parse_request=x=>x;
export const parse_result=x=>x;
const abort=()=>new DOMException('synthetic-private-cancel','AbortError');
class Pool {
 constructor(){this.busy=false;this.queue=[];}
 async connect(){if(this.busy)return new Promise(resolve=>this.queue.push(resolve));this.busy=true;return this.client();}
 client(){const pool=this;let released=false,rejectSleep;
  const client={readyForQuery:true,_activeQuery:null,connection:{stream:{bytesWritten:0,writableLength:0}},
   query(config){if(state.fault!=='dispatch')client.connection.stream.bytesWritten++;client.readyForQuery=false;client._activeQuery=config;
    if(config.text==='SELECT pg_sleep(2)')return new Promise((resolve,reject)=>{rejectSleep=reject;});
    client.readyForQuery=true;client._activeQuery=null;return Promise.resolve({rows:[[1]]});},
   getTransactionStatus(){return 'I';},release(){if(released)return;released=true;if(rejectSleep)state.activeReleased=true;rejectSleep?.(abort());
    const next=pool.queue.shift();if(next)next(pool.client());else pool.busy=false;}};
  return client;}
 async end(){state.poolEnds=(state.poolEnds??0)+1;}
}
export class PoolResource {
 constructor(config){this.config=config;this.work=new Set();this.connecting=new Set();this.factory=async()=>new Pool();state.resources.push(this);}
 async open(){this.pool=await this.factory(this.config);const client=await this.pool.connect();client.release();}
 async withLease(options,body){
  if(state.activeReleased && state.fault==='recovery_delay' && (state.refusals??0)<2){state.refusals=(state.refusals??0)+1;const e=new Error('private-recovery');e.code='provider_unavailable';throw e;}
  if(state.activeReleased && state.fault==='recovery_unknown')throw new Error('private-recovery-unknown');
  if(this.work.size+this.connecting.size>=2){const e=new Error('synthetic-private-overload');e.code=state.fault==='overload'?'wrong':'provider_unavailable';throw e;}
  const marker={};this.work.add(marker);let client,aborted=false,listener;
  const pending=this.pool.connect();let tracked;
  const acquiring=pending.then(value=>{client=value;if(aborted)value.release();return value;});
  void acquiring.catch(()=>{});
  const cancellation=new Promise((_,reject)=>{listener=()=>{aborted=true;reject(state.fault===(client?._activeQuery?'active_cancel':'queued_cancel')?new Error('synthetic-private-cancel-fault'):abort());};options.signal?.addEventListener('abort',listener,{once:true});});
  try{client=await Promise.race([acquiring,cancellation]);return await Promise.race([Promise.resolve().then(()=>body(client,options.signal)),cancellation]);}
  finally{options.signal?.removeEventListener('abort',listener);this.work.delete(marker);
   if(client)client.release();else if(aborted){tracked=acquiring.finally(()=>this.connecting.delete(tracked));this.connecting.add(tracked);void tracked.catch(()=>{});}}
 }
 async close(){this.closed=true;if(state.fault==='cleanup')throw new Error('synthetic-private-close');await this.pool?.end();}
}
export class Cl100kCounter {
 static async create(){return new Cl100kCounter();}
 count(){return 5;}
 close(){state.closedCounters++;}
}
export const count_context=evidence=>({context:JSON.stringify(evidence),context_tokens:state.fault==='tokens'?999:5,total_tokens:261});
export class EmbeddingAdapter {
 constructor(transport,counter,options){this.transport=transport;this.profile=options.profile;}
 async call(text){const out=JSON.parse(Buffer.from(await this.transport(Buffer.from(JSON.stringify({input:[text]})))).toString());
  if(out.data.length!==1||out.data[0].embedding.length!==1536)throw new Error('fake-vector-shape');}
}
export class PostgresVectorIndexer {
 constructor(resource,authorize,embedder){this.resource=resource;this.authorize=authorize;this.embedder=embedder;}
 async ingest(text,options){if(!await this.authorize(options.scope,options.collection,options.document_id))throw Error('auth');
  state.authorized++;state.ingests++;await this.embedder.call(text);
  const receipt={tenant_id:options.scope.tenant_id,collection:options.collection,document_id:options.document_id,
   canonical_sha256:state.fault==='receipt'?'bad':hash(text),embedding_profile:FAKE_PROFILE.profile_id,
   chunk_count:1,provider_calls:1,replayed:false,revision_id:'revision-'+options.document_id,generation_id:'generation-'+options.document_id};
  if(options.document_id==='resource-0')state.source={text,receipt};return receipt;}
}
export class PostgresRetriever {
 constructor(resource,options){this.resource=resource;this.options=options;}
 async retrieve(request,options){state.retrievals++;await this.options.embedder.call(request.query);
  if(request.required_filters[0].value!=='resource-0'||options.scope.tenant_id!=='resource-tenant')throw Error('filter');
  return this.resource.withLease(options,async client=>{await client.query({text:'SELECT 1'});
   const {text,receipt}=state.source;
   const evidence={collection:state.fault==='scope'?'wrong':receipt.collection,document_id:receipt.document_id,
    revision_id:receipt.revision_id,source_sha256:hash(text),start_byte:0,end_byte:Buffer.byteLength(text),
    text:state.fault==='span'?'wrong':text,text_sha256:hash(text)};
   const items=[evidence];
   return {execution:'complete',status:state.fault==='sufficient'?'sufficient':'partial',
    evidence:state.fault==='empty'?[]:items,context:JSON.stringify(items),
    usage:{context_counting:'strict',context_tokens:5,provider_calls:state.fault==='calls'?9:1,attempt_count:1,cost_kind:'known',cost_usd:0}};
  });}
}
`;

async function fixture() {
    const root = await mkdtemp(join(tmpdir(), 'cragkit-resource-sdk-'));
    await mkdir(join(root, 'dist'));
    await writeFile(join(root, 'package.json'), '{"type":"module"}');
    await writeFile(join(root, 'dist/fixture.js'), syntheticSDK);
    for (const name of ['index', 'postgres-pool', 'requests', 'results', 'context', 'embeddings', 'vector-ingestion', 'retrieval']) {
        await writeFile(join(root, 'dist', name + '.js'), "export * from './fixture.js';\n");
    }
    const {state} = await import(pathToFileURL(join(root, 'dist/fixture.js')).href);
    return {root, state, configuration: {sdk_root: root, tokenizer_path: join(root, 'tokenizer'),
        reader_config: {synthetic: 'reader'}, writer_config: {synthetic: 'writer'}},
        close: () => rm(root, {recursive: true, force: true})};
}

test('fixed workload uses the supplied SDK, bounded workers and actual queue/cancel paths', async () => {
    const value = await fixture();
    try {
        const result = await runResourceWorkload(value.configuration);
        assert.equal(result.revision, 'RST-r1');
        assert.equal(result.runtime, 'node');
        assert.equal(result.version, 'synthetic-test');
        assert.equal(result.provider_http_calls, 0);
        assert.equal(result.active_dispatch_observation, 1);
        assert.equal(result.ingestion_ms.length, 3);
        assert.ok(result.ingestion_ms.every(n => n > 0));
        assert.deepEqual(result.retrieval.map(stage => stage.concurrency), [1, 2]);
        for (const stage of result.retrieval) {
            assert.equal(stage.latency_ms.length, 20);
            assert.equal(stage.context_tokens.length, 20);
            assert.equal(stage.attempts.length, 20);
            assert.equal(stage.provider_calls.length, 20);
            assert.ok(stage.elapsed_ms > 0 && stage.throughput_per_second > 0);
        }
        assert.equal(Object.keys(result.checks).length, 12);
        assert.ok(Object.values(result.checks).every(v => v === true));
        assert.equal(value.state.ingests, 3);
        assert.equal(value.state.authorized, 3);
        assert.equal(value.state.retrievals, 40);
        assert.ok(value.state.resources.every(resource => resource.closed && resource.work.size === 0 && resource.connecting.size === 0));
        assert.ok(value.state.resources.every(resource => resource.config.max_size === 1 && resource.config.max_waiting === 1));
        assert.equal(value.state.closedCounters, 1);
        assert.ok(result.peak_rss_bytes > 0);
        assert.ok(!JSON.stringify(result).includes('synthetic-private'));
        assert.ok(!JSON.stringify(result).includes('reader_config'));
    } finally { await value.close(); }
});

test('reports temporary backend refusals before observed healthy reuse', async () => {
    const value = await fixture();
    value.state.fault = 'recovery_delay';
    try {
        const result = await runResourceWorkload(value.configuration);
        assert.equal(result.recovery_attempts, 3);
        assert.equal(result.recovery_refusals, 2);
        assert.ok(result.recovery_elapsed_ms >= 190 && result.recovery_elapsed_ms < 5000);
        assert.equal(result.checks.reuse_after_active, true);
        assert.ok(value.state.resources.every(resource => resource.closed));
    } finally { await value.close(); }
});

test('does not retry unrelated recovery failures or expose their details', async () => {
    const value = await fixture();
    value.state.fault = 'recovery_unknown';
    try {
        await assert.rejects(runResourceWorkload(value.configuration), error => {
            assert.equal(error.message, 'resource_workload_failed');
            assert.equal(error.stage, 'active_reuse');
            assert.equal(error.category, 'unknown');
            assert.ok(!JSON.stringify(error).includes('private-recovery'));
            return true;
        });
        assert.ok(value.state.resources.every(resource => resource.closed));
    } finally { await value.close(); }
});

for (const fault of ['receipt', 'scope', 'span', 'tokens', 'calls', 'sufficient', 'empty', 'overload', 'dispatch', 'queued_cancel', 'active_cancel']) {
    test(`refuses ${fault} invariant and closes owned resources`, async () => {
        const value = await fixture();
        try {
            value.state.fault = fault;
            await assert.rejects(runResourceWorkload(value.configuration), error => {
                assert.equal(error.message, 'resource_workload_failed');
                assert.equal(error.cause, undefined);
                assert.ok(!error.stack.includes('synthetic-private'));
                return true;
            });
            assert.ok(value.state.resources.every(resource => resource.closed));
            assert.equal(value.state.closedCounters, 1);
        } finally { await value.close(); }
    });
}

test('cleanup faults never produce a success summary or disclose raw error', async () => {
    const value = await fixture();
    try {
        value.state.fault = 'cleanup';
        await assert.rejects(runResourceWorkload(value.configuration), {message: 'resource_workload_cleanup_failed'});
        assert.ok(value.state.resources.every(resource => resource.closed));
        assert.equal(value.state.closedCounters, 1);
    } finally { await value.close(); }
});

for (const config of [null, {}, {sdk_root: '/unknown', tokenizer_path: '/unknown', reader_config: {}, writer_config: {}, extra: true}]) {
    test('invalid configuration fails before dynamic imports', async () => {
        await assert.rejects(runResourceWorkload(config), {message: 'resource_workload_invalid'});
    });
}

test('configuration getters are refused without execution', async () => {
    let reads = 0;
    const config = {reader_config: {}, writer_config: {}, tokenizer_path: '/fake',
        get sdk_root() { reads++; throw Error('synthetic-private-getter'); }};
    await assert.rejects(runResourceWorkload(config), {message: 'resource_workload_invalid'});
    assert.equal(reads, 0);
});
