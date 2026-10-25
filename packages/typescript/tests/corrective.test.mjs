import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { CorrectiveRetriever } from '../dist/corrective.js';
import { BudgetExhausted } from '../dist/execution.js';
import { PlannerAdapter } from '../dist/planning.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from '../dist/errors.js';
const hash=text=>createHash('sha256').update(text).digest('hex');
const scope={tenant_id:'tenant',principal_id:'reader',authorization_revision:'acl1',grant_ids:['read']};
const query='Explain API-42';
const request=extra=>({request_id:'request',query,collection:'docs',required_filters:[{op:'eq',field:'tag',value:'allowed'}],output_profile:{renderer:'cragkit.context.v2'},...extra});
const options=extra=>({scope,deadline:performance.now()/1000+2,...extra});
const candidate=(id,text)=>({tenant_id:'tenant',collection:'docs',document_id:id,revision_id:'r1',generation_id:'g1',chunk_id:id,start_byte:0,end_byte:Buffer.byteLength(text),text_sha256:hash(text),score:1});
const source=(id,text)=>({collection:'docs',document_id:id,revision_id:'r1',source_sha256:hash(text),text});
const evidence=(id,text)=>({evidence_id:id,collection:'docs',document_id:id,revision_id:'r1',chunk_id:id,source_locator:'source:'+id,start_byte:0,end_byte:Buffer.byteLength(text),text,source_sha256:hash(text),text_sha256:hash(text)});
const first='Retry three times.',second='Wait ten seconds.';
const anchor=(id,text)=>({claim_id:id,collection:'docs',document_id:id,revision_id:'r1',source_sha256:hash(text),start_byte:0,end_byte:Buffer.byteLength(text),text});
const policy={policy_id:'curated',version:'1',query_sha256:hash(query),facets:[
  {facet_id:'retry',question:'Retry count?',required:true,absence:'missing',anchors:[anchor('a',first)]},
  {facet_id:'delay',question:'Delay?',required:true,absence:'missing',anchors:[anchor('b',second)]}]};
const variants=[{facet_id:'delay',variant_id:'delay-v1',query:'API-42 delay?'}];
const planner=()=>new PlannerAdapter({transport:async()=>({plan:{queries:[{facet_id:'delay',variant_id:'delay-v1'}]},usage:{input_tokens:null,output_tokens:null,cost_usd:null}})});
function backend({both=false,afterCapture}={}){
  const searches=[],captures=[];
  return {searches,captures,
    async search(r,o){searches.push({r,o});assert.deepEqual(r.required_filters,request().required_filters);assert.deepEqual(o.scope,scope);
      return {candidates:both?[candidate('a',first),candidate('b',second)]:[candidate(searches.length===1?'a':'b',searches.length===1?first:second)],degraded:false};},
    async capture(refs,o){captures.push({refs,o});const items=refs.map(c=>[c.document_id,c.document_id==='a'?first:second]);
      const value={evidence:items.map(([id,text])=>evidence(id,text)),sources:items.map(([id,text])=>source(id,text)),source_bytes:items.reduce((n,[,text])=>n+Buffer.byteLength(text),0),stale:false,budget_exhausted:false};
      return afterCapture?afterCapture(value,captures.length):value;}};
}

test('targeted recovery freshly captures retained candidates and assesses original question',async()=>{
  const b=backend();const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:planner(),batch_size:2}).retrieve(request(),options());
  assert.equal(r.result.status,'sufficient');assert.equal(r.diagnostics.stop_reason,'sufficient');
  assert.equal(r.diagnostics.queries_executed,2);assert.equal(r.diagnostics.candidate_work,4);
  assert.equal(b.captures.length,3);assert.equal(b.captures[2].refs.length,2);
  assert.equal(b.searches[1].r.query,variants[0].query);assert.equal(b.captures[2].o.request.query,query);
  assert.equal(r.result.request_id,'request');assert.equal(r.result.versions.policy,'curated:1');
  assert.equal(r.result.usage.provider_calls,1);assert.equal(r.result.usage.cost_usd,null);
  assert.equal(r.result.context,JSON.stringify(r.result.evidence));assert.ok(Object.isFrozen(r.result));
});

