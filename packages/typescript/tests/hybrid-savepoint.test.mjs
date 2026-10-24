import test from 'node:test';
import assert from 'node:assert/strict';
import { PostgresSession,EXPECTED_HISTORY,_ROLE_SQL,_CATALOG_SQL,_HISTORY_SQL,_COLLECTION_SQL,CandidateCleanupFailure } from '../dist/postgres-session.js';
import { parse_request,parse_scope } from '../dist/contracts.js';
import { now } from '../dist/postgres-pool.js';
import { InvalidRequest,ProviderUnavailable } from '../dist/errors.js';
const request=parse_request({request_id:'r',query:'x',collection:'c'});
const options=()=>({deadline:now()+2,scope:parse_scope({tenant_id:'t',principal_id:'p',authorization_revision:'a',grant_ids:['g']})});
function resource(failCleanup=false) {
 const calls=[];let state='I';const client={getTransactionStatus:()=>state,release(){},async query({text}){
  calls.push(text);if(text.startsWith('BEGIN'))state='T';if(text==='ROLLBACK')state='I';
  if(failCleanup&&text.startsWith('ROLLBACK TO'))throw Error('broken');
  if(text===_ROLE_SQL||text===_CATALOG_SQL)return {rows:[[true]]};if(text===_HISTORY_SQL)return {rows:EXPECTED_HISTORY.map(v=>[...v])};if(text===_COLLECTION_SQL)return {rows:[['0.1','native_fts.v1']]};return {rows:[]};
 }};return {calls,config:{release_timeout:0.1},async withLease(o,body){return body(client,new AbortController().signal);}};
}
test('savepoint cleans failed branch before next branch and retains outer snapshot',async()=>{
 const r=resource();await new PostgresSession(r).transaction(request,options(),async handle=>{
  await assert.rejects(handle.candidate_branch(async()=>{throw new ProviderUnavailable();}),ProviderUnavailable);
  assert.equal(await handle.candidate_branch(async()=>7),7);
 });
 const controls=r.calls.filter(v=>/SAVEPOINT/.test(v));assert.deepEqual(controls,['SAVEPOINT cragkit_candidate_branch','ROLLBACK TO SAVEPOINT cragkit_candidate_branch','RELEASE SAVEPOINT cragkit_candidate_branch','SAVEPOINT cragkit_candidate_branch','RELEASE SAVEPOINT cragkit_candidate_branch']);assert.equal(r.calls.filter(v=>v.startsWith('BEGIN')).length,1);
});
test('nested and concurrent branch wrappers reject and expired handle rejects',async()=>{
 const r=resource();let expired;
 await new PostgresSession(r).transaction(request,options(),async handle=>{
  expired=handle;let release;const wait=new Promise(resolve=>{release=resolve;});
  const first=handle.candidate_branch(async()=>{await assert.rejects(handle.candidate_branch(async()=>1),InvalidRequest);await wait;});
  await assert.rejects(handle.candidate_branch(async()=>2),InvalidRequest);release();await first;
 });await assert.rejects(expired.candidate_branch(async()=>1),InvalidRequest);
});
test('cleanup failure invalidates handle and cannot be recovered as a successful later branch',async()=>{
 const r=resource(true);await new PostgresSession(r).transaction(request,options(),async handle=>{
  await assert.rejects(handle.candidate_branch(async()=>{throw new ProviderUnavailable();}),CandidateCleanupFailure);
  await assert.rejects(handle.candidate_branch(async()=>1),InvalidRequest);
 });
});
