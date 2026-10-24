/** Native synthetic child: restricted credentials only; owner RPC has a fixed allowlist. */
import { readFileSync, lstatSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { PoolResource, parse_pool_config, now } from '../packages/typescript/dist/postgres-pool.js';
import { PostgresVectorIndexer } from '../packages/typescript/dist/vector-ingestion.js';
import { canonicalize } from '../packages/typescript/dist/canonical.js';
import { PostgresIndexer, write_transaction, query } from '../packages/typescript/dist/ingestion.js';
import { PostgresSession, _SCOPE_SQL } from '../packages/typescript/dist/postgres-session.js';
import { EmbeddingAdapter } from '../packages/typescript/dist/embeddings.js';
import { parse_scope, parse_request } from '../packages/typescript/dist/contracts.js';
import { ProviderUnavailable, EmbeddingProfileMismatch, InvalidRequest, IntegrityViolation, IndexNotReady, UnauthorizedScope, UnsupportedCapability } from '../packages/typescript/dist/errors.js';
import { verifyNeonResource } from './check_typescript_postgres.mjs';

class CheckError extends Error {}
function requireCheck(value, code) { if (!value) throw new CheckError(code); }
function privateJSON(path) {
  const info=lstatSync(path);
  requireCheck(info.isFile()&&info.uid===process.getuid()&&(info.mode&0o077)===0,'private_file_permissions');
  return JSON.parse(readFileSync(path,'utf8'));
}
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
const replies=input[Symbol.asyncIterator]();
async function owner(action, enabled, privilege) {
  process.stdout.write(JSON.stringify({type:'owner',action,enabled,privilege})+'\n');
  const reply=await replies.next();
  requireCheck(!reply.done&&JSON.parse(reply.value).ok===true,'owner_reply');
}
async function run(config, fixture) {
  const resource=new PoolResource(parse_pool_config({...config,max_size:1}));
  if(fixture.neon)verifyNeonResource(resource,config.host);
  const scopes=fixture.scopes.map(parse_scope), shared=fixture.shared;
  const checks=[], state={calls:0,fail_at:null,wrong_model:false};
  const authorize=async(scope,collection,document)=>scopes.some(value=>JSON.stringify(value)===JSON.stringify(scope))
    &&collection===fixture.collection&&['vector-shared','vector-node','node-identifier-lexical','node-identifier-vector'].includes(document);
  const transport=async(body, options)=>{
    state.calls++;
    const status=await resource.withLease({deadline:Math.min(options.deadline,now()+3)},async client=>client.getTransactionStatus());
    requireCheck(status==='I','provider_inside_transaction');
    if(state.calls===state.fail_at)throw new Error('synthetic provider failure');
    const value=JSON.parse(Buffer.from(body).toString('utf8'));
    return Buffer.from(JSON.stringify({model:state.wrong_model?'other-model':value.model,
      data:value.input.map((_,index)=>({index,embedding:[1,...Array(1535).fill(0)]}))}));
  };
  const embedder=new EmbeddingAdapter(transport,{name:'fake-byte-v1',count:text=>Buffer.byteLength(text)}, {limits:{max_items:1}});
  const vector=new PostgresVectorIndexer(resource,authorize,embedder);
  const lexical=new PostgresIndexer(resource,authorize);
  const options=(intent,changes={})=>({collection:fixture.collection,document_id:'vector-node',intent_id:intent,
    source_locator:'synthetic:vector-generations',scope:scopes[0],metadata:shared.metadata,
    canonical_options:shared.canonical_options,deadline:now()+25,...changes});
  const scoped=async(text,values=[],scope=scopes[0])=>write_transaction(resource,{deadline:now()+12},async(client,opts)=>{
    await query(client,_SCOPE_SQL,[scope.tenant_id,scope.principal_id,scope.authorization_revision,JSON.stringify(scope.grant_ids)],opts);
    return query(client,text,values,opts);
  });
  const key=[scopes[0].tenant_id,fixture.collection,'vector-node'];
  const pointer=async()=> (await scoped('SELECT active_generation_id FROM cragkit.documents WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3',key))[0]?.[0]??null;
  async function read(scope=scopes[0], candidate) {
    await owner('read');
    try {
      const session=new PostgresSession(resource), request=parse_request({query:'alpha',collection:fixture.collection});
      return await session.transaction(request,{scope,deadline:now()+12},async handle=>{
        if(candidate)return handle.fetch_evidence(candidate,{max_source_bytes:1048576});
        return handle.lexical_candidates({limit:16});
      });
    } finally {await owner('write');}
  }
  const identity=receipt=>[receipt.tenant_id,receipt.collection,receipt.document_id,receipt.intent_id,receipt.revision_id,
    receipt.generation_id,receipt.payload_sha256,receipt.canonical_sha256,receipt.chunk_count,receipt.embedding_profile];
  const normalized=candidates=>candidates.filter(c=>c.document_id==='vector-node').map(c=>[c.generation_id,c.chunk_id,c.start_byte,c.end_byte]);
  async function unchanged(expected,prior){requireCheck(await pointer()===expected,'failed_rebuild_pointer');requireCheck(JSON.stringify(normalized(await read()))===JSON.stringify(prior),'failed_rebuild_lexical');}
  try {
    await resource.open();
    // IF-r1: prove both Node writers populate the existing exact-token array.
    for(const [writer,document_id,intent_id] of [[lexical,'node-identifier-lexical','node-identifiers-lex'],[vector,'node-identifier-vector','node-identifiers-vec']]){
      const receipt=await writer.ingest('ERR_CONN-42',options(intent_id,{document_id}));
      const rows=await scoped('SELECT array_to_json(identifier_tokens) FROM cragkit.chunk_lexical WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4',[...key.slice(0,2),document_id,receipt.generation_id]);
      requireCheck(rows.length===1&&JSON.stringify(rows[0][0])===JSON.stringify(['ERR_CONN-42']),'node_writer_identifier_tokens');
    }
    checks.push('node_lexical_and_vector_writers_store_exact_identifier_arrays');
    for(const privilege of ['CREATE','UPDATE']) {
      const beforeCalls=state.calls;
      await owner('unsafe_vector',true,privilege);
      try {
        try {await vector.stage('alpha unsafe role',options('node-unsafe-'+privilege.toLowerCase()));throw new CheckError('unsafe_vector_role_accepted');}
        catch(error){requireCheck(error instanceof UnsupportedCapability,'unsafe_vector_role_error');}
        requireCheck(state.calls===beforeCalls,'unsafe_vector_role_called_provider');
        requireCheck(await pointer()===null,'unsafe_vector_role_changed_pointer');
        const documents=await scoped('SELECT count(*)::int FROM cragkit.documents WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3',key);
        requireCheck(documents[0]?.[0]===0,'unsafe_vector_role_created_document');
      } finally {await owner('unsafe_vector',false,privilege);}
    }
    checks.push('vector_schema_create_and_ledger_update_roles_rejected_before_provider_or_writes');
    const python=await vector.stage(shared.replacement_source,options('vector-build',{document_id:'vector-shared',expected_generation_id:fixture.python_expected}));
    requireCheck(python.replayed&&python.provider_calls===0&&JSON.stringify(identity(python))===JSON.stringify(identity(fixture.python_receipt)),'python_node_intent_identity_parity');
    checks.push('python_write_node_replay_profile_and_identity_parity');
    const baseline=await lexical.ingest(shared.baseline_source,options('node-baseline'));
    const original=normalized(await read());
    requireCheck(original.length>0,'baseline_lexical');
    const beforeProfileCalls=state.calls;
    await owner('hide_profile',true);
    try {
      try {await vector.stage('alpha unavailable profile',options('node-missing-profile',{expected_generation_id:baseline.generation_id}));throw new CheckError('missing_profile_accepted');}
      catch(error){requireCheck(error instanceof UnsupportedCapability,'missing_profile_error');}
      requireCheck(state.calls===beforeProfileCalls,'missing_profile_called_provider');
      await unchanged(baseline.generation_id,original);
    } finally {await owner('hide_profile',false);}
    checks.push('unavailable_profile_rejected_before_provider_preserves_prior_result');
    state.fail_at=state.calls+2;
    let caught=false;
    try {await vector.stage(shared.replacement_source,options('node-build',{expected_generation_id:baseline.generation_id}));}
    catch(error){caught=error instanceof ProviderUnavailable;}
    requireCheck(caught,'interrupted_stage');
    await unchanged(baseline.generation_id,original);
    checks.push('interrupted_stage_preserves_exact_pointer_and_native_lexical');
    if(!fixture.stage_only){
      try {await vector.publish(shared.replacement_source,options('node-build',{expected_generation_id:baseline.generation_id}));throw new CheckError('incomplete_accepted');}
      catch(error){requireCheck(error instanceof IntegrityViolation,'incomplete_error');}
      await unchanged(baseline.generation_id,original);
      checks.push('incomplete_vectors_preserve_exact_pointer_and_lexical');
    }
    state.fail_at=null;
    const staged=await vector.stage(shared.replacement_source,options('node-build',{expected_generation_id:baseline.generation_id}));
    requireCheck(staged.provider_calls===staged.chunk_count-1,'missing_only_resume');
    await unchanged(baseline.generation_id,original);
    const replay=await vector.stage(shared.replacement_source,options('node-build',{expected_generation_id:baseline.generation_id}));
    requireCheck(replay.provider_calls===0&&replay.generation_id===staged.generation_id,'staged_replay');
    try {await vector.stage(shared.replacement_source+'changed',options('node-build',{expected_generation_id:baseline.generation_id}));throw new CheckError('changed_accepted');}
    catch(error){requireCheck(error instanceof InvalidRequest,'changed_error');}
    await unchanged(baseline.generation_id,original);
    checks.push('bounded_missing_only_resume_staging_invisible_and_payload_conflict');
    state.wrong_model=true;
    try {await vector.stage('alpha wrong model',options('node-model',{expected_generation_id:baseline.generation_id}));throw new CheckError('model_accepted');}
    catch(error){requireCheck(error instanceof EmbeddingProfileMismatch,'model_error');}
    finally {state.wrong_model=false;}
    await unchanged(baseline.generation_id,original);
    const other=await vector.stage(shared.replacement_source,options('node-build',{scope:scopes[1]}));
    requireCheck(other.tenant_id!==staged.tenant_id&&other.generation_id!==staged.generation_id,'tenant_collision');
    checks.push('wrong_model_same_dimension_and_colliding_tenants_isolated');
    if(fixture.stage_only)return {checks,phase:'stage',receipt:staged};
    const pub=changes=>options('node-build',{expected_generation_id:baseline.generation_id,...changes});
    const sentinel=new Error('synthetic interruption');
    try {await vector.publish(shared.replacement_source,pub({before_publish:async()=>{throw sentinel;}}));throw new CheckError('hook_accepted');}
    catch(error){requireCheck(error===sentinel,'hook_identity');}
    await unchanged(baseline.generation_id,original);
    checks.push('publication_hook_rolls_back_exact_pointer_and_lexical');
    await scoped("UPDATE cragkit.index_generations SET lexical_profile='mixed.v1' WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4",[...key,staged.generation_id]);
    try {
      try {await vector.publish(shared.replacement_source,pub());throw new CheckError('mixed_accepted');}
      catch(error){requireCheck(error instanceof IntegrityViolation,'mixed_error');}
      await unchanged(baseline.generation_id,original);
    } finally {await scoped("UPDATE cragkit.index_generations SET lexical_profile='native_fts.v1' WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4",[...key,staged.generation_id]);}
    const priorJob=await scoped('SELECT state,attempt_count FROM cragkit.ingestion_jobs WHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3',[...key.slice(0,2),'node-build']);
    await owner('deny_ready',true);
    try {
      try {await vector.publish(shared.replacement_source,pub());throw new CheckError('denied_ready_accepted');}
      catch(error){requireCheck(error instanceof UnauthorizedScope,'ready_failure_error');}
      requireCheck(JSON.stringify(await scoped('SELECT state,attempt_count FROM cragkit.ingestion_jobs WHERE tenant_id=$1 AND collection_id=$2 AND intent_id=$3',[...key.slice(0,2),'node-build']))===JSON.stringify(priorJob),'failed_ready_changed_job');
      const generationState=await scoped('SELECT status FROM cragkit.index_generations WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3 AND generation_id=$4',[...key,staged.generation_id]);
      requireCheck(generationState[0]?.[0]==='staging','failed_ready_changed_generation');
      await unchanged(baseline.generation_id,original);
    } finally {await owner('deny_ready',false);}
    checks.push('mixed_generation_and_failed_ready_write_preserve_prior_result');
    const retained=(await read()).find(c=>c.document_id==='vector-node');
    const first=await vector.publish(shared.replacement_source,pub());
    requireCheck(await pointer()===first.generation_id,'published_pointer');
    const historical=await read(scopes[0],retained);
    const canonical=canonicalize(shared.baseline_source,shared.canonical_options);
    const expectedText=Buffer.from(canonical.canonical_text).subarray(retained.start_byte,retained.end_byte).toString('utf8');
    requireCheck(historical.state==='verified'&&historical.stale&&historical.evidence.text===expectedText&&historical.evidence.source_sha256===canonical.canonical_sha256,'retained_source_snapshot');
    const publishedAgain=await vector.publish(shared.replacement_source,pub());
    requireCheck(publishedAgain.replayed&&publishedAgain.provider_calls===0,'published_replay');
    const slowSource='alpha slower competing shadow',fastSource='alpha newer competing shadow';
    const build=intent=>options(intent,{expected_generation_id:first.generation_id});
    await vector.stage(slowSource,build('node-slow'));
    const fast=await vector.stage(fastSource,build('node-fast'));
    await vector.publish(fastSource,build('node-fast'));
    const prior=normalized(await read());
    try {await vector.publish(slowSource,build('node-slow'));throw new CheckError('stale_cas_accepted');}
    catch(error){requireCheck(error instanceof IndexNotReady,'stale_cas_error');}
    await unchanged(fast.generation_id,prior);
    checks.push('atomic_publish_replay_cas_and_retained_immutable_source');
    const deniedSource='alpha authorization-sensitive staged build',deniedOptions=()=>options('node-denied',{expected_generation_id:fast.generation_id});
    await vector.stage(deniedSource,deniedOptions());
    await scoped("UPDATE cragkit.document_grants SET authorization_revision='revoked' WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3",key);
    try {
      try {await vector.publish(deniedSource,deniedOptions());throw new CheckError('revoked_accepted');}
      catch(error){requireCheck(error instanceof UnauthorizedScope,'revoked_error');}
      await unchanged(fast.generation_id,[]);
      requireCheck((await read(scopes[0],retained)).state==='unavailable','revoked_source_release');
    } finally {await scoped('UPDATE cragkit.document_grants SET authorization_revision=$4 WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3',[...key,scopes[0].authorization_revision]);}
    await scoped('UPDATE cragkit.documents SET tombstoned=true WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3',key);
    try {
      try {await vector.publish(deniedSource,deniedOptions());throw new CheckError('tombstone_accepted');}
      catch(error){requireCheck(error instanceof UnauthorizedScope,'tombstone_error');}
      await unchanged(fast.generation_id,[]);
      requireCheck((await read(scopes[0],retained)).state==='unavailable','tombstoned_source_release');
    } finally {await scoped('UPDATE cragkit.documents SET tombstoned=false WHERE tenant_id=$1 AND collection_id=$2 AND document_id=$3',key);}
    checks.push('revocation_tombstones_and_final_source_release_remain_denied');
    return {checks,phase:'full',receipt:first,active_receipt:fast,active_source:fastSource};
  } finally {await resource.close();}
}
if(process.argv[2]!=='--allow-vector-checks')throw new Error('Explicit fixture authorization required.');
try {
  const result=await run(privateJSON(process.argv[3]),privateJSON(process.argv[4]));
  process.stdout.write(JSON.stringify({type:'result',...result})+'\n');
} catch(error) {
  const known=['invalid_request','index_not_ready','unsupported_capability','integrity_violation','unauthorized_scope','embedding_profile_mismatch','provider_unavailable','deadline_exceeded'];
  process.stdout.write(JSON.stringify({type:'error',code:error instanceof CheckError?error.message:known.includes(error?.code)?error.code:'native_vector_check_failed'})+'\n');
  process.exitCode=1;
} finally {input.close();}