test('initial sufficient assessment avoids planner and corrected search',async()=>{
  const b=backend({both:true});let calls=0;
  const p=new PlannerAdapter({transport:async()=>{calls++;throw new Error('must not run');}});
  const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:p}).retrieve(request(),options());
  assert.equal(r.result.status,'sufficient');assert.equal(b.searches.length,1);assert.equal(calls,0);
});

test('no plan and unassessed coverage remain explicit',async()=>{
  const a=await new CorrectiveRetriever({backend:backend(),policy}).retrieve(request(),options());
  assert.equal(a.diagnostics.stop_reason,'no_plan');assert.equal(a.result.status,'partial');
  const b=await new CorrectiveRetriever({backend:backend()}).retrieve(request(),options());
  assert.equal(b.diagnostics.stop_reason,'coverage_unknown');assert.equal(b.result.status,'partial');
});

test('fresh capture prevents returning evidence revoked during correction',async()=>{
  const b=backend({afterCapture:(v,n)=>n===1?v:{...v,evidence:v.evidence.filter(e=>e.document_id!=='a'),sources:v.sources.filter(s=>s.document_id!=='a'),stale:true}});
  const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:planner()}).retrieve(request(),options());
  assert.equal(r.result.status,'partial');assert.equal(r.diagnostics.stop_reason,'plan_complete');assert.ok(r.result.evidence.every(e=>e.document_id!=='a'));assert.ok(r.result.limitations.some(l=>l.code==='stale_evidence'));
});

test('candidate work exhaustion stops before planning with the latest fresh evidence',async()=>{
  const b=backend({afterCapture:(v,n)=>n===1?v:{...v,evidence:[],sources:[],stale:true}});
  const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:planner(),batch_size:1}).retrieve(request({limits:{max_candidates:1}}),options());
  assert.equal(r.diagnostics.stop_reason,'budget_exhausted');assert.equal(b.captures.length,1);assert.equal(r.result.evidence.length,1);assert.equal(r.result.usage.provider_calls,0);
  assert.ok(r.result.limitations.some(l=>l.code==='budget_exhausted'));assert.equal(r.diagnostics.candidate_work,1);
});

test('malformed, duplicate, cross-tenant and cross-collection candidates fail closed',async()=>{
  const c=candidate('a',first);
  for(const candidates of [[{...c,score:NaN}],[c,c],[{...c,tenant_id:'other'}],[{...c,collection:'other'}],[{...c,extra:'unsafe'}]]){
    const b=backend();b.search=async()=>({candidates,degraded:false});
    await assert.rejects(new CorrectiveRetriever({backend:b}).retrieve(request(),options()),IntegrityViolation);
  }
});

test('capture membership, exact source bytes and cumulative source budget are enforced',async()=>{
  for(const change of [v=>({...v,evidence:[evidence('invented',first)]}),v=>({...v,source_bytes:0}),
    v=>({...v,sources:[{...v.sources[0],text:'corrupted'}]}),v=>({...v,source_bytes:16777217})]){
    const b=backend({afterCapture:change});await assert.rejects(new CorrectiveRetriever({backend:b}).retrieve(request(),options()),IntegrityViolation);
  }
});

test('trusted config, source policy and strict counting validate before backend work',async()=>{
  const b=backend();
  for(const r of [request({output_profile:{renderer:'cragkit.context.v1'}}),request({output_profile:{renderer:'cragkit.context.v2',counting_mode:'strict',tokenizer:'unknown'}})])
    await assert.rejects(new CorrectiveRetriever({backend:b}).retrieve(r,options()),UnsupportedCapability);
  await assert.rejects(new CorrectiveRetriever({backend:b,policy:{...policy,query_sha256:hash('other')}}).retrieve(request(),options()),InvalidRequest);
  assert.equal(b.searches.length,0);
});

test('request and configuration snapshot survives callback mutations',async()=>{
  const raw=request(),s=structuredClone(scope),p=structuredClone(policy),v=structuredClone(variants),b=backend();
  const original=b.search.bind(b);b.search=async(r,o)=>{raw.query='changed';raw.required_filters=[];s.tenant_id='other';p.facets=[];v[0].query='changed';return original(r,o);};
  const retriever=new CorrectiveRetriever({backend:b,policy:p,variants:v,planner:planner()});
  const result=await retriever.retrieve(raw,options({scope:s}));assert.equal(result.result.status,'sufficient');assert.equal(b.searches[1].r.query,variants[0].query);
});

