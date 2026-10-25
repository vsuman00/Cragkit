import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { setImmediate as turn } from 'node:timers/promises';
import net from 'node:net';
import dns from 'node:dns';
import { DynamicStructuredTool, StructuredTool } from '@langchain/core/tools';
import { ToolMessage } from '@langchain/core/messages';
import { convertToOpenAITool } from '@langchain/core/utils/function_calling';
import { RunTree } from 'langsmith/run_trees';
import { getCurrentRunTree, withRunTree } from 'langsmith/traceable';
import { Cl100kCounter } from 'cragkit/context';
import { parse_request, parse_scope, parse_result } from 'cragkit/contracts';
import { CorrectiveRetriever } from 'cragkit/corrective';
import { PlannerAdapter } from 'cragkit/planning';
import { ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest,
  ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from 'cragkit/errors';
import { create_tool } from '../dist/index.js';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const fixtures = process.env.CRAGKIT_FIXTURES ?? path.join(root, 'contracts/fixtures');
const tokenizer = process.env.CRAGKIT_TOKENIZER ?? path.join(root, 'artifacts/tokenizers/cl100k_base.tiktoken');
const fixture = name => JSON.parse(readFileSync(path.join(fixtures, name), 'utf8'));
const copy = value => structuredClone(value);
const scope = {tenant_id:'tenant', principal_id:'principal', authorization_revision:'1', grant_ids:['grant']};
const template = {collection:'collection', required_filters:[{field:'document_id', op:'eq', value:'document'}],
  limits:{deadline_ms:1000, max_candidates:12, max_attempts:3, max_subqueries:3, max_provider_calls:8, max_context_tokens:20000},
  output_profile:{renderer:'cragkit.context.v2', counting_mode:'estimated', tokenizer:null, envelope_reserve_tokens:17}};
const args = {request_id:'request', query:'ERR-17 café "quoted" 🙂', collection:'collection'};
const hash = text => createHash('sha256').update(text).digest('hex');
function result(request_id='request', status='partial', execution='complete') {
  const text=args.query, digest=hash(text);
  const evidence={evidence_id:'evidence',collection:'collection',document_id:'document',revision_id:'revision',chunk_id:'chunk',
    source_locator:'synthetic:source',start_byte:0,end_byte:Buffer.byteLength(text),text,source_sha256:digest,text_sha256:digest};
  return parse_result({request_id,status,execution,evidence:status==='insufficient'?[]:[evidence],
    limitations:execution==='degraded'?[{code:'degraded_search'}]:[],context:'[]',
    usage:{attempt_count:1,provider_calls:0,provider_input_tokens:0,provider_output_tokens:0,cost_usd:0,cost_kind:'known',context_tokens:1,context_counting:'estimated'},
    ...(status==='sufficient'?{facets:[{facet_id:'facet',question:'What applies?',state:'supported',evidence_ids:['evidence'],assessment_method:'fixture',assessment_version:'1'}],versions:{policy:'reviewed.fixture.v1'}}:{})});
}
class Engine {
  constructor(status='partial', execution='complete') { this.calls=[];this.status=status;this.execution=execution; }
  async retrieve(request, options) {
    this.calls.push({request,options});
    return {result:result(request.request_id,this.status,this.execution),diagnostics:{not_model_content:'private-canary'}};
  }
}
function serializer(value) {
  if(value instanceof ToolMessage) return JSON.stringify({role:'tool',name:value.name,tool_call_id:value.tool_call_id,content:value.content});
  assert.equal(typeof value,'string');
  return JSON.stringify({role:'tool',content:value});
}
const tool = (engine=new Engine(), options={}) => create_tool({engine,template:copy(template),scope:copy(scope),final_serializer:serializer,...options});
const native = (input=args,id='call-1') => ({type:'tool_call',id,name:'cragkit_retrieve',args:copy(input)});
const strictTemplate = (max=20000,reserve=17) => ({...copy(template),limits:{...template.limits,max_context_tokens:max},
  output_profile:{...template.output_profile,counting_mode:'strict',tokenizer:'cl100k_base',envelope_reserve_tokens:reserve}});
const gate = () => {let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};

for(const [status,execution] of [['sufficient','complete'],['partial','complete'],['insufficient','complete'],['partial','degraded']]) {
  test(`real SDK plain/native preserve ${status}/${execution}`,async()=>{
    const engine=new Engine(status,execution),target=tool(engine);
    assert.ok(target instanceof StructuredTool && target instanceof DynamicStructuredTool);
    const plain=await target.invoke(copy(args));
    const message=await target.invoke(native(args,'call-"escaped"-🙂'));
    assert.equal(typeof plain,'string');assert.ok(message instanceof ToolMessage);
    assert.equal(message.tool_call_id,'call-"escaped"-🙂');assert.equal(message.name,'cragkit_retrieve');
    assert.deepEqual(JSON.parse(plain),result('request',status,execution));
    assert.deepEqual(JSON.parse(message.content),JSON.parse(plain));
    assert.deepEqual(JSON.parse(await target.call(copy(args))),JSON.parse(plain));
    assert.ok(!plain.includes('private-canary'));
    for(const {request,options} of engine.calls) {
      assert.deepEqual(request.required_filters,template.required_filters);assert.deepEqual(options.scope,scope);
      assert.equal(request.limits.max_provider_calls,8);assert.equal(request.limits.max_candidates,12);
      assert.deepEqual(request.output_profile,template.output_profile);
      assert.ok(options.deadline>=performance.now()/1000-1);
      assert.ok(options.signal instanceof AbortSignal);
    }
  });
}

const invalidInputs=[
  ['scope',{...args,scope}],['limits',{...args,limits:{max_provider_calls:1000}}],
  ['filters',{...args,required_filters:[]}],['profile',{...args,output_profile:{counting_mode:'estimated'}}],
  ['collection',{...args,collection:'other'}],['json-string',JSON.stringify(args)],
  ['wrong-name',{...native(),name:'other'}],['extra-native',{...native(),scope}],
  ['invalid-id',native(args,'bad\0id')],['native-args',{...native(),args:{...args,scope}}],
];
for(const [name,input] of invalidInputs) test(`authority/input rejection ${name}`,async()=>{
  const engine=new Engine();await assert.rejects(tool(engine).invoke(copy(input)),InvalidRequest);assert.equal(engine.calls.length,0);
});

const invalidConfigs=[{callbacks:[]},{callbacks:[{}]},{tags:['secret']},{metadata:{query:'secret'}},{configurable:{scope}},
  {runName:'unsafe'},{recursionLimit:10},{signal:new AbortController().signal,metadata:{source:'secret'}}];
for(const [index,config] of invalidConfigs.entries()) test(`configuration ${index} is not merged`,async()=>{
  const engine=new Engine(),target=tool(engine);
  await assert.rejects(target.invoke(copy(args),config),InvalidRequest);assert.equal(engine.calls.length,0);
  assert.equal(typeof await target.invoke(copy(args),{}),'string');
});

for(const failure of [ProviderUnavailable,UnauthorizedScope,IntegrityViolation,DeadlineExceeded]) {
  test(`typed engine failure ${failure.name} stays typed`,async()=>{
    const engine={async retrieve(){throw new failure();}};
    await assert.rejects(tool(engine).invoke(copy(args)),failure);
  });
}

test('malformed result and replaced request identity fail closed',async()=>{
  for(const payload of [{request_id:'request',status:'sufficient',private:'secret'},result('other-request')]) {
    const engine={async retrieve(){return {result:payload};}};
    await assert.rejects(tool(engine).invoke(copy(args)),error=>error instanceof IntegrityViolation&&!error.message.includes('secret'));
  }
});

for(const boundary of ['engine','serializer']) test(`private ${boundary} exceptions are redacted`,async()=>{
  const secret='private-credential-and-source-canary';
  const engine=boundary==='engine'?{async retrieve(){throw new Error(secret);}}:new Engine();
  const final_serializer=boundary==='serializer'?()=>{throw new Error(secret);}:serializer;
  await assert.rejects(tool(engine,{final_serializer}).invoke(copy(args)),error=>
    error instanceof (boundary==='engine'?ProviderUnavailable:InvalidRequest)&&!error.message.includes(secret));
});

for(const bad of [null,3,{},[]]) test(`non-string final serializer ${JSON.stringify(bad)} rejected`,async()=>{
  await assert.rejects(tool(new Engine(),{final_serializer:()=>bad}).invoke(copy(args)),InvalidRequest);
});

test('strict tokenizer and issued counter required before engine dispatch',async()=>{
  for(const counter of [undefined,{},Object.create(Cl100kCounter.prototype)]) {
    const engine=new Engine();
    await assert.rejects(async()=>{
      const target=tool(engine,{template:strictTemplate(),counter});await target.invoke(copy(args));
    },UnsupportedCapability);
    assert.equal(engine.calls.length,0);
  }
});

test('strict final actual message, escaping, ID and reserve counted at exact boundary',async()=>{
  const counter=await Cl100kCounter.create(tokenizer);
  try {
    const representation='provider wrapper: '+('é "escaped" 🙂 '.repeat(20));
    const tokens=counter.count(representation),reserve=17;
    const final_serializer=value=>{assert.ok(value instanceof ToolMessage);assert.equal(value.tool_call_id,'actual-"id"-🙂');return representation;};
    const accepted=tool(new Engine(),{template:strictTemplate(tokens+reserve,reserve),counter,final_serializer});
    assert.ok(await accepted.invoke(native(args,'actual-"id"-🙂')) instanceof ToolMessage);
    const rejected=tool(new Engine(),{template:strictTemplate(tokens+reserve-1,reserve),counter,final_serializer});
    await assert.rejects(rejected.invoke(native(args,'actual-"id"-🙂')),ContextBudgetTooSmall);
  } finally {counter.close();}
});

test('final serialized byte ceiling applies to actual wrapper',async()=>{
  await assert.rejects(tool(new Engine(),{final_serializer:()=> '🙂'.repeat(65537)}).invoke(native()),ContextBudgetTooSmall);
});

test('trusted snapshots and concurrent requests stay isolated',async()=>{
  const entered=gate(),release=gate(),calls=[];
  const localTemplate=copy(template),localScope=copy(scope);
  const engine={async retrieve(request,options){calls.push({request,options});if(calls.length===2)entered.resolve();await release.promise;return {result:result(request.request_id)};}};
  const target=create_tool({engine,template:localTemplate,scope:localScope,final_serializer:serializer});
  const firstArgs={...args,request_id:'one'},secondArgs={...args,request_id:'two'};
  const first=target.invoke(firstArgs),second=target.invoke(secondArgs);
  try {
    await entered.promise;firstArgs.query='MUTATED';localScope.tenant_id='changed';localTemplate.required_filters=[];localTemplate.limits.max_provider_calls=999;
    release.resolve();const outputs=await Promise.all([first,second]);
    assert.deepEqual(outputs.map(value=>JSON.parse(value).request_id),['one','two']);
    assert.equal(calls[0].request.query,args.query);assert.equal(calls[0].request.limits.max_provider_calls,8);
    assert.deepEqual(calls[0].request.required_filters,template.required_filters);assert.equal(calls[0].options.scope.tenant_id,scope.tenant_id);
    assert.equal(calls[1].options.scope.tenant_id,scope.tenant_id);
  } finally {release.resolve();await Promise.allSettled([first,second]);}
});

test('pre-aborted invocation never calls the engine',async()=>{
  const controller=new AbortController();controller.abort();const engine=new Engine();
  await assert.rejects(tool(engine).invoke(copy(args),{signal:controller.signal}),error=>error?.name==='AbortError');
  assert.equal(engine.calls.length,0);
});

for(const termination of ['abort','deadline']) test(`uncooperative engine ${termination} remains bounded and late errors observed`,async()=>{
  const entered=gate(),release=gate(),finished=gate();
  const engine={async retrieve(){entered.resolve();await release.promise;finished.resolve();throw new Error('late-private-error');}};
  const configured=copy(template);configured.limits.deadline_ms=termination==='deadline'?30:1000;
  const target=tool(engine,{template:configured}),controller=new AbortController();
  const invocation=target.invoke(copy(args),{signal:controller.signal});
  try {
    await entered.promise;if(termination==='abort')controller.abort();
    await assert.rejects(invocation,error=>termination==='abort'?error?.name==='AbortError':error instanceof DeadlineExceeded);
  } finally {release.resolve();await finished.promise;await turn();await Promise.allSettled([invocation]);}
});

test('alternate SDK paths cannot release uncounted content',async()=>{
  const engine=new Engine(),target=tool(engine);
  for(const name of ['_call','func','batch','stream','streamEvents','streamLog','transform','_streamIterator','_streamLog','_transformStreamWithConfig']) {
    if(typeof target[name]!=='function') continue;
    await assert.rejects(async()=>{
      const output=target[name](copy(args));
      if(output&&typeof output[Symbol.asyncIterator]==='function'){for await(const _ of output){}return;}
      await output;
    },UnsupportedCapability);
  }
  await assert.rejects(target.invoke(copy(args),{},'extra'),InvalidRequest);
  assert.equal(engine.calls.length,0);
});

test('enabled ambient tracing is disabled inside adapter without network or secret output',async t=>{
  const secret='AD-r1-tracing-credential-canary',attempts=[],logs=[];
  const keys=['LANGSMITH_TRACING','LANGCHAIN_TRACING_V2','LANGCHAIN_TRACING','LANGCHAIN_VERBOSE','LANGSMITH_API_KEY','LANGCHAIN_API_KEY'];
  const before=Object.fromEntries(keys.map(key=>[key,process.env[key]]));
  const deny=()=>{attempts.push('network');throw new Error('network denied');};
  for(const key of keys)process.env[key]=key.endsWith('API_KEY')?secret:'true';
  t.mock.method(globalThis,'fetch',deny);t.mock.method(net.Socket.prototype,'connect',deny);t.mock.method(dns,'lookup',deny);
  t.mock.method(console,'warn',(...values)=>logs.push(values));t.mock.method(console,'error',(...values)=>logs.push(values));
  const outer=new RunTree({name:'outer-host-application',run_type:'chain',tracingEnabled:true,inputs:{secret}});
  const engine={async retrieve(request){const current=getCurrentRunTree(true);assert.ok(!current||current.tracingEnabled===false);assert.notEqual(current,outer);return {result:result(request.request_id)};}};
  try {
    await withRunTree(outer,async()=>{
      assert.equal(getCurrentRunTree(),outer);
      const output=await tool(engine).invoke(native());assert.ok(!serializer(output).includes(secret));
      assert.equal(getCurrentRunTree(),outer);
    });
    assert.deepEqual(attempts,[]);assert.ok(!JSON.stringify(logs).includes(secret));
  } finally {for(const key of keys){if(before[key]===undefined)delete process.env[key];else process.env[key]=before[key];}}
});

for(const item of fixture('requests.json').cases.filter(value=>value.kind==='tool')) {
  test(`shared ToolRequest ${item.id}`,async()=>{
    const engine=new Engine(),configured=copy(template);
    if(typeof item.input.collection==='string'&&item.input.collection&&!item.input.collection.includes('\0'))configured.collection=item.input.collection;
    const target=tool(engine,{template:configured});
    if(item.valid){const output=await target.invoke(copy(item.input));assert.equal(JSON.parse(output).request_id,item.input.request_id);assert.equal(engine.calls.length,1);}
    else {await assert.rejects(target.invoke(copy(item.input)),InvalidRequest);assert.equal(engine.calls.length,0);}
  });
}

for(const item of fixture('results.json').cases.filter(value=>value.kind==='result'&&value.valid)) {
  test(`shared complete result ${item.id}`,async()=>{
    const expected=parse_result(copy(item.input)),collection=expected.evidence[0]?.collection??'collection';
    const configured=copy(template);configured.collection=collection;configured.limits.max_context_tokens=1000000;
    const engine={async retrieve(){return {result:copy(item.input),diagnostics:{private_canary:'not_model_content'}};}};
    const target=tool(engine,{template:configured}),input={request_id:expected.request_id,query:'shared engine fixture',collection};
    const plain=await target.invoke(input),message=await target.invoke(native(input,'shared-fixture-call'));
    assert.deepEqual(JSON.parse(plain),expected);assert.deepEqual(JSON.parse(message.content),expected);
    assert.ok(message instanceof ToolMessage);assert.ok(!plain.includes('not_model_content'));
  });
}

test('actual shared corrective targeted recovery matches direct engine with fixed constraints',async()=>{
  const data=fixture('corrective.json'),item=data.cases.find(row=>row.id==='targeted-recovery');
  const request=parse_request(data.request),trusted=parse_scope(data.scope);
  function backend(){const searches=[],captures=[];return {searches,captures,
    async search(attempt,options){searches.push(copy(attempt));assert.deepEqual(options.scope,trusted);
      const {query,...fixed}=attempt;const {query:_,...original}=request;assert.deepEqual(fixed,original);
      return {candidates:item.searches[searches.length-1].ids.map(key=>copy(data.rows[key].candidate)),degraded:false};},
    async capture(candidates,options){assert.deepEqual(options.request,request);assert.deepEqual(options.scope,trusted);
      const keys=candidates.map(row=>row.document_id);captures.push(keys);const rows=keys.map(key=>data.rows[key]);
      const source_bytes=rows.reduce((sum,row)=>sum+Buffer.byteLength(row.source.text),0);assert.ok(source_bytes<=options.max_source_bytes);
      return {evidence:rows.map(row=>copy(row.evidence)),sources:rows.map(row=>copy(row.source)),source_bytes,stale:false,budget_exhausted:false};}};}
  const make=store=>new CorrectiveRetriever({backend:store,policy:data.policy,
    variants:[{facet_id:'second',variant_id:'v',query:item.queries[0]}],planner:new PlannerAdapter({cost_upper_usd:0,
      transport:async payload=>{assert.equal(payload.query,request.query);assert.deepEqual(payload.missing_facets,['second']);return {plan:{queries:[{facet_id:'second',variant_id:'v'}]},usage:{input_tokens:0,output_tokens:0,cost_usd:0}};}})});
  const directStore=backend(),direct=await make(directStore).retrieve(request,{scope:trusted,deadline:performance.now()/1000+2});
  const store=backend(),configured=Object.fromEntries(Object.entries(data.request).filter(([key])=>['collection','required_filters','limits','output_profile'].includes(key)));
  const target=create_tool({engine:make(store),template:configured,scope:data.scope,final_serializer:serializer});
  const input=Object.fromEntries(Object.entries(data.request).filter(([key])=>['schema_version','request_id','query','collection','search_hints'].includes(key)));
  const message=await target.invoke(native(input,'corrective-fixture-call'));
  assert.ok(message instanceof ToolMessage);assert.deepEqual(JSON.parse(message.content),direct.result);
  assert.equal(direct.result.status,'sufficient');assert.equal(direct.diagnostics.queries_executed,2);
  assert.deepEqual(direct.result.evidence.map(row=>row.document_id),['a','b']);
  assert.deepEqual(store.searches,directStore.searches);assert.deepEqual(store.captures,directStore.captures);
  assert.ok(!('diagnostics' in JSON.parse(message.content)));
});

for(const [name,override] of [
  ['missing-serializer',{final_serializer:undefined}],['scope-in-template',{template:{...copy(template),scope}}],
  ['query-in-template',{template:{...copy(template),query:'forged'}}],['invalid-scope',{scope:{...scope,unknown:'secret'}}],
  ['invalid-counter-profile',{template:strictTemplate(),counter:{}}],
]) test(`trusted configuration rejects ${name}`,async()=>{
  const engine=new Engine();
  await assert.rejects(async()=>{const target=tool(engine,override);await target.invoke(copy(args));},
    name==='invalid-counter-profile'?UnsupportedCapability:InvalidRequest);
  assert.equal(engine.calls.length,0);
});

test('accessor-bearing input and configuration are rejected without evaluating getters',async()=>{
  const engine=new Engine(),target=tool(engine);let getters=0;
  const input={...args};Object.defineProperty(input,'query',{enumerable:true,get(){getters++;throw new Error('private-getter-secret');}});
  await assert.rejects(target.invoke(input),InvalidRequest);
  const config={};Object.defineProperty(config,'signal',{enumerable:true,get(){getters++;throw new Error('private-getter-secret');}});
  await assert.rejects(target.invoke(copy(args),config),InvalidRequest);
  assert.equal(getters,0);assert.equal(engine.calls.length,0);
});

test('explicit typed serializer failure preserves its type',async()=>{
  await assert.rejects(tool(new Engine(),{final_serializer:()=>{throw new IntegrityViolation();}}).invoke(copy(args)),IntegrityViolation);
});

test('real SDK model-facing tool conversion exposes only narrow input schema',()=>{
  const target=tool(),converted=convertToOpenAITool(target);
  assert.equal(converted.type,'function');assert.equal(converted.function.name,'cragkit_retrieve');
  const parameters=converted.function.parameters;
  assert.deepEqual(Object.keys(parameters.properties).sort(),['schema_version','request_id','query','collection','search_hints'].sort());
  assert.equal(parameters.additionalProperties,false);
  for(const forbidden of ['scope','tenant_id','required_filters','limits','output_profile','callbacks','config']) assert.ok(!(forbidden in parameters.properties));
});

test('engine AbortError name cannot bypass redaction without external cancellation',async()=>{
  const secret='private-abort-shaped-engine-canary';
  const engine={async retrieve(){const error=new Error(secret);error.name='AbortError';throw error;}};
  await assert.rejects(tool(engine).invoke(copy(args)),error=>
    error instanceof ProviderUnavailable&&!error.message.includes(secret));
});

test('actual external cancellation preserves the original abort reason',async()=>{
  const entered=gate(),release=gate(),controller=new AbortController();
  const reason=new Error('caller-owned-cancellation-reason');
  const engine={async retrieve(request){entered.resolve();await release.promise;return {result:result(request.request_id)};}};
  const invocation=tool(engine).invoke(copy(args),{signal:controller.signal});
  try {
    await entered.promise;controller.abort(reason);
    await assert.rejects(invocation,error=>error===reason);
  } finally {release.resolve();await Promise.allSettled([invocation]);await turn();}
});

test('closing a bound strict counter fails before engine or provider work',async()=>{
  const counter=await Cl100kCounter.create(tokenizer),engine=new Engine();
  try {
    const target=tool(engine,{template:strictTemplate(),counter});
    counter.close();
    await assert.rejects(target.invoke(copy(args)),UnsupportedCapability);
    assert.equal(engine.calls.length,0);
  } finally {counter.close();}
});
