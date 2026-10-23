/** Native read-only dense fixture; restricted credentials and fixed local owner actions. */
import {readFileSync,lstatSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {PoolResource,parse_pool_config,now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresSession} from '../packages/typescript/dist/postgres-session.js';
import {FAKE_PROFILE} from '../packages/typescript/dist/embeddings.js';
import {parse_request,parse_scope} from '../packages/typescript/dist/contracts.js';
import {UnsupportedCapability} from '../packages/typescript/dist/errors.js';
import {verifyNeonResource} from './check_typescript_postgres.mjs';

class CheckError extends Error {}
function requireCheck(value,code){if(!value)throw new CheckError(code);}
function privateJSON(path){
  const info=lstatSync(path);
  requireCheck(info.isFile()&&info.uid===process.getuid()&&(info.mode&0o077)===0,'private_file_permissions');
  return JSON.parse(readFileSync(path,'utf8'));
}
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
const replies=input[Symbol.asyncIterator]();
async function owner(action,enabled){
  process.stdout.write(JSON.stringify({type:'owner',action,enabled})+'\n');
  const reply=await replies.next();
  requireCheck(!reply.done&&JSON.parse(reply.value).ok===true,'owner_reply');
}
async function run(config,fixture){
  const resource=new PoolResource(parse_pool_config({...config,max_size:1}));
  if(fixture.neon)verifyNeonResource(resource,config.host);
  const {shared,receipts}=fixture, scopes=fixture.scopes.map(parse_scope), checks=[];
  const batch=coordinates=>({profile:FAKE_PROFILE,vectors:[[...coordinates,...Array(shared.dimension-coordinates.length).fill(0)]],
    usage:{prompt_tokens:0,total_tokens:0,cost_usd:0,cost_kind:'known'},provider_calls:1,synthetic:true});
  const request=(entry,changes={})=>parse_request({query:'alpha',collection:fixture.collection,
    required_filters:entry?.filters??[],...changes});
  const session=new PostgresSession(resource);
  const read=(entry,{scope=scopes[0],candidate,parsed}={})=>session.transaction(parsed??request(entry),{scope,deadline:now()+12},
    async handle=>candidate?handle.fetch_evidence(candidate,{max_source_bytes:1048576}):handle.dense_candidates(batch(entry?.coordinates??[1,0]),{limit:entry?.limit??100}));
  const normalized=values=>values.map(item=>[item.document_id,item.generation_id,item.chunk_id,item.score]);
  try{
    await resource.open();
    for(const entry of shared.cases){
      const candidates=await read(entry);
      requireCheck(candidates.length===entry.expected.length,'dense_case_count');
      candidates.forEach((item,index)=>{
        const expected=entry.expected[index];
        requireCheck(item.document_id===expected[0]&&Math.abs(item.score-expected[1])<=shared.tolerance,'dense_case_order');
        requireCheck(item.tenant_id===scopes[0].tenant_id&&item.collection===fixture.collection
          &&item.embedding_profile===FAKE_PROFILE.profile_id&&item.score_direction==='lower_is_better'
          &&item.score_kind==='cosine_distance','dense_scope_metadata');
      });
    }
    checks.push('node_exact_distance_order_ties_filters_before_limit_and_staging_legacy_exclusion');
    requireCheck((await read(undefined,{parsed:request(undefined,{limits:{max_candidates:1}})})).length===1,'request_candidate_limit');
    requireCheck((await read(undefined,{scope:parse_scope({...scopes[0],principal_id:'not-authorized'})})).length===0,'same_tenant_principal_leak');
    let missingCollection=false;
    try{await read(undefined,{parsed:request(undefined,{collection:fixture.collection+'-other'})});}
    catch(error){missingCollection=error instanceof UnsupportedCapability;}
    requireCheck(missingCollection,'missing_collection_accepted');
    const grantScope=parse_scope({...scopes[0],principal_id:'grant-only',grant_ids:['dense-reader']});
    const grantRows=await read(undefined,{scope:grantScope});
    requireCheck(grantRows.length===1&&grantRows[0].document_id==='dense-c','grant_only_scope');
    requireCheck((await read(undefined,{scope:grantScope,candidate:grantRows[0]})).state==='verified','grant_only_source');
    const wrongGrant=parse_scope({...grantScope,grant_ids:['wrong-grant']});
    requireCheck((await read(undefined,{scope:wrongGrant})).length===0,'wrong_grant_leak');
    requireCheck((await read(undefined,{scope:wrongGrant,candidate:grantRows[0]})).state==='unavailable','wrong_grant_source');
    const other=await read(undefined,{scope:scopes[1]});
    requireCheck(other.length===1&&other[0].tenant_id===scopes[1].tenant_id&&other[0].generation_id===receipts.other.generation_id,'tenant_collision');
    checks.push('node_tenant_collection_principal_and_request_limits');
    const candidate=(await read())[0], source=await read(undefined,{candidate});
    requireCheck(source.state==='verified'&&source.evidence.text===shared.documents[0].source,'dense_exact_source');
    for(const action of ['revoke','tombstone']){
      await owner(action,true);
      try{
        requireCheck((await read()).every(item=>item.document_id!=='dense-a'),'denied_dense_candidate');
        requireCheck((await read(undefined,{candidate})).state==='unavailable','denied_dense_source');
      }finally{await owner(action,false);}
    }
    checks.push('node_dense_source_fidelity_and_revocation_tombstone_denial');
    await owner('hide_profile',true);
    try{
      let denied=false;
      try{await read();}catch(error){denied=error instanceof UnsupportedCapability;}
      requireCheck(denied,'unavailable_profile_accepted');
      await session.transaction(request(),{scope:scopes[0],deadline:now()+12},async handle=>requireCheck((await handle.lexical_candidates()).length>0,'missing_profile_broke_lexical'));
    }finally{await owner('hide_profile',false);}
    checks.push('node_missing_profile_typed_failure_keeps_lexical_available');
    let before;
    try{
      await session.transaction(request(),{scope:scopes[0],deadline:now()+12},async handle=>{
        before=await handle.dense_candidates(batch([1,0]));
        const lexicalBefore=await handle.lexical_candidates();
        requireCheck(lexicalBefore.length>0,'same_snapshot_lexical_empty');
        await owner('advance',true);
        const after=await handle.dense_candidates(batch([1,0]));
        requireCheck(JSON.stringify(normalized(before))===JSON.stringify(normalized(after)),'dense_snapshot_changed');
        requireCheck(JSON.stringify(normalized(await handle.lexical_candidates()))===JSON.stringify(normalized(lexicalBefore)),'lexical_snapshot_changed');
      });
      const historical=await read(undefined,{candidate:before[0]});
      requireCheck(historical.state==='verified'&&historical.stale&&historical.evidence.text===shared.documents[0].source,'dense_retained_source');
    }finally{await owner('advance',false);}
    checks.push('node_dense_and_lexical_repeatable_snapshot_retained_source');
    return {checks};
  }finally{await resource.close();}
}
if(process.argv[2]!=='--allow-dense-checks')throw new Error('Explicit fixture authorization required.');
try{process.stdout.write(JSON.stringify({type:'result',...await run(privateJSON(process.argv[3]),privateJSON(process.argv[4]))})+'\n');}
catch(error){
  process.stdout.write(JSON.stringify({type:'error',code:error instanceof CheckError?error.message:'native_dense_check_failed'})+'\n');
  process.exitCode=1;
}finally{input.close();}
