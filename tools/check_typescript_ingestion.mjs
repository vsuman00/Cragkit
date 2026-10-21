/** Native child of the explicitly authorized empty-target fixture. No DDL/admin access. */
import { readFileSync, lstatSync } from 'node:fs';
import { PoolResource, parse_pool_config, now } from '../packages/typescript/dist/postgres-pool.js';
import { PostgresIndexer } from '../packages/typescript/dist/ingestion.js';
import { canonicalize } from '../packages/typescript/dist/canonical.js';
import { parse_scope } from '../packages/typescript/dist/contracts.js';
import { InvalidRequest, UnauthorizedScope, IndexNotReady } from '../packages/typescript/dist/errors.js';

class CheckError extends Error {}
const requireCheck=(condition,code)=>{if(!condition)throw new CheckError(code);};
function privateJSON(path) {
  const info=lstatSync(path);
  requireCheck(info.isFile()&&info.uid===process.getuid()&&(info.mode&0o077)===0,'private_file_permissions');
  return JSON.parse(readFileSync(path,'utf8'));
}
async function run(config, fixture) {
  const resource=new PoolResource(parse_pool_config({...config,max_size:1}));
  const scopes=fixture.scopes.map(parse_scope);
  const checks=[];
  const authorize=async(scope,collection,document)=>scopes.some(value=>JSON.stringify(value)===JSON.stringify(scope))
    &&collection===fixture.collection&&['ingestion-shared-document','node-document'].includes(document);
  const indexer=new PostgresIndexer(resource,authorize);
  const options=(changes={})=>({collection:fixture.collection,document_id:'ingestion-shared-document',intent_id:'initial-intent',
    source_locator:'synthetic:ingestion',scope:scopes[0],deadline:now()+15,
    canonical_options:{target_bytes:8,max_chunk_bytes:16},metadata:{unicode:'Café🙂',nested:[null,true,1.25]},...changes});
  async function read(scope,document,receipt,source) {
    const canonical=canonicalize(source,{target_bytes:8,max_chunk_bytes:16});
    return resource.withLease({deadline:now()+8},async client=>{
      await client.query({text:'BEGIN READ ONLY',rowMode:'array'});
      try {
        await client.query({text:"SELECT set_config('cragkit.tenant_id',$1,true),set_config('cragkit.principal_id',$2,true),set_config('cragkit.authorization_revision',$3,true)",values:[scope.tenant_id,scope.principal_id,scope.authorization_revision],rowMode:'array'});
        const result=await client.query({text:`SELECT r.source_sha256,r.canonical_sha256,r.canonical_text,c.start_byte,c.end_byte,c.text,c.text_sha256,
          l.search_vector=to_tsvector(l.language_config::regconfig,c.text)
          FROM cragkit.document_revisions r JOIN cragkit.documents d USING(tenant_id,collection_id,document_id)
          JOIN cragkit.chunks c USING(tenant_id,collection_id,document_id,revision_id)
          JOIN cragkit.chunk_lexical l USING(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id)
          WHERE r.tenant_id=$1 AND r.collection_id=$2 AND r.document_id=$3 AND c.generation_id=$4
          AND NOT d.tombstoned AND d.authorization_revision=$5
          AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
            AND x.document_id=d.document_id AND x.principal_id=$6 AND x.authorization_revision=$5)
          ORDER BY c.ordinal`,values:[scope.tenant_id,fixture.collection,document,receipt.generation_id,scope.authorization_revision,scope.principal_id],rowMode:'array'});
        requireCheck(result.rows.length===receipt.chunk_count,'stored_chunk_count');
        for(let index=0;index<result.rows.length;index++) {
          const row=result.rows[index],chunk=canonical.chunks[index];
          requireCheck(row[0]===canonical.source_sha256&&row[1]===canonical.canonical_sha256&&row[2]===canonical.canonical_text
            &&Number(row[3])===chunk.start_byte&&Number(row[4])===chunk.end_byte&&row[5]===chunk.text
            &&row[6]===chunk.text_sha256&&row[7]===true,'native_read_spans_digests_fts');
        }
      } finally {await client.query({text:'ROLLBACK',rowMode:'array'});}
    });
  }
  try {
    await resource.open();
    const first=await indexer.ingest(fixture.python_source,options());
    requireCheck(first.replayed&&JSON.stringify({...first,replayed:false})===JSON.stringify(fixture.python_receipt),'python_intent_identifier_parity');
    await read(scopes[0],'ingestion-shared-document',first,fixture.python_source);
    checks.push('python_write_node_read_exact_spans_and_intent_replay');
    let rejected=false;
    try {await indexer.ingest(fixture.python_source+'changed',options());}catch(error){rejected=error instanceof InvalidRequest;}
    requireCheck(rejected,'cross_runtime_payload_conflict');
    rejected=false;
    try {await indexer.ingest('denied',options({scope:parse_scope({...scopes[0],principal_id:'unauthorized-principal'})}));}
    catch(error){rejected=error instanceof UnauthorizedScope;}
    requireCheck(rejected,'node_write_authorization');
    checks.push('node_cross_runtime_conflict_and_write_authorization');
    const source='\ufeffNode Café🙂\r\n\r\nNative source\n';
    const nodeOptions=options({document_id:'node-document',intent_id:'node-intent',metadata:{'🙂':[null,true,1.0],z:-0}});
    const receipt=await indexer.ingest(source,nodeOptions);
    requireCheck(!receipt.replayed&&receipt.chunk_count>1,'node_first_receipt');
    await read(scopes[0],'node-document',receipt,source);
    const replay=await indexer.ingest(source,{...nodeOptions,deadline:now()+15});
    requireCheck(replay.replayed&&receipt.generation_id===replay.generation_id,'node_replay');
    const other=await indexer.ingest(source,{...nodeOptions,scope:scopes[1],deadline:now()+15});
    requireCheck(other.tenant_id!==receipt.tenant_id&&other.generation_id!==receipt.generation_id,'node_tenant_isolation');
    await read(scopes[1],'node-document',other,source);
    checks.push('node_write_replay_native_fts_and_same_ids_two_tenants');
    const sentinel=new Error('synthetic hook');let caught=false;
    try {await indexer.ingest('unpublished node revision',options({document_id:'node-document',intent_id:'failed-node-intent',
      expected_generation_id:receipt.generation_id,before_publish:async()=>{throw sentinel;}}));}
    catch(error){caught=error===sentinel;}
    requireCheck(caught,'node_hook_identity');
    const controller=new AbortController();let entered;
    const ready=new Promise(resolve=>{entered=resolve;});
    const task=indexer.ingest('cancelled node revision',options({document_id:'node-document',intent_id:'aborted-node-intent',
      expected_generation_id:receipt.generation_id,signal:controller.signal,before_publish:async()=>{entered();await new Promise(()=>{});}}));
    // Observe early task rejection as well as hook readiness, without leaving a rejection unhandled.
    await Promise.race([ready,task.then(()=>{throw new CheckError('node_hook_not_entered');})]);
    controller.abort();caught=false;
    try{await task;}catch(error){caught=error.name==='AbortError';}
    requireCheck(caught,'node_abort_propagation');
    const after=await indexer.ingest(source,{...nodeOptions,deadline:now()+15});
    requireCheck(after.replayed,'node_after_abort_replay');
    await read(scopes[0],'node-document',receipt,source);
    rejected=false;
    try {await indexer.ingest('stale node revision',options({document_id:'node-document',intent_id:'stale-node-intent',expected_generation_id:'stale'}));}
    catch(error){rejected=error instanceof IndexNotReady;}
    requireCheck(rejected,'node_stale_cas');
    checks.push('node_hook_abort_rollback_reuse_and_stale_cas');
    return {state:'passed',checks,receipt};
  } finally {await resource.close();}
}
try {
  const args=process.argv.slice(2);
  requireCheck(args.length===3&&args[0]==='--allow-ingestion-checks','explicit_authorization');
  const result=await run(privateJSON(args[1]),privateJSON(args[2]));
  process.stdout.write(JSON.stringify(result)+'\n');
} catch(error) {
  const code=error instanceof CheckError&&/^[a-z_]+$/.test(error.message)?error.message:'native_ingestion_failed';
  process.stdout.write(JSON.stringify({state:'failed',code})+'\n');process.exitCode=1;
}
