import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { PassThrough } from 'node:stream';
import { setImmediate as turn } from 'node:timers/promises';
import net from 'node:net';
import { Client } from '@modelcontextprotocol/client';
import { Cl100kCounter } from 'cragkit/context';
import { parse_result } from 'cragkit/contracts';
import { ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest,
  ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from 'cragkit/errors';
import { create_server, BoundedStdioTransport } from '../dist/index.js';

const scope={tenant_id:'tenant',principal_id:'principal',authorization_revision:'1',grant_ids:['grant']};
const template={collection:'collection',required_filters:[{field:'document_id',op:'eq',value:'document'}],
  limits:{deadline_ms:1000,max_candidates:12,max_attempts:3,max_subqueries:3,max_provider_calls:8,max_context_tokens:20000},
  output_profile:{renderer:'cragkit.context.v2',counting_mode:'estimated',tokenizer:null,envelope_reserve_tokens:17}};
const args={request_id:'request',query:'ERR-17 café "quoted" 🙂',collection:'collection'};
const copy=structuredClone;
function result(request_id='request',status='partial',execution='complete'){
  const text=args.query,digest=createHash('sha256').update(text).digest('hex');
  return parse_result({request_id,status,execution,evidence:status==='insufficient'?[]:[{evidence_id:'evidence',collection:'collection',
    document_id:'document',revision_id:'revision',chunk_id:'chunk',source_locator:'synthetic:source',start_byte:0,end_byte:Buffer.byteLength(text),
    text,source_sha256:digest,text_sha256:digest}],limitations:execution==='degraded'?[{code:'degraded_search'}]:[],context:'[]',
    usage:{attempt_count:1,provider_calls:0,provider_input_tokens:0,provider_output_tokens:0,cost_usd:0,cost_kind:'known',context_tokens:1,context_counting:'estimated'},
    ...(status==='sufficient'?{facets:[{facet_id:'facet',question:'What applies?',state:'supported',evidence_ids:['evidence'],assessment_method:'fixture',assessment_version:'1'}],versions:{policy:'reviewed.fixture.v1'}}:{})});
}
class Engine{
  calls=[];
  constructor(status='partial',execution='complete',wrapped=true){this.status=status;this.execution=execution;this.wrapped=wrapped;}
  async retrieve(request,options){this.calls.push({request,options});const value=result(request.request_id,this.status,this.execution);
    return this.wrapped?{result:value,diagnostics:{secret:'private-canary'}}:value;}
}
const serializer=actual=>JSON.stringify({role:'tool',result:actual});
const host=(engine=new Engine(),overrides={})=>create_server({engine,template:copy(template),scope:copy(scope),final_serializer:serializer,...overrides});
const gate=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
async function withClient(target,run){
  const input=new PassThrough(),output=new PassThrough();
  const runner=target.run_stdio({input,output});
  const transport=new BoundedStdioTransport(output,input);
  const client=new Client({name:'cragkit-test',version:'0.0.0'});
  try{await client.connect(transport);return await run(client,{input,output,transport});}
  finally{input.end();await target.close();await client.close();await runner;input.destroy();output.destroy();}
}

for(const [status,execution] of [['sufficient','complete'],['partial','complete'],['insufficient','complete'],['partial','degraded']]){
  for(const wrapped of [true,false])test(`official SDK stdio discovery and ${status}/${execution}, wrapped=${wrapped}`,async()=>{
    const engine=new Engine(status,execution,wrapped),target=host(engine);assert.equal(engine.calls.length,0);
    await withClient(target,async client=>{
      const listing=await client.listTools();assert.deepEqual(listing.tools.map(item=>item.name),['cragkit_retrieve']);
      assert.equal(listing.tools[0].inputSchema.additionalProperties,false);
      assert.deepEqual(Object.keys(listing.tools[0].inputSchema.properties).sort(),['collection','query','request_id','schema_version','search_hints']);
      assert.equal(listing.tools[0].inputSchema.properties.search_hints.maxItems,8);
      assert.equal(listing.tools[0].inputSchema.properties.query.type,'string');
      assert.equal(listing.tools[0].inputSchema.properties.collection.type,'string');
      const answer=await client.callTool({name:'cragkit_retrieve',arguments:copy(args)});
      assert.equal(answer.isError,false);assert.equal(answer.content.length,1);
      assert.deepEqual(JSON.parse(answer.content[0].text),result('request',status,execution));
      assert.ok(!JSON.stringify(answer).includes('private-canary'));
    });
    assert.deepEqual(engine.calls[0].request.required_filters,template.required_filters);
    assert.equal(engine.calls[0].request.limits.max_candidates,12);assert.deepEqual(engine.calls[0].options.scope,scope);
    assert.ok(engine.calls[0].options.signal instanceof AbortSignal);await target.close();
  });
}

for(const extra of [{scope},{tenant_id:'forged'},{required_filters:[]},{limits:{max_candidates:1000}},
  {output_profile:{}},{collection:'wrong'},{query:''},{unknown:'credential-canary'}]){
  test(`rejects forged input ${Object.keys(extra)[0]}`,async()=>{
    const engine=new Engine();await withClient(host(engine),async client=>{
      const answer=await client.callTool({name:'cragkit_retrieve',arguments:{...args,...extra}});
      assert.equal(answer.isError,true);assert.equal(answer.content[0].text,'invalid_request');
      assert.ok(!JSON.stringify(answer).includes('credential-canary'));assert.equal(engine.calls.length,0);
    });
  });
}

test('snapshots trusted scope and template and gives serializer exact SDK result',async()=>{
  const mutableTemplate=copy(template),mutableScope=copy(scope),engine=new Engine(),seen=[];
  const target=host(engine,{template:mutableTemplate,scope:mutableScope,final_serializer:actual=>{seen.push(actual);return serializer(actual);}});
  mutableTemplate.required_filters.length=0;mutableScope.grant_ids.push('forged');
  const actual=await target.retrieve(args);assert.equal(seen[0],actual);
  assert.deepEqual(engine.calls[0].options.scope,scope);assert.deepEqual(engine.calls[0].request.required_filters,template.required_filters);
  await target.close();
});

for(const [error,code] of [[new UnauthorizedScope(),'unauthorized_scope'],[new Error('SECRET password sql query'),'provider_unavailable']]){
  test(`stable sanitized error ${code}`,async()=>{
    await withClient(host({async retrieve(){throw error;}}),async client=>{
      const answer=await client.callTool({name:'cragkit_retrieve',arguments:args});
      assert.equal(answer.isError,true);assert.equal(answer.content[0].text,code);assert.ok(!JSON.stringify(answer).includes('SECRET'));
    });
  });
}

for(const mode of ['bytes','tokens','exception'])test(`error wrapper ${mode} fails as sanitized protocol error`,async()=>{
  const target=host({async retrieve(){throw new UnauthorizedScope();}},{final_serializer:actual=>{
    assert.equal(actual.isError,true);if(mode==='exception')throw new Error('SECRET serializer');
    return 'x'.repeat(mode==='bytes'?262145:100000);
  }});
  await withClient(target,async client=>{
    await assert.rejects(client.callTool({name:'cragkit_retrieve',arguments:args}),error=>{
      assert.equal(error.code,-32603);assert.ok(error.message.includes('invalid_request'));
      assert.ok(!JSON.stringify(error).includes('SECRET'));return true;
    });
  });
});

test('result identity and final representation overflow fail before release',async()=>{
  let target=host({async retrieve(){return result('different');}});
  await assert.rejects(target.retrieve(args),IntegrityViolation);await target.close();
  target=host(new Engine(),{final_serializer:()=> 'x'.repeat(262145)});
  await assert.rejects(target.retrieve(args),ContextBudgetTooSmall);await target.close();
  target=host(new Engine(),{final_serializer:()=>null});
  await assert.rejects(target.retrieve(args),InvalidRequest);await target.close();
  target=host({async retrieve(){return {...result(),context:'x'.repeat(262144)};}});
  await assert.rejects(target.retrieve(args),ContextBudgetTooSmall);await target.close();
});

test('authentic strict counter counts complete final wrapper including reserve',async()=>{
  const counter=await Cl100kCounter.create(new URL('../../../artifacts/tokenizers/cl100k_base.tiktoken',import.meta.url));
  try{
    const strict=copy(template);Object.assign(strict.output_profile,{counting_mode:'strict',tokenizer:'cl100k_base'});
    let serialized;let target=host(new Engine(),{template:strict,counter,final_serializer:actual=>{serialized=serializer(actual);return serialized;}});
    await target.retrieve(args);await target.close();
    strict.limits.max_context_tokens=counter.count(serialized)+16;
    target=host(new Engine(),{template:strict,counter});await assert.rejects(target.retrieve(args),ContextBudgetTooSmall);await target.close();
    assert.throws(()=>host(new Engine(),{template:strict}),UnsupportedCapability);
  }finally{counter.close();}
});

for(const stop of ['deadline','cancel','close'])test(`noncooperative ${stop} retains slot until actual drain`,async()=>{
  const started=gate(),release=gate(),aborted=gate();let calls=0;
  const engine={async retrieve(request,{signal}){calls++;signal.addEventListener('abort',()=>aborted.resolve(),{once:true});started.resolve();await release.promise;return result(request.request_id);}};
  const limited=copy(template);limited.limits.deadline_ms=stop==='deadline'?10:1000;
  const target=host(engine,{template:limited}),controller=new AbortController();
  const pending=target.retrieve(args,controller.signal);await started.promise;
  if(stop==='cancel')controller.abort();if(stop==='close'){await target.close();await target.close();}
  await assert.rejects(pending,stop==='deadline'?DeadlineExceeded:ProviderUnavailable);await aborted.promise;
  await assert.rejects(target.retrieve(args),ProviderUnavailable);assert.equal(calls,1);
  release.resolve();await turn();
  if(stop!=='close')assert.equal((await target.retrieve(args)).isError,false);
  await target.close();
});

test('SDK cancellation suppresses late response and competition fails before engine',async()=>{
  const started=gate(),release=gate(),aborted=gate();let calls=0;
  const target=host({async retrieve(request,{signal}){calls++;signal.addEventListener('abort',()=>aborted.resolve(),{once:true});started.resolve();await release.promise;return result(request.request_id);}});
  await withClient(target,async client=>{
    const controller=new AbortController();
    const pending=client.callTool({name:'cragkit_retrieve',arguments:args},{signal:controller.signal});
    const rejection=assert.rejects(pending);await started.promise;
    const competing=await client.callTool({name:'cragkit_retrieve',arguments:args});
    assert.equal(competing.isError,true);assert.equal(competing.content[0].text,'provider_unavailable');assert.equal(calls,1);
    controller.abort();await rejection;await aborted.promise;release.resolve();await turn();
    assert.equal((await client.callTool({name:'cragkit_retrieve',arguments:args})).isError,false);
  });
});

test('stdio disconnect aborts native work and never emits its late completion',async()=>{
  const started=gate(),release=gate(),aborted=gate();
  const target=host({async retrieve(request,{signal}){signal.addEventListener('abort',()=>aborted.resolve(),{once:true});started.resolve();await release.promise;return result(request.request_id);}});
  await withClient(target,async(client,{input,output,transport})=>{
    const pending=client.callTool({name:'cragkit_retrieve',arguments:args});const rejection=assert.rejects(pending);
    await started.promise;input.end();await aborted.promise;await transport.close();await rejection;
    const late=[];output.on('data',chunk=>late.push(chunk));release.resolve();await turn();assert.equal(late.length,0);
  });
});

for(const chunks of [[Buffer.alloc(65536,120)],[Buffer.alloc(40000,120),Buffer.alloc(25536,120)],
  [Buffer.from([255,10])],[Buffer.from('{bad secret\n')]]){
  test(`bounded stdio rejects malformed frame of ${chunks.reduce((n,c)=>n+c.length,0)} bytes`,async()=>{
    const input=new PassThrough(),output=new PassThrough(),transport=new BoundedStdioTransport(input,output),errors=[],messages=[];
    let closes=0;transport.onerror=error=>errors.push(error.message);transport.onclose=()=>closes++;transport.onmessage=message=>messages.push(message);
    await transport.start();for(const chunk of chunks)input.write(chunk);await turn();
    assert.deepEqual(errors,['invalid_request']);assert.equal(closes,1);assert.deepEqual(messages,[]);
    await transport.close();assert.equal(closes,1);input.destroy();output.destroy();
  });
}

test('bounded stdio permits fragmented valid frame and sanitizes native protocol errors',async()=>{
  const input=new PassThrough(),output=new PassThrough(),transport=new BoundedStdioTransport(input,output),messages=[],sent=[];
  transport.onmessage=message=>messages.push(message);output.on('data',chunk=>sent.push(chunk));await transport.start();
  const frame=Buffer.from('{"jsonrpc":"2.0","method":"tools/list","id":1}\n');input.write(frame.subarray(0,11));input.write(frame.subarray(11));
  assert.equal(messages.length,1);
  await transport.send({jsonrpc:'2.0',id:1,error:{code:-32602,message:'SECRET input',data:{query:'PRIVATE'}}});
  assert.equal(JSON.parse(Buffer.concat(sent).toString()).error.message,'invalid_request');
  assert.ok(!Buffer.concat(sent).toString().includes('SECRET'));await transport.close();input.destroy();output.destroy();
});

test('bounded stdio rejects an incomplete frame on EOF without leaking content',async()=>{
  const input=new PassThrough(),output=new PassThrough(),transport=new BoundedStdioTransport(input,output),errors=[],messages=[];
  let closed=0;transport.onerror=error=>errors.push(error.message);transport.onmessage=message=>messages.push(message);transport.onclose=()=>closed++;
  await transport.start();input.end(Buffer.from('{"PRIVATE":"unfinished'));
  await turn();assert.deepEqual(errors,['invalid_request']);assert.equal(closed,1);assert.deepEqual(messages,[]);
  await transport.close();input.destroy();output.destroy();
});

test('core native host construction and fake retrieval cause no unsolicited network',async()=>{
  const previous=net.Socket.prototype.connect;
  net.Socket.prototype.connect=function(){throw new Error('Unsolicited network');};
  try{const target=host();await target.retrieve(args);await target.close();}
  finally{net.Socket.prototype.connect=previous;}
});