test('shared deadline and native cancellation bound ignoring backend callbacks',async()=>{
  const b=backend();b.search=async()=>new Promise(()=>{});
  await assert.rejects(new CorrectiveRetriever({backend:b}).retrieve(request({limits:{deadline_ms:5}}),options()),DeadlineExceeded);
  const abort=new AbortController();const c=backend();c.capture=async()=>{abort.abort();return new Promise(()=>{});};
  await assert.rejects(new CorrectiveRetriever({backend:c}).retrieve(request(),options({signal:abort.signal})),{name:'AbortError'});
});

test('termination closes the ledger before an ignoring backend can dispatch late work',async()=>{
  const b=backend();let release,held;
  const gate=new Promise(resolve=>{release=resolve;});
  const finished=new Promise(resolve=>{
    b.search=async(_request,{ledger})=>{held=ledger;await gate;try{assert.throws(()=>ledger.reserve({provider_calls:1}),InvalidRequest);}finally{resolve();}return {candidates:[],degraded:false};};
  });
  await assert.rejects(new CorrectiveRetriever({backend:b}).retrieve(request({limits:{deadline_ms:5}}),options()),DeadlineExceeded);
  assert.ok(held);release();await finished;
});

const selectedPlanner=items=>new PlannerAdapter({transport:async()=>({plan:{queries:items.map(({facet_id,variant_id})=>({facet_id,variant_id}))},usage:{input_tokens:0,output_tokens:0,cost_usd:0}})});
function sequenceBackend(sequence){
  let calls=0,captures=0;const texts=new Map();
  return {get calls(){return calls;},get captures(){return captures;},
    async search(){const batch=sequence[Math.min(calls++,sequence.length-1)];for(const [id,text]of batch)texts.set(id,text);return {candidates:batch.map(([id,text])=>candidate(id,text)),degraded:false};},
    async capture(refs){captures++;const items=refs.map(c=>[c.document_id,texts.get(c.document_id)]);return {evidence:items.map(([id,text])=>evidence(id,text)),sources:items.map(([id,text])=>source(id,text)),source_bytes:items.reduce((n,[,text])=>n+Buffer.byteLength(text),0),stale:false,budget_exhausted:false};}};
}

test('ASCII query normalization prevents repeated original dispatch',async()=>{
  const repeated=[{facet_id:'delay',variant_id:'repeat',query:'  Explain\tAPI-42  '}],b=backend();
  const r=await new CorrectiveRetriever({backend:b,policy,variants:repeated,planner:selectedPlanner(repeated)}).retrieve(request(),options());
  assert.equal(r.diagnostics.stop_reason,'repeated_query');assert.equal(b.searches.length,1);assert.equal(r.diagnostics.queries_executed,1);
});

test('repeated candidate batches stop after fresh capture, including a later A/B/A cycle',async()=>{
  const selections=[...variants,{facet_id:'delay',variant_id:'delay-v2',query:'API-42 waiting delay?'}];
  const same=sequenceBackend([[['a',first]],[['a',first]]]);
  const r=await new CorrectiveRetriever({backend:same,policy,variants,planner:selectedPlanner(variants)}).retrieve(request(),options());
  assert.equal(r.diagnostics.stop_reason,'repeated_candidates');assert.equal(same.captures,3);
  const cycle=sequenceBackend([[['a',first]],[['c','Unrelated material.']],[['a',first]]]);
  const result=await new CorrectiveRetriever({backend:cycle,policy,variants:selections,planner:selectedPlanner(selections),no_progress_limit:3})
    .retrieve(request({limits:{max_attempts:4}}),options());
  assert.equal(result.diagnostics.stop_reason,'repeated_candidates');assert.equal(cycle.captures,4);
});

