/** Actual profile-4 reader admission; no source release or settlement claim. */
import {isDeepStrictEqual as same} from 'node:util';
import {PoolResource,parse_pool_config,bounded,now} from '../packages/typescript/dist/postgres-pool.js';
import {PostgresQdrantAuthority} from '../packages/typescript/dist/qdrant-authority.js';
import {UnsupportedCapability} from '../packages/typescript/dist/errors.js';

const CHECKS=Object.freeze([
  'four_migration_reader_admission_with_exact_guard_shape',
  'unpublished_scoped_read_returns_no_source_bytes',
  'committed_sensitive_guard_grant_refused_before_source_sql',
  'guard_owner_login_drift_refused_before_source_sql',
  'fifth_history_row_refused_after_initialization',
  'extra_definer_refused_without_legacy_fallback',
  'permission_and_catalog_restoration_allows_safe_source_read',
  'borrowed_resources_close_and_no_provider_activity',
]);
const ERRORS=new Set(['IntegrityViolation','InvalidRequest','ProviderUnavailable','UnauthorizedScope',
  'UnsupportedCapability','DeadlineExceeded','IndexNotReady','AbortError','CancelledError']);
const cancellation=new AbortController();let readingInput=true,step=0;
const cancel=()=>{cancellation.abort();if(readingInput)process.stdin.destroy();};
process.on('SIGTERM',cancel);process.on('SIGINT',cancel);
function outcome(error){try{return ERRORS.has(error?.name)?error.name:'internal';}catch{return 'internal';}}
class RuntimeCleanupFailure extends Error{
  constructor(primary,failures){super('runtime_cleanup_failed');this.primary=primary?outcome(primary):null;this.failures=failures;}
}
async function input(){
  const chunks=[];let size=0;
  for await(const chunk of process.stdin){size+=chunk.length;if(size>1048576)throw new Error('bounded_input');chunks.push(chunk);}
  const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
  if(!value||typeof value!=='object'||Array.isArray(value)||!same(Object.keys(value).sort(),['inputs','operator_config','reader_config'])
    ||!value.inputs||typeof value.inputs!=='object'||Array.isArray(value.inputs)
    ||!same(Object.keys(value.inputs).sort(),['config','nomination','request','scope']))throw new Error('input_shape');
  return value;
}
async function cases(value){
  const readerConfig=parse_pool_config(value.reader_config),operatorConfig=parse_pool_config(value.operator_config);
  if(readerConfig.max_size!==1||operatorConfig.max_size!==1)throw new Error('two_client_ceiling');
  const options={deadline:now()+120,signal:cancellation.signal};
  let sourceQueries=0,deniedSourceQueries=0,activeRestore,primary;
  const vanilla=new PoolResource(readerConfig);
  const defaultFactory=vanilla.factory;
  if(typeof defaultFactory!=='function')throw new Error('native_factory_unavailable');
  const reader=new PoolResource(readerConfig,{factory:async config=>{
    const actual=await defaultFactory(config);
    return {async connect(){
      const client=await actual.connect();
      return {query(query){
        if(typeof query?.text==='string'&&query.text.includes('FROM cragkit_qdrant.members m'))sourceQueries++;
        return client.query(query);
      },getTransactionStatus(){return client.getTransactionStatus();},release(destroy){client.release(destroy);}};
    },end(){return actual.end();}};
  }});
  const operator=new PoolResource(operatorConfig),authority=new PostgresQdrantAuthority(reader),checks=[];
  const mark=()=>{checks.push(CHECKS[checks.length]);step=checks.length;};
  const {inputs}=value;
  const execute=(text,values=[],selected=options)=>operator.withLease(selected,client=>client.query({text,values,rowMode:'array'}));
  const read=()=>authority.read(inputs.nomination,inputs.request,inputs.scope,inputs.config,
    {...options,retained:false,max_source_bytes:16777216});
  async function safeRead(){
    const before=sourceQueries,rows=await read();
    if(!same(rows,[])||sourceQueries!==before+1)throw new Error('unpublished_read');
  }
  async function refuse(){
    const before=sourceQueries;let refused=false;
    try{await read();}catch(error){if(!(error instanceof UnsupportedCapability))throw error;refused=true;}
    deniedSourceQueries+=sourceQueries-before;
    if(!refused||sourceQueries!==before)throw new Error('unsafe_source_query');
  }
  async function mutation(apply,restore,applyValues=[],restoreValues=[]){
    await execute(apply,applyValues);
    activeRestore=()=>execute(restore,restoreValues,{deadline:now()+5});
    let failure;
    try{await refuse();}catch(error){failure=error;}
    try{await activeRestore();}
    catch(error){throw new RuntimeCleanupFailure(failure,[{operation:'catalog_restore',outcome:outcome(error)}]);}
    activeRestore=undefined;
    if(failure)throw failure;
    await safeRead();
  }
  try{
    await reader.open();await operator.open();await authority.initialize(options);mark();
    await safeRead();mark();
    await mutation('GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO cragkit_qdrant_security_guard',
      'REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM cragkit_qdrant_security_guard');mark();
    await mutation('ALTER ROLE cragkit_qdrant_security_guard LOGIN','ALTER ROLE cragkit_qdrant_security_guard NOLOGIN');mark();
    await mutation('INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES($1,$2)',
      'DELETE FROM cragkit_qdrant.schema_migrations WHERE version=$1 AND checksum_sha256=$2',
      ['9999_native_guard_admission_probe','0'.repeat(64)],['9999_native_guard_admission_probe','0'.repeat(64)]);mark();
    await mutation("CREATE FUNCTION cragkit_qdrant.native_guard_admission_probe() RETURNS boolean LANGUAGE SQL SECURITY DEFINER AS 'SELECT true'",
      'DROP FUNCTION cragkit_qdrant.native_guard_admission_probe()');mark();
    await safeRead();
    if(sourceQueries!==6||deniedSourceQueries!==0)throw new Error('source_query_accounting');mark();
    const readerAlive=await reader.withLease(options,client=>client.query({text:'SELECT 1',values:[],rowMode:'array'}));
    const operatorAlive=await execute('SELECT 1');
    if(!same(readerAlive.rows,[[1]])||!same(operatorAlive.rows,[[1]]))throw new Error('borrowed_resource_lifetime');
    await reader.close();await operator.close();await vanilla.close();mark();
    return {runtime:'typescript',checks,proof_scope:'profile4_authority_admission_only',source_queries:sourceQueries,denied_source_queries:deniedSourceQueries};
  }catch(error){primary=error;throw error;}
  finally{
    const failures=[],deadline=now()+12;
    async function cleanup(operation,action){
      try{await bounded(Promise.resolve().then(action),{deadline:Math.max(now()+.001,Math.min(now()+5,deadline))});}
      catch(error){failures.push({operation,outcome:outcome(error)});}
    }
    if(activeRestore)await cleanup('catalog_restore',activeRestore);
    for(const [operation,resource]of [['reader_pool_close',reader],['operator_pool_close',operator],['factory_pool_close',vanilla]]){
      await cleanup(operation,()=>resource.close());
    }
    if(failures.length)throw new RuntimeCleanupFailure(primary,failures);
  }
}
try{
  const value=await bounded(input(),{deadline:now()+5,signal:cancellation.signal});readingInput=false;
  process.stdout.write(JSON.stringify(await cases(value))+'\n');
}catch(error){
  process.stdout.write(JSON.stringify(error instanceof RuntimeCleanupFailure
    ?{ok:false,step,error:'cleanup_failed',primary:error.primary,cleanup:error.failures}
    :{ok:false,step,error:outcome(error)})+'\n');process.exitCode=1;
}finally{process.removeListener('SIGTERM',cancel);process.removeListener('SIGINT',cancel);}
