import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as vector from '../../dist/vector-ingestion.js';
import * as lexical from '../../dist/ingestion.js';
import {PoolResource,parse_pool_config,now} from '../../dist/postgres-pool.js';
import {EXPECTED_HISTORY,_CATALOG_SQL,_HISTORY_SQL,_COLLECTION_SQL} from '../../dist/postgres-session.js';
import {EmbeddingAdapter,FAKE_PROFILE} from '../../dist/embeddings.js';
import {parse_scope} from '../../dist/contracts.js';

export const oracle=JSON.parse(readFileSync(new URL('../../../../contracts/fixtures/vector_generations.json',import.meta.url),'utf8'));
export const scope=(changes={})=>parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['unassigned-group'],...changes});
export const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
export class Client {
  status='I';calls=[];releases=[];staged=[];published=[];document=[];revision=[];generation=[];jobs=[];manifest=[];vectors={};
  role=[[true]];catalog=[[true]];history=EXPECTED_HISTORY;collection=[['0.1','native_fts.v1']];capability=[[true]];
  profile=[[...Object.values(FAKE_PROFILE),'chunk_vectors_fake_1536']];grants=[[true]];missing;counts;vectorCounts;
  readyRows=[[1]];casRows=[[1]];jobRows=[[1]];commits=0;rollbacks=0;gucs=null;failure;
  getTransactionStatus(){return this.status;}
  release(destroy){
    this.releases.push(destroy);
    // Simulate a destroyed client's uncommitted transaction ending at disconnect.
    // The shared fake store remains; the next lease represents a fresh idle session.
    if(destroy&&this.status!=='I'){
      [this.staged,this.published,this.document,this.revision,this.generation,this.jobs,this.manifest,this.vectors]=this.before;
      this.status='I';this.gucs=null;
    }
  }
  async query({text,values}) {
    this.calls.push([text,values]);
    if(this.failure&&text.includes(this.failure[0]))throw this.failure[1];
    if(text==='BEGIN'){this.before=structuredClone([this.staged,this.published,this.document,this.revision,this.generation,this.jobs,this.manifest,this.vectors]);this.status='T';}
    if(text==='COMMIT'){this.commits++;this.status='I';this.gucs=null;}
    if(text==='ROLLBACK'){[this.staged,this.published,this.document,this.revision,this.generation,this.jobs,this.manifest,this.vectors]=this.before;this.rollbacks++;this.status='I';this.gucs=null;}
    const responses=new Map([
      [lexical._WRITER_ROLE_SQL,this.role],[_CATALOG_SQL,this.catalog],[_HISTORY_SQL,this.history],[_COLLECTION_SQL,this.collection],
      [vector._VECTOR_CAPABILITY_SQL,this.capability],[vector._SETUP_HISTORY_SQL,vector.EXPECTED_VECTOR_HISTORY],[vector._PROFILE_SQL,this.profile],
      [vector._VECTOR_JOB_SQL,this.jobs],[lexical._DOCUMENT_LOCK_SQL,this.document],[vector._VECTOR_GENERATION_SQL,this.generation],
      [vector._VECTOR_REVISION_SQL,this.revision],[vector._MANIFEST_SQL,this.manifest],[vector._GRANTS_SQL,this.grants],
      [vector._MISSING_SQL,this.missing??this.manifest.filter(row=>!Object.hasOwn(this.vectors,row[0])).map(row=>[row[0]])],
      [vector._VECTOR_COUNTS_SQL,this.vectorCounts??[[Object.keys(this.vectors).length]]],
      [lexical._COUNTS_SQL,this.counts??[[this.manifest.length,this.manifest.length]]],
    ]);
    if(responses.has(text))return {rows:responses.get(text)};
    if(text.includes("set_config('cragkit.tenant_id'"))this.gucs=values;
    if(/^(INSERT|UPDATE) /.test(text.trimStart())){
      this.staged.push([text,structuredClone(values)]);
      if(text.startsWith('INSERT INTO cragkit.documents')){if(!this.document.length)this.document=[[null,false,values[3]]];return {rows:[['document']]};}
      if(text.startsWith('INSERT INTO cragkit.ingestion_jobs'))this.jobs=[[values[4],values[5],'running',values[2],1]];
      if(text.startsWith('INSERT INTO cragkit.document_revisions'))this.revision=[[values[4],values[7],values[5],values[8],values[6]]];
      if(text.startsWith('INSERT INTO cragkit.index_generations'))this.generation=[[values[3],'staging',values.at(-1),FAKE_PROFILE.profile_id,values[5],'native_fts.v1']];
      if(text===lexical._CHUNKS_SQL)this.manifest=JSON.parse(values.at(-1)).map(row=>[row.chunk_id,row.ordinal,row.start_byte,row.end_byte,row.text,row.text_sha256,row.metadata]);
      if(text===vector._VECTOR_INSERT_SQL)for(const row of JSON.parse(values.at(-1)))this.vectors[row.chunk_id]=row.embedding;
      if(text.startsWith('UPDATE cragkit.ingestion_jobs')&&text.includes('attempt_count'))this.jobs[0][4]++;
      if(text.startsWith('UPDATE cragkit.index_generations')){if(this.readyRows.length)this.generation[0][1]='ready';return {rows:this.readyRows};}
      if(text.startsWith('UPDATE cragkit.documents')){if(this.casRows.length){this.document=[[values[0],false,values.at(-1)]];this.published.push(structuredClone(values));}return {rows:this.casRows};}
      if(text.startsWith('UPDATE cragkit.ingestion_jobs')&&text.includes("state='succeeded'")){if(this.jobRows.length)this.jobs[0][2]='succeeded';return {rows:this.jobRows};}
      return {rows:[[1]]};
    }
    return {rows:[]};
  }
}
export function fixture(options={}) {
  const client=new Client();const pool={leases:0,async connect(){this.leases++;return client;},async end(){assert.fail('borrowed pool closed');}};
  const config=parse_pool_config({host:'host.invalid',dbname:'synthetic',user:'writer',sslrootcert:'/synthetic/ca',passfile:'/synthetic/pass',release_timeout:0.03,close_timeout:0.1});
  const resource=new PoolResource(config,{pool});
  const transport={calls:[],change:null,failureAt:null,block:false,entered:deferred(),async send(body,options){
    assert.equal(client.status,'I');assert.equal(pool.leases,client.releases.length,'provider outside lease');
    const payload=JSON.parse(Buffer.from(body).toString());this.calls.push(payload);
    if(this.failureAt===this.calls.length)throw Error('private transport secret');
    if(this.block){this.entered.resolve();await new Promise((_,reject)=>{if(options.signal.aborted)reject(options.signal.reason);else options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});});}
    const response={model:FAKE_PROFILE.model,data:payload.input.map((_,index)=>({index,embedding:[1,...new Array(1535).fill(0)]}))};
    this.change?.(response);return Buffer.from(JSON.stringify(response));
  }};
  const adapter=new EmbeddingAdapter(transport.send.bind(transport),{name:'fake-byte-v1',count:text=>Buffer.byteLength(text)}, {limits:options.limits});
  const indexer=new vector.PostgresVectorIndexer(resource,options.authorize??(async()=>true),adapter,options.indexerOptions);
  return {client,pool,resource,transport,adapter,indexer};
}
export const input=(changes={})=>({collection:'collection',document_id:'document',intent_id:'intent',source_locator:'synthetic:source',scope:scope(),deadline:now()+2,...changes});
export const stage=(indexer,changes={},source='synthetic source')=>indexer.stage(source,input(changes));