test('consecutive nonimproving recovery rounds honor configured no-progress limit',async()=>{
  const selections=[...variants,{facet_id:'delay',variant_id:'delay-v2',query:'API-42 waiting delay?'}];
  const b=sequenceBackend([[['a',first]],[['c','Unrelated one.']],[['d','Unrelated two.']]]);
  const r=await new CorrectiveRetriever({backend:b,policy,variants:selections,planner:selectedPlanner(selections),no_progress_limit:2}).retrieve(request(),options());
  assert.equal(r.diagnostics.stop_reason,'no_progress');assert.equal(b.calls,3);assert.equal(b.captures,4);assert.equal(r.result.status,'partial');
});

test('transient retries reserve new attempt, candidate work and provider slots without new subquery',async()=>{
  const b=backend({both:true}),original=b.search.bind(b);let calls=0;
  b.search=async(r,o)=>{
    const token=o.ledger.reserve({provider_calls:1,cost_upper_usd:0});o.ledger.dispatch(token);
    try{if(++calls===1)throw new ProviderUnavailable();o.ledger.reconcile(token,{input_tokens:0,output_tokens:0,cost_usd:0});return original(r,o);}
    catch(error){o.ledger.abandon(token);throw error;}
  };
  const r=await new CorrectiveRetriever({backend:b,policy,max_retries:1,batch_size:2,backoff_ms:1}).retrieve(request(),options());
  assert.equal(r.result.status,'sufficient');assert.equal(calls,2);assert.equal(r.result.usage.attempt_count,2);
  assert.equal(r.result.usage.provider_calls,2);assert.equal(r.result.usage.cost_usd,null);
  assert.equal(r.diagnostics.queries_executed,1);assert.equal(r.diagnostics.candidate_work,4);
});

test('permanent failures never retry and transient exhaustion remains operational',async()=>{
  for(const ErrorType of [InvalidRequest,IntegrityViolation,UnauthorizedScope]){
    const b=backend();let calls=0;b.search=async()=>{calls++;throw new ErrorType();};
    await assert.rejects(new CorrectiveRetriever({backend:b,max_retries:2}).retrieve(request(),options()),ErrorType);assert.equal(calls,1);
  }
  for(const limits of [{max_attempts:1},{max_candidates:1}]){
    const b=backend();let calls=0;b.search=async()=>{calls++;throw new ProviderUnavailable();};
    await assert.rejects(new CorrectiveRetriever({backend:b,max_retries:2,batch_size:1}).retrieve(request({limits}),options()),ProviderUnavailable);assert.equal(calls,1);
  }
  const b=backend();let calls=0;b.search=async()=>{calls++;throw new ProviderUnavailable();};
  await assert.rejects(new CorrectiveRetriever({backend:b,max_retries:1}).retrieve(request(),options()),ProviderUnavailable);assert.equal(calls,2);
});

test('backoff honors deadline and cancellation without dispatching another retry',async()=>{
  let calls=0;const b=backend();b.search=async()=>{calls++;throw new ProviderUnavailable();};
  await assert.rejects(new CorrectiveRetriever({backend:b,max_retries:2,backoff_ms:1000}).retrieve(request({limits:{deadline_ms:10}}),options()),DeadlineExceeded);assert.equal(calls,1);
  const controller=new AbortController(),c=backend();let retries=0;
  c.search=async()=>{retries++;setTimeout(()=>controller.abort(),5);throw new ProviderUnavailable();};
  await assert.rejects(new CorrectiveRetriever({backend:c,max_retries:2,backoff_ms:1000}).retrieve(request(),options({signal:controller.signal})),{name:'AbortError'});assert.equal(retries,1);
});

test('empty, fallback and repeated plans freshly reauthorize evidence after model work',async()=>{
  for(const mode of ['empty','fallback','repeat']){
    let revoked=false;const b=backend({afterCapture:v=>revoked?{...v,evidence:[],sources:[],stale:true}:v});
    const approved=mode==='repeat'?[{facet_id:'delay',variant_id:'repeat',query:'Explain API-42'}]:variants;
    const adapter=new PlannerAdapter({allow_fallback:mode==='fallback',transport:async()=>{
      revoked=true;
      if(mode==='fallback')throw new ProviderUnavailable();
      return {plan:{queries:mode==='repeat'?[{facet_id:'delay',variant_id:'repeat'}]:[]},usage:{input_tokens:1,output_tokens:1,cost_usd:0.01}};
    }});
    const r=await new CorrectiveRetriever({backend:b,policy,variants:approved,planner:adapter}).retrieve(request(),options());
    assert.equal(b.captures.length,2);assert.equal(b.searches.length,1);assert.equal(r.result.evidence.length,0);
    assert.equal(r.result.status,'insufficient');assert.ok(r.result.limitations.some(l=>l.code==='stale_evidence'));
    assert.equal(r.diagnostics.stop_reason,mode==='repeat'?'repeated_query':'no_plan');
    assert.equal(r.result.usage.provider_calls,1);assert.equal(r.result.usage.cost_usd,mode==='fallback'?null:0.01);
    assert.equal(r.diagnostics.planning_fallback,mode==='fallback');
  }
});

