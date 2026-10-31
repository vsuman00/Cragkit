/** Actual native backend/direct/LangChain/MCP conformance. */
import {createRequire} from 'node:module';
import http from 'node:http';
import {PassThrough} from 'node:stream';
import {execFile} from 'node:child_process';
import {isDeepStrictEqual as same} from 'node:util';
import {writeFileSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {PoolResource,parse_pool_config,now,bounded} from '../packages/typescript/dist/postgres-pool.js';
import {parse_request,parse_scope} from '../packages/typescript/dist/requests.js';
import {CorrectiveRetriever} from '../packages/typescript/dist/corrective.js';
import {PostgresCorrectiveBackend} from '../packages/typescript/dist/postgres-corrective.js';
import {QdrantCorrectiveBackend} from '../packages/typescript/dist/qdrant-corrective.js';
import {QdrantSearchStore,FetchQdrantTransport} from '../packages/typescript/dist/qdrant.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {InvalidRequest,ProviderUnavailable} from '../packages/typescript/dist/errors.js';
import {ManagedQdrantSupervisor,PostgresQdrantWriter,QdrantReconciliationVerifier,PostgresQdrantRecovery,
  PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport,QdrantPublicationManager} from '../packages/typescript/dist/qdrant-publication.js';
import {create_tool} from '../packages/langchain-typescript/dist/index.js';
import {create_server,BoundedStdioTransport} from '../packages/mcp-typescript/dist/index.js';
const requireSDK=createRequire(new URL('../packages/mcp-typescript/package.json',import.meta.url));
const {Client}=await import(requireSDK.resolve('@modelcontextprotocol/client'));
const CHECKS=['common_native_data_ready','postgres_routes_match','qdrant_routes_match','source_identity_status_match',
  'provider_budget_difference_explicit','partial_generation_never_released','forged_input_refused','owned_cleanup_verified'];
const assert=(value,code)=>{if(!value)throw new Error(code);};
const bytes=value=>[...Buffer.from(JSON.stringify(value))];
const decode=value=>JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.from(value)));
const cancellation=new AbortController();process.on('SIGTERM',()=>cancellation.abort());process.on('SIGINT',()=>cancellation.abort());
async function listener(address){
  return new Promise((resolve,reject)=>execFile('/usr/sbin/lsof',['-nP','-a','-iTCP@127.0.0.1:'+new URL(address).port,'-sTCP:LISTEN','-t'],
    {encoding:'utf8',maxBuffer:1024,timeout:3000},(error,out,err)=>error?.code===1&&out===''&&err===''?resolve():reject(new Error('listener_remains'))));
}
async function sdk(host,work){
  const input=new PassThrough(),output=new PassThrough(),runner=host.run_stdio({input,output});
  const client=new Client({name:'cragkit-v5-conformance',version:'0.0.0'}),transport=new BoundedStdioTransport(output,input);
  try{await client.connect(transport);return await work(client);}
  finally{input.end();await host.close();await client.close();await runner;input.destroy();output.destroy();}
}
async function run(value){
  const {inputs}=value,options={deadline:now()+120,signal:cancellation.signal},scope=parse_scope(inputs.scope);
  const pools=[],owned=[],observations=[],checks=[];let address,routeCalls=0;
  function pool(raw){const item=new PoolResource(parse_pool_config(raw));assert(item.config.max_size===1,'pool_bound');pools.push(item);return item;}
  const writerPool=pool(value.writer_config),supervisorPool=pool(value.supervisor_config);
  const supervisor=new ManagedQdrantSupervisor(value.binary,value.work_dir,inputs.instance_id,inputs.config);
  const writer=new PostgresQdrantWriter(writerPool,inputs.config,inputs.instance_id),verifier=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(supervisorPool,inputs.config,supervisor,verifier);
  const authority=new PostgresQdrantPublicationAuthority(writer,recovery),transport=new ManagedQdrantPublicationTransport(supervisor);
  const allowed=async(selected,collection,document)=>collection===inputs.base.manifest.collection
    &&[inputs.base,inputs.foreign].some(stage=>selected.tenant_id===stage.manifest.tenant_id&&document===stage.manifest.document_id);
  const manager=new QdrantPublicationManager(authority,transport,inputs.config,supervisor,allowed);
  owned.push(manager,transport,authority,recovery,verifier,writer);
  const target='/collections/'+inputs.config.physical_collection,reference=stage=>Object.fromEntries(['collection','document_id','intent_id'].map(key=>[key,stage.intent[key]]));
  const ledger=()=>new ExecutionLedger({limits:{deadline_ms:60000,max_provider_calls:0},deadline:options.deadline});
  const counter={name:'fake-byte-v1',count:text=>Buffer.byteLength(text)};
  const embedding=async body=>{
    const query=decode(body).input[0],vector=Array(1536).fill(0);vector[query==='pending'?1:0]=1;
    return Buffer.from(JSON.stringify({model:inputs.config.dense_profile.model,data:[{index:0,embedding:vector}],
      usage:{prompt_tokens:Buffer.byteLength(query),total_tokens:Buffer.byteLength(query)}}));
  };
  try{
    await supervisor.initialize({...options,provision:async(admin,probe)=>{
      await admin.request('PUT',target,{...options,body:bytes(inputs.collection_config)});
      const path='/collections/'+probe.collection;
      await admin.request('PUT',path,{...options,body:bytes(probe.collection_config)});
      await admin.request('PUT',path+'/points?wait=true&ordering=strong',{...options,body:bytes({points:[probe.point]})});
    }});address=supervisor.identity().endpoint;
    await writerPool.open();await supervisorPool.open();await manager.initialize(options);
    for(const stage of [inputs.base,inputs.foreign]){
      const selected=parse_scope({...inputs.scope,tenant_id:stage.manifest.tenant_id});
      await manager.stage(stage,selected,ledger(),options);
      assert((await manager.publish(reference(stage),selected,ledger(),options)).published,'publication');
    }
    await manager.stage(inputs.pending,scope,ledger(),options);
    const nativeRequest=http.request,partialBatches=[];
    http.request=function(requestOptions,callback){
      const outgoing=nativeRequest.call(this,requestOptions,callback);
      if(requestOptions.method==='PUT'&&requestOptions.path===target+'/points?wait=true&ordering=strong'){
        const index=partialBatches.length;partialBatches.push(null);const nativeEnd=outgoing.end,nativeWrite=outgoing.write,chunks=[];
        outgoing.write=function(body,...args){chunks.push(Buffer.from(body));return index===0?nativeWrite.call(this,body,...args):true;};
        outgoing.end=function(body){
          if(body!==undefined)chunks.push(Buffer.from(body));partialBatches[index]=decode(Buffer.concat(chunks)).points.map(point=>point.id);
          if(index===0)return nativeEnd.call(this,body);
          queueMicrotask(()=>outgoing.destroy(new ProviderUnavailable()));return outgoing;
        };
      }return outgoing;
    };
    try{
      let refused=false;
      try{await manager.publish(reference(inputs.pending),scope,ledger(),options);}
      catch(error){assert(error instanceof ProviderUnavailable,'partial_error');refused=true;}
      assert(refused,'partial_write_not_interrupted');
    }finally{http.request=nativeRequest;}
    assert(same(partialBatches.map(batch=>batch.length),[8,1]),'partial_batches');
    const snapshot=await writer.manager_snapshot({...reference(inputs.pending),scope,owner_token:'00000000-0000-4000-8000-000000000087'},options);
    assert(snapshot.pending&&snapshot.document.active_generation_id===inputs.base.manifest.generation_id,'partial_publication');
    await supervisorPool.withLease(options,async client=>{
      await client.query({text:'BEGIN READ ONLY',rowMode:'array'});
      try{
        await client.query({text:"SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",values:[inputs.instance_id],rowMode:'array'});
        const rows=(await client.query({text:'SELECT state,sequence::text FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND intent_id=$2 ORDER BY sequence',values:[inputs.instance_id,inputs.pending.intent.intent_id],rowMode:'array'})).rows;
        assert(same(rows,[['settled','1'],['unknown','2']]),'partial_journal');await client.query({text:'COMMIT',rowMode:'array'});
      }catch(error){await client.query({text:'ROLLBACK',rowMode:'array'});throw error;}
    });
    const capability=supervisor.issue_attempt({intent_id:'conformance-fixture',owner_token:'00000000-0000-4000-8000-000000000087',epoch:1,dispatch_id:'conformance-fixture'},options);
    let credential;await supervisor.deliver_worker_credential(capability,raw=>{credential=raw;},options);
    const handle=supervisor.transport_for(capability);
    try{
      const found=[];
      for(const batch of partialBatches){const response=decode(await handle.request('POST',target+'/points',{...options,body:bytes({ids:batch,with_payload:true,with_vector:true})}));found.push(...response.result);}
      assert(found.length===8&&same(found.map(point=>point.id).sort(),[...partialBatches[0]].sort()),'partial_readback');
    }
    finally{await handle.close();}
    await writerPool.close();await supervisorPool.close();
    const pg=pool(value.postgres_config),reader=pool(value.reader_config);await pg.open();await reader.open();
    const candidateTransport=new FetchQdrantTransport(credential.endpoint,{api_key:credential.api_key,allow_loopback_http:true});
    const candidates=new QdrantSearchStore(inputs.config,candidateTransport),sources=new PostgresQdrantSourceStore(reader,inputs.config);
    owned.push(candidateTransport,candidates,sources);await candidates.initialize(options);await sources.initialize(options);
    const backends={postgres_lexical:new PostgresCorrectiveBackend({resource:pg}),qdrant_dense:new QdrantCorrectiveBackend(candidates,sources,{embedding_transport:embedding,token_counter:counter})};
    checks.push(CHECKS[0]);
    for(const [profile,backend] of Object.entries(backends)){
      for(const item of inputs.cases){
        const engine=new CorrectiveRetriever({backend,policy:item.policy,batch_size:1});
        const request=parse_request({...item.template,request_id:item.id,query:item.query});
        const args={request_id:item.id,query:item.query,collection:request.collection};
        const direct=(await engine.retrieve(request,{...options,scope})).result;
        const tool=create_tool({engine,template:item.template,scope:inputs.scope,
          final_serializer:actual=>JSON.stringify({role:'tool',content:typeof actual==='string'?actual:actual.content})});
        assert(same(JSON.parse(await tool.invoke(args)),direct),'tool_result');
        const host=create_server({engine,template:item.template,scope:inputs.scope,final_serializer:actual=>JSON.stringify({role:'tool',result:actual})});
        await sdk(host,async client=>{
          const answer=await client.callTool({name:'cragkit_retrieve',arguments:args});
          assert(!answer.isError&&answer.content.length===1&&same(JSON.parse(answer.content[0].text),direct),'mcp_result');
        });
        const expected=profile==='qdrant_dense'&&item.id==='provider_budget'?'insufficient':item.expected_status;
        assert(direct.status===expected&&direct.execution==='complete','status');
        assert(direct.usage.provider_calls===(profile==='qdrant_dense'&&item.id!=='provider_budget'?1:0),'usage');
        assert(direct.usage.attempt_count===1,'attempt');assert(expected!=='insufficient'||direct.evidence.length===0,'evidence');
        observations.push({profile,case:item.id,result:direct});routeCalls+=3;
      }checks.push(CHECKS[profile==='postgres_lexical'?1:2]);
    }
    for(const item of inputs.cases){
      if(item.id==='provider_budget')continue;
      const left=observations.find(row=>row.profile==='postgres_lexical'&&row.case===item.id).result;
      const right=observations.find(row=>row.profile==='qdrant_dense'&&row.case===item.id).result;
      for(const key of ['request_id','status','execution','evidence','context','facets','versions'])assert(same(left[key],right[key]),'backend_'+key);
    }checks.push(...CHECKS.slice(3,6));
    const guard=new CorrectiveRetriever({backend:backends.qdrant_dense,batch_size:1}),template=inputs.cases[0].template;
    let guardCalls=0;const observed={async retrieve(...args){guardCalls++;return guard.retrieve(...args);}};
    const tool=create_tool({engine:observed,template,scope:inputs.scope,final_serializer:actual=>JSON.stringify(actual)});
    for(const extra of ['scope','tenant_id','limits','required_filters']){
      let rejected=false;
      try{await tool.invoke({request_id:'forged',query:'café',collection:template.collection,[extra]:{}});}
      catch(error){assert(error instanceof InvalidRequest,'forged_error');rejected=true;}
      assert(rejected,'forged_accepted');
    }
    const host=create_server({engine:observed,template,scope:inputs.scope,final_serializer:actual=>JSON.stringify(actual)});
    await sdk(host,async client=>{
      for(const extra of ['scope','tenant_id','limits','required_filters']){
        const answer=await client.callTool({name:'cragkit_retrieve',arguments:{request_id:'forged',query:'café',collection:template.collection,[extra]:{}}});
        assert(answer.isError&&answer.content[0].text==='invalid_request','forged_mcp');
      }
    });assert(guardCalls===0,'forged_engine_called');checks.push(CHECKS[6]);
  }finally{
    const failures=[];
    for(const item of [...owned,...pools,supervisor])if(typeof item.close==='function')try{await bounded(item.close(),{deadline:now()+5});}catch{failures.push(true);}
    if(address)await listener(address);
    assert(!failures.length&&pools.every(pool=>pool.state==='closed'&&pool.work.size===0&&pool.connecting.size===0),'cleanup_failed');
  }
  checks.push(CHECKS[7]);return {runtime:'typescript',checks,route_calls:routeCalls,boundary_refusals:8,observations,cleanup_verified:true};
}
let path;
try{
  const chunks=[];let size=0;for await(const chunk of process.stdin){size+=chunk.length;assert(size<=1048576,'input_bound');chunks.push(chunk);}
  const value=decode(Buffer.concat(chunks));path=join(dirname(value.work_dir),'node-failure.json');
  process.stdout.write(JSON.stringify(await run(value)));
}catch(error){const result={ok:false,error:error.name,locations:error.stack?.split('\n').slice(1)};if(path)writeFileSync(path,JSON.stringify(result));process.stdout.write(JSON.stringify(result));process.exitCode=1;}
