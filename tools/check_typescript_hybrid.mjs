/** Native HY-r1 runtime/evaluation child: restricted credentials only. */
import assert from 'node:assert/strict';
import {readFileSync,lstatSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {PoolResource,parse_pool_config,now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresRetriever} from '../packages/typescript/dist/retrieval.js';
import {PostgresSession} from '../packages/typescript/dist/postgres-session.js';
import {query} from '../packages/typescript/dist/ingestion.js';
import {EmbeddingAdapter,FAKE_PROFILE} from '../packages/typescript/dist/embeddings.js';
import {parse_request,parse_scope} from '../packages/typescript/dist/contracts.js';
import {encode} from '../evaluation/runners/synthetic-vectors.mjs';
import {verifyNeonResource} from './check_typescript_postgres.mjs';

function privateJSON(path){
  const info=lstatSync(path);
  assert.ok(info.isFile()&&info.uid===process.getuid()&&(info.mode&0o077)===0);
  return JSON.parse(readFileSync(path,'utf8'));
}
function normalized(value){
  const result=structuredClone(value);
  for(const stage of result.usage.stage_durations)stage.duration_ms=0;
  return result;
}
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
const replies=input[Symbol.asyncIterator]();
async function owner(enabled){
  console.log(JSON.stringify({type:'owner',action:'tombstone',enabled}));
  const reply=await replies.next();assert.ok(!reply.done&&JSON.parse(reply.value).ok===true);
}
async function run(config,fixture){
  const resource=new PoolResource(parse_pool_config({...config,max_size:1}));
  if(fixture.neon)verifyNeonResource(resource,config.host);
  const checks=[],latency_ms={lexical:[],dense:[],hybrid:[]};
  const embedder=()=>new EmbeddingAdapter(async body=>{
    const value=JSON.parse(Buffer.from(body).toString('utf8'));
    const tokens=value.input.reduce((sum,text)=>sum+Buffer.byteLength(text),0);
    return Buffer.from(JSON.stringify({model:FAKE_PROFILE.model,
      data:value.input.map((text,index)=>({index,embedding:encode(text)})),
      usage:{prompt_tokens:tokens,total_tokens:tokens}}));
  },{name:'fake-byte-v1',count:text=>Buffer.byteLength(text)});
  try{
    await resource.open();
    for(const entry of fixture.fault_cases){
      const original=PostgresSession.prototype.transaction;
      let first=true;
      PostgresSession.prototype.transaction=function(request,options,body){
        return original.call(this,request,options,async handle=>{
          if(first){
            first=false;
            const snapshot=await query(handle.client,"SELECT set_config('cragkit.hybrid_probe',$1,true),pg_current_snapshot()::text",[config.user+'_hybrid'],options);
            for(const family of ['dense','lexical','identifier']){
              if(family===entry.family)continue;
              const originalMethod=handle[family+'_candidates'].bind(handle);
              handle[family+'_candidates']=async(...args)=>{
                const current=await query(handle.client,"SELECT current_setting('cragkit.hybrid_probe',true),pg_current_snapshot()::text",[],options);
                assert.deepEqual(current,snapshot);return originalMethod(...args);
              };
            }
            handle[entry.family+'_candidates']=async()=>{
              await query(handle.client,'SELECT 1/0',[],options);
              throw Error('fault_not_raised');
            };
          }
          return body(handle);
        });
      };
      try{
        const retriever=new PostgresRetriever(resource,{mode:'hybrid',embedder:embedder(),allow_degraded:entry.allow_degraded});
        const request=parse_request({query:'ERR-17',collection:fixture.collection,
          required_filters:[{field:'document_id',op:'eq',value:'retry-policy'}]});
        let result,error;
        try{result=await retriever.retrieve(request,{scope:parse_scope(fixture.scopes[0]),deadline:now()+20});}
        catch(caught){error=caught;}
        if(entry.expected_error){assert.equal(error?.code,entry.expected_error);}
        else{
          if(error)throw error;
          assert.equal(result.execution,entry.expected_execution);assert.ok(result.evidence.length);
          assert.ok(result.evidence.every(item=>item.document_id==='retry-policy'));
          assert.ok(result.usage.stage_durations.some(item=>item.stage===entry.family+'_failed_provider_unavailable'));
        }
        checks.push('node_'+entry.id.replaceAll('-','_'));
      }finally{PostgresSession.prototype.transaction=original;}
    }
    const originalTransaction=PostgresSession.prototype.transaction;
    let transactions=0;
    PostgresSession.prototype.transaction=function(request,options,body){
      transactions++;
      return (async()=>{
        if(transactions===2)await owner(true);
        return originalTransaction.call(this,request,options,body);
      })();
    };
    try{
      const result=await new PostgresRetriever(resource,{mode:'hybrid',embedder:embedder()}).retrieve(
        parse_request({query:'ERR-17',collection:fixture.collection,required_filters:[{field:'document_id',op:'eq',value:'retry-policy'}]}),
        {scope:parse_scope(fixture.scopes[0]),deadline:now()+25});
      assert.equal(result.evidence.length,0);assert.equal(result.status,'insufficient');
      assert.ok(result.limitations.some(item=>item.code==='stale_evidence'));
      checks.push('node_hybrid_fresh_source_tombstone_denied');
    }finally{PostgresSession.prototype.transaction=originalTransaction;await owner(false);}
    for(const entry of fixture.cases){
      const options=entry.mode==='lexical'?{}:{mode:entry.mode,embedder:embedder()};
      const started=now();
      const result=await new PostgresRetriever(resource,options).retrieve(parse_request(entry.request),
        {scope:parse_scope(entry.scope),deadline:now()+25});
      latency_ms[entry.mode].push((now()-started)*1000);
      assert.deepEqual(normalized(result),entry.expected);
    }
    checks.push('node_development_ablation_18_requests_full_result_parity');
    return {state:'passed',checks,latency_ms};
  }finally{await resource.close();}
}
if(process.argv[2]!=='--allow-hybrid-checks')throw Error('Explicit fixture authorization required');
try{console.log(JSON.stringify(await run(privateJSON(process.argv[3]),privateJSON(process.argv[4]))));}
catch{console.log(JSON.stringify({state:'failed',code:'node_hybrid_failed'}));process.exitCode=1;}
finally{input.close();}
