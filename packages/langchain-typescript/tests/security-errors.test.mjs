import test from 'node:test';
import assert from 'node:assert/strict';
import { inspect } from 'node:util';
import { parse_result } from 'cragkit/contracts';
import * as errors from 'cragkit/errors';
import { create_tool } from '../dist/index.js';

const canary='SYNTHETIC_PRIVATE_ERROR_CANARY';
const args={request_id:'consumer-request',collection:'docs',query:'synthetic query'};
const scope={tenant_id:'tenant',principal_id:'principal',authorization_revision:'1',grant_ids:['read']};
const template={collection:'docs',limits:{max_context_tokens:20000},output_profile:{envelope_reserve_tokens:17}};

const kinds=['InvalidRequest','UnauthorizedScope','UnsupportedCapability','IndexNotReady','EmbeddingProfileMismatch',
  'ProviderUnavailable','DeadlineExceeded','ContextBudgetTooSmall','IntegrityViolation'];
for(const name of kinds)for(const boundary of ['engine','serializer'])for(const subclass of [false,true])
test(`LangChain ${boundary} ${name}, subclass=${subclass}, keeps only safe classification`,async()=>{
  const Kind=errors[name];let constructions=0;
  class ProviderError extends Kind{constructor(){super();constructions++;}}
  const original=Object.assign(subclass?new ProviderError():new Kind(),{code:canary,message:canary,cause:new Error(canary),private_detail:canary});
  const tool=create_tool({engine:{async retrieve(){
    if(boundary==='engine')throw original;
    return {result:parse_result({request_id:args.request_id,status:'insufficient',context:'[]'})};
  }},template,scope,final_serializer:boundary==='serializer'?()=>{throw original;}:actual=>JSON.stringify(actual)});
  await assert.rejects(tool.invoke(args),error=>{
    assert.ok(error instanceof Kind);assert.notEqual(error,original);
    assert.equal(Object.getPrototypeOf(error),Kind.prototype);
    assert.equal(error.code,new Kind().code);
    assert.equal(error.message,new Kind().message);
    assert.ok(!inspect(error,{depth:5}).includes(canary));assert.ok(!JSON.stringify(error).includes(canary));
    return true;
  });
  assert.equal(constructions,subclass?1:0);
});

for(const boundary of ['engine','serializer'])test(`LangChain ${boundary} unknown declared code uses a fresh boundary-specific failure`,async()=>{
  const original=new errors.CragkitError('not_a_declared_code',canary,false);
  const tool=create_tool({engine:{async retrieve(){
    if(boundary==='engine')throw original;
    return {result:parse_result({request_id:args.request_id,status:'insufficient',context:'[]'})};
  }},template,scope,final_serializer:boundary==='serializer'?()=>{throw original;}:actual=>JSON.stringify(actual)});
  const Kind=boundary==='engine'?errors.ProviderUnavailable:errors.InvalidRequest;
  await assert.rejects(tool.invoke(args),error=>{
    assert.equal(Object.getPrototypeOf(error),Kind.prototype);assert.notEqual(error,original);
    assert.ok(!inspect(error,{depth:5}).includes(canary));return true;
  });
});
