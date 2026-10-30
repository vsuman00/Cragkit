import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {PostgresQdrantWriter,PURGE_RETENTION_POLICY,purge_projection_data,purge_dispatch_plan_data} from '../dist/qdrant-writer.js';
import {PostgresQdrantRecovery,dispatch_purge_recovery,settle_purge_guarded,purge_dispatch_authorization} from '../dist/qdrant-recovery.js';
import {QdrantSecurityVerifier,verify_purge_ordinary,purge_absence_receipt_data} from '../dist/qdrant-security-verification.js';
import {QdrantPublicationManager,PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport} from '../dist/qdrant-publication.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {QdrantReconciliationVerifier} from '../dist/qdrant-reconciliation.js';
import {ExecutionLedger} from '../dist/execution.js';
import {InvalidRequest,IndexNotReady,UnsupportedCapability} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const scope={tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'};
const context={scope,collection:'docs',document_id:'doc-1',intent_id:'purge-1',owner_token:'00000000-0000-4000-8000-000000000001'};
const options=()=>({deadline:now()+5});
const record={intent_id:context.intent_id,tenant_id:scope.tenant_id,collection:context.collection,document_id:context.document_id,
  tombstone_intent_payload_sha256:'a'.repeat(64),expected_authorization_revision:'auth-1',expected_mutation_epoch:2};

function setup(){
  const state={checkouts:0,authorizations:0};
  const pool={async connect(){state.checkouts++;throw Error('unexpected database checkout');},async end(){}};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',sslrootcert:'/fake/ca',
    passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  const writer=new PostgresQdrantWriter(resource,config,'instance-fixture');
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-fixture',config);
  const reconciliation=new QdrantReconciliationVerifier(writer,supervisor);
  const recovery=new PostgresQdrantRecovery(resource,config,supervisor,reconciliation);
  const verifier=new QdrantSecurityVerifier(writer,supervisor);
  const authority=new PostgresQdrantPublicationAuthority(writer,recovery);
  const transport=new ManagedQdrantPublicationTransport(supervisor);
  const authorize=async()=>{state.authorizations++;return true;};
  const manager=new QdrantPublicationManager(authority,transport,config,supervisor,authorize);
  return {state,writer,recovery,verifier,manager,async close(){await manager.close();await verifier.close();await writer.close();
    await recovery.close();await reconciliation.close();await resource.close();}};
}

test('purge policy is explicit and rejected before readiness, callbacks or storage',async()=>{
  const f=setup();
  try{
    for(const policy of [undefined,null,'vectors_only','erase_managed_source_and_replay_v2',new String(PURGE_RETENTION_POLICY)]){
      const ledger=new ExecutionLedger({limits:{max_provider_calls:0,max_attempts:1},deadline:now()+5});
      await assert.rejects(f.manager.purge(record,scope,ledger,policy,options()),typeof policy==='string'?UnsupportedCapability:InvalidRequest);
      assert.equal(ledger.snapshot().attempts,0);
    }
    const ledger=new ExecutionLedger({limits:{max_provider_calls:0,max_attempts:1},deadline:now()+5});
    await assert.rejects(f.manager.purge(record,scope,ledger,PURGE_RETENTION_POLICY,options()),IndexNotReady);
    assert.equal(f.state.checkouts,0);assert.equal(f.state.authorizations,0);assert.equal(ledger.snapshot().provider_calls,0);
  }finally{await f.close();}
});

test('serialized, copied and proxy purge capabilities cannot authorize work',async()=>{
  const f=setup();
  try{
    for(const forged of [{},Object.freeze({}),JSON.parse(JSON.stringify({context})),new Proxy({},{})]){
      assert.throws(()=>purge_projection_data(forged,f.writer),InvalidRequest);
      await assert.rejects(f.writer.admit_purge_successor(forged,
        {instance_id:'instance-fixture',intent_id:'purge-previous',owner_token:context.owner_token,backend_epoch:1},
        {instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:1},options()),InvalidRequest);
      assert.throws(()=>purge_dispatch_authorization(forged,f.writer,options()),InvalidRequest);
      assert.throws(()=>purge_dispatch_plan_data(forged,{},f.writer,options()),InvalidRequest);
      assert.throws(()=>purge_absence_receipt_data(forged,f.verifier,options()),InvalidRequest);
      await assert.rejects(verify_purge_ordinary(f.verifier,{},context,forged,options()),InvalidRequest);
      await assert.rejects(dispatch_purge_recovery(f.recovery,{},context,forged,async()=>true,options()),InvalidRequest);
      await assert.rejects(settle_purge_guarded(f.recovery,f.verifier,{},context,forged,options()),InvalidRequest);
    }
    assert.equal(f.state.checkouts,0);assert.equal(f.state.authorizations,0);
  }finally{await f.close();}
});