test('planner subclass overrides are rejected consistently with native exact types',()=>{
  class OverriddenPlanner extends PlannerAdapter{async plan(){return {queries:[],fallback:false};}}
  assert.throws(()=>new CorrectiveRetriever({backend:backend(),planner:new OverriddenPlanner({transport:async()=>({})})}),InvalidRequest);
});

test('initial capture budget refusal terminates once with empty assessed evidence',async()=>{
  const b=backend();let captures=0;b.capture=async()=>{captures++;throw new BudgetExhausted();};
  const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:planner()}).retrieve(request(),options());
  assert.equal(captures,1);assert.equal(b.searches.length,1);assert.equal(r.result.evidence.length,0);assert.equal(r.result.status,'insufficient');
  assert.equal(r.diagnostics.stop_reason,'budget_exhausted');assert.ok(r.result.limitations.some(l=>l.code==='budget_exhausted'));
  assert.equal(r.result.usage.provider_calls,0);assert.equal(r.result.usage.cost_usd,0);
});

test('post-plan capture budget refusal discards earlier evidence and retains planner charges',async()=>{
  const b=backend(),original=b.capture.bind(b);let captures=0;
  b.capture=async(refs,o)=>{if(++captures===2)throw new BudgetExhausted();return original(refs,o);};
  const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:planner()}).retrieve(request(),options());
  assert.equal(captures,2);assert.equal(b.searches.length,1);assert.equal(r.result.evidence.length,0);
  assert.equal(r.diagnostics.stop_reason,'budget_exhausted');assert.equal(r.result.usage.provider_calls,1);assert.equal(r.result.usage.cost_usd,null);
});

test('failed capture retains dispatched unknown usage and does not retry its admission',async()=>{
  const b=backend();let captures=0;
  b.capture=async(_refs,{ledger})=>{
    captures++;const sent=ledger.reserve({provider_calls:1});ledger.dispatch(sent);ledger.abandon(sent);
    ledger.reserve({provider_calls:1});throw new Error('unreachable');
  };
  const r=await new CorrectiveRetriever({backend:b,policy}).retrieve(request({limits:{max_provider_calls:1}}),options());
  assert.equal(captures,1);assert.equal(r.result.usage.provider_calls,1);assert.equal(r.result.usage.cost_usd,null);
  assert.equal(r.diagnostics.stop_reason,'budget_exhausted');assert.equal(r.result.evidence.length,0);
});

test('capture operational and permanent errors are never converted to empty budget results',async()=>{
  for(const ErrorType of [ProviderUnavailable,InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability]){
    const b=backend();let captures=0;b.capture=async()=>{captures++;throw new ErrorType();};
    await assert.rejects(new CorrectiveRetriever({backend:b,policy,max_retries:2}).retrieve(request(),options()),ErrorType);
    assert.equal(captures,1);
  }
});

test('retained candidate capacity stops before an unnecessary planner provider call',async()=>{
  const b=sequenceBackend([Array.from({length:64},(_,i)=>['c'+i,'Unrelated '+i+'.'])]);let calls=0;
  const adapter=new PlannerAdapter({transport:async()=>{calls++;throw new Error('unreachable');}});
  const r=await new CorrectiveRetriever({backend:b,policy,variants,planner:adapter,batch_size:64}).retrieve(request(),options());
  assert.equal(r.diagnostics.stop_reason,'budget_exhausted');assert.equal(calls,0);assert.equal(b.captures,1);
  assert.equal(r.diagnostics.candidate_work,64);assert.equal(r.result.usage.provider_calls,0);
});
