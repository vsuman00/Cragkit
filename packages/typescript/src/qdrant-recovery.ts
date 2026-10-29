/** Supervisor SQL control. Physical fencing and source authority stay separate. */
import { types } from 'node:util';
import {randomUUID} from 'node:crypto';
import { PoolResource, bounded, now, type LeaseOptions } from './postgres-pool.js';
import { ManagedQdrantSupervisor, type SupervisorControlSession } from './qdrant-supervisor.js';
import { QdrantReconciliationVerifier, receipt_data, verifier_authority, inspect_missing_readback, verification_budget, type VerificationBudget } from './qdrant-reconciliation.js';
import { projection_data, writer_binding, recovery_dispatch_plan_data, type RecoveryDispatchPlanData, type PostgresQdrantWriter } from './qdrant-writer.js';
import { AUTHORITY_HISTORY_SQL, AUTHORITY_PUBLICATION_HISTORY, AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL, EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,
  AUTHORITY_ATTESTATION_HISTORY,AUTHORITY_ATTESTATION_CATALOG_SQL,EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT,
  AUTHORITY_SECURITY_GUARD_HISTORY,AUTHORITY_SECURITY_GUARD_CATALOG_SQL,EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT,SECURITY_GUARD_OWNER_SQL } from './qdrant-authority.js';
import { same, parse_response, type QdrantConfig } from './qdrant-contract.js';
import { config as parse_config, context as parse_context, options as parse_options, fields, metadata,
  native_array, text, count, db_count, uuid, digest, hash, type Data, type WriterContext } from './qdrant-writer-contract.js';
import { DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable,
  UnauthorizedScope, UnsupportedCapability } from './errors.js';

type Binding = Readonly<Data>;
type Backend = Readonly<{instance_id:string;backend_namespace:string;storage_identity:string;supervisor_id:string;
  epoch:number;state:'open'|'recovery_blocked';recovery_id:string|null}>;
type Tx = Readonly<{query:(sql:string,values?:readonly unknown[],max?:number)=>Promise<unknown[][]>}>;
type SQLSettlement = Readonly<Record<never,never>>;
type Settlement = Readonly<{issuer:PostgresQdrantRecovery;supervisor:ManagedQdrantSupervisor;barrier:unknown;binding:Binding}>;
const settlements = new WeakMap<object,Settlement>();
type RecoveryRegistration=Readonly<{
  resource:PoolResource;
  config:QdrantConfig;
  writer:PostgresQdrantWriter;
  supervisor:ManagedQdrantSupervisor;
  verifier:QdrantReconciliationVerifier;
}>;
const recoveryRegistrations=new WeakMap<object,RecoveryRegistration>();

export type RecoveryDispatchAuthorizationData=Readonly<{context:WriterContext;physical_binding:Binding;attempt_binding:Binding;sequence:number}>;
type DispatchAuthorization=Readonly<{issuer:PostgresQdrantRecovery;writer:PostgresQdrantWriter;supervisor:ManagedQdrantSupervisor;
  proof:unknown;attempt:unknown;data:RecoveryDispatchAuthorizationData;deadline:number;signal?:AbortSignal;lifetime:{active:boolean}}>;
const dispatchAuthorizations=new WeakMap<object,DispatchAuthorization>();
export function recovery_dispatch_authorization(input:unknown,expectedWriter:PostgresQdrantWriter,rawOptions:unknown):RecoveryDispatchAuthorizationData {
  const options=parse_options(rawOptions);writer_binding(expectedWriter);
  if(typeof input!=='object'||input===null||types.isProxy(input))throw new InvalidRequest();
  const issued=dispatchAuthorizations.get(input);
  const origin=issued?recoveryRegistrations.get(issued.issuer):undefined;
  if(!issued||issued.writer!==expectedWriter||!origin||origin.writer!==expectedWriter||origin.supervisor!==issued.supervisor)throw new InvalidRequest();
  if(!issued.lifetime.active||options.deadline>issued.deadline||options.signal!==issued.signal)throw new InvalidRequest();
  parse_options({deadline:issued.deadline,signal:issued.signal});
  if(!same(physical(issued.supervisor.recovery_binding(issued.proof)),issued.data.physical_binding)
    ||!same(metadata(issued.supervisor.attempt_binding(issued.attempt)),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
}

/** Return only the originally bound nominal verifier, never privileged resources. */
export function recovery_components(input:unknown,expected_writer:unknown,expected_supervisor:unknown,expected_config:unknown):QdrantReconciliationVerifier {
  if(typeof input!=='object'||input===null||types.isProxy(input)
    ||Object.getPrototypeOf(input)!==PostgresQdrantRecovery.prototype
    ||typeof expected_supervisor!=='object'||expected_supervisor===null||types.isProxy(expected_supervisor)
    ||Object.getPrototypeOf(expected_supervisor)!==ManagedQdrantSupervisor.prototype)throw new InvalidRequest();
  const original=recoveryRegistrations.get(input);
  const writer=writer_binding(expected_writer);
  if(!original||original.writer!==expected_writer||original.supervisor!==expected_supervisor)throw new InvalidRequest();
  if(verifier_authority(original.verifier,original.supervisor)!==original.writer)throw new InvalidRequest();
  const config=parse_config(expected_config);
  if(!same(config,original.config)||!same(writer.config,original.config))throw new UnsupportedCapability();
  return original.verifier;
}

/** Only a committed recovery coordinator can mint the nominal SQL handoff. */
export function settlement_data(token:unknown,supervisor:ManagedQdrantSupervisor,barrier:unknown):Binding {
  if (typeof token !== 'object' || token === null) throw new UnsupportedCapability();
  const entry = settlements.get(token);
  if (!entry || entry.supervisor !== supervisor || entry.barrier !== barrier) throw new UnsupportedCapability();
  if (!same(supervisor.barrier_binding(barrier),entry.binding)) throw new UnsupportedCapability();
  settlements.delete(token);
  return entry.binding;
}

export const RECOVERY_ROLE_SQL = `SELECT current_user=session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND EXISTS(SELECT 1 FROM pg_roles capability WHERE capability.rolname='cragkit_qdrant_supervisor'
  AND NOT(capability.rolcanlogin OR capability.rolsuper OR capability.rolbypassrls OR capability.rolcreaterole OR capability.rolcreatedb OR capability.rolreplication)
  AND NOT EXISTS(SELECT 1 FROM pg_auth_members membership WHERE membership.member=capability.oid)
  AND pg_has_role(current_user,capability.oid,'USAGE'))
 AND NOT EXISTS(SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER') AND
  (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR
   r.rolname IN('cragkit_qdrant_writer','pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')))
 AND has_schema_privilege(current_user,'cragkit_qdrant','USAGE')
 AND NOT EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit_qdrant' AND
  (pg_has_role(current_user,n.nspowner,'MEMBER') OR has_schema_privilege(current_user,n.oid,'CREATE')))
 AND NOT EXISTS(SELECT 1 FROM pg_database d WHERE pg_has_role(current_user,d.datdba,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND
  (pg_has_role(current_user,c.relowner,'MEMBER') OR has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER')
   OR (c.relkind='r' AND c.relname<>'schema_migrations' AND NOT row_security_active(c.oid))))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND has_table_privilege(current_user,c.oid,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN('schema_migrations','backend_instances','document_owners','point_claims','dispatch_points','preparations')
   WHEN privilege='INSERT' THEN c.relname IN('backend_instances','dispatch_journal','dispatch_points')
   WHEN privilege='UPDATE' THEN c.relname='backend_instances'
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND
  has_column_privilege(current_user,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN('schema_migrations','backend_instances','document_owners','point_claims','dispatch_points','preparations')
    OR (c.relname='publication_intents' AND a.attname IN('tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256','manifest_sha256','revision_id','generation_id','expected_active_generation_id','expected_authorization_revision','expected_mutation_epoch','state','authority_committed','replica_complete','purge_complete'))
    OR (c.relname='dispatch_journal' AND a.attname IN('tenant_id','collection','document_id','intent_id','dispatch_id','instance_id','sequence','owner_token','backend_epoch','credential_generation','operation','recovery','request_sha256','state','completion_sha256','created_xid'))
   WHEN privilege='INSERT' THEN c.relname IN('backend_instances','dispatch_journal','dispatch_points')
   WHEN privilege='UPDATE' THEN c.relname='backend_instances'
    OR (c.relname='document_owners' AND a.attname='backend_epoch')
    OR (c.relname='dispatch_journal' AND a.attname IN('state','completion_sha256'))
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND
  has_function_privilege(current_user,p.oid,'EXECUTE') IS DISTINCT FROM (
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.supervisor_instance(text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)')))`;

/** Exact legacy role map with only SG-r2's private guard execution added. */
export const RECOVERY_SECURITY_GUARD_ROLE_SQL=RECOVERY_ROLE_SQL.replace(
  "p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR",
  "p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)') OR\n   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR");
type RecoverySchemaProfile='publication'|'attestation'|'security_guard';
function recovery_profile(history:unknown):RecoverySchemaProfile{
  try{
    const rows=native_array(history,1,4).map(row=>native_array(row,2,2).map(value=>{
      if(typeof value!=='string')throw new UnsupportedCapability();return value;
    }));
    if(same(rows,AUTHORITY_PUBLICATION_HISTORY))return 'publication';
    if(same(rows,AUTHORITY_ATTESTATION_HISTORY))return 'attestation';
    if(same(rows,AUTHORITY_SECURITY_GUARD_HISTORY))return 'security_guard';
  }catch(error){if(!(error instanceof InvalidRequest))throw error;}
  throw new UnsupportedCapability();
}
class CommitUnknown extends Error {}
function safe(error:unknown,deadline:number):Error {
  if (error instanceof DeadlineExceeded) return new DeadlineExceeded();
  if (error instanceof InvalidRequest) return new InvalidRequest();
  if (error instanceof UnauthorizedScope) return new UnauthorizedScope();
  if (error instanceof UnsupportedCapability) return new UnsupportedCapability();
  if (error instanceof IntegrityViolation) return new IntegrityViolation();
  if (error instanceof IndexNotReady) return new IndexNotReady();
  if (error instanceof DOMException && error.name==='AbortError') return new DOMException('Operation aborted.','AbortError');
  let code:unknown;
  try { code=Object.getOwnPropertyDescriptor(error as object,'code')?.value; } catch { /* No untrusted error hooks. */ }
  if (code==='42501') return new UnauthorizedScope();
  if (code==='57014' && now()>=deadline) return new DeadlineExceeded();
  if (typeof code==='string' && ['42P01','42703','42883','42704','3F000'].includes(code)) return new UnsupportedCapability();
  if (typeof code==='string' && ['23502','23503','23505','23514'].includes(code)) return new IntegrityViolation();
  return new ProviderUnavailable();
}
function physical(input:unknown):Binding {
  const value=metadata(input);
  fields(value,['instance_id','storage_identity','supervisor_id','recovery_id','old_epoch','new_epoch','credential_generation']);
  for (const key of ['instance_id','storage_identity','supervisor_id','recovery_id','credential_generation']) text(value[key]);
  if (count(value.new_epoch,1)!==count(value.old_epoch,1)+1) throw new InvalidRequest();
  return value;
}
function control(supervisor:ManagedQdrantSupervisor):Data {
  const value=metadata(supervisor.control_binding());
  fields(value,['instance_id','backend_namespace','storage_identity','supervisor_id','epoch','credential_generation','recovery','sealed','alive']);
  for (const key of ['instance_id','backend_namespace','storage_identity','supervisor_id','credential_generation']) text(value[key]);
  count(value.epoch,1);
  if (typeof value.sealed!=='boolean'||typeof value.alive!=='boolean') throw new InvalidRequest();
  if (value.recovery!==null) {
    const recovery=fields(value.recovery,['recovery_id','old_epoch','new_epoch']);
    text(recovery.recovery_id);
    if (count(recovery.new_epoch,1)!==count(recovery.old_epoch,1)+1) throw new InvalidRequest();
  }
  return value;
}

export class PostgresQdrantRecovery {
  readonly #resource:PoolResource;
  readonly #config:QdrantConfig;
  readonly #supervisor:ManagedQdrantSupervisor;
  readonly #verifier:QdrantReconciliationVerifier;
  readonly #writer:PostgresQdrantWriter;
  #identity?:Data;
  #ready=false;
  #profile:RecoverySchemaProfile|null=null;
  #securityGuardAdmitted=false;
  #closed=false;
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #closing?:Promise<void>;
  constructor(resource:PoolResource,config:unknown,supervisor:ManagedQdrantSupervisor,verifier:QdrantReconciliationVerifier) {
    if (!resource||!supervisor||!verifier||types.isProxy(resource)||Object.getPrototypeOf(resource)!==PoolResource.prototype
      ||types.isProxy(supervisor)||Object.getPrototypeOf(supervisor)!==ManagedQdrantSupervisor.prototype
      ||types.isProxy(verifier)||Object.getPrototypeOf(verifier)!==QdrantReconciliationVerifier.prototype) throw new InvalidRequest();
    this.#resource=resource;
    this.#config=parse_config(config);
    this.#supervisor=supervisor;
    this.#verifier=verifier;
    this.#writer=verifier_authority(verifier,supervisor);
    recoveryRegistrations.set(this,Object.freeze({resource:this.#resource,config:this.#config,writer:this.#writer,
      supervisor:this.#supervisor,verifier:this.#verifier}));
  }
  #admit(initializing=false):void {
    if (this.#closed||this.#active) throw new ProviderUnavailable();
    if (!initializing&&!this.#ready) throw new IndexNotReady();
  }
  async #work<T>(options:LeaseOptions,body:(options:LeaseOptions,control:SupervisorControlSession)=>Promise<T>,initializing=false):Promise<T> {
    this.#admit(initializing);
    const controller=new AbortController();
    const relay=()=>controller.abort();
    options.signal?.addEventListener('abort',relay,{once:true});
    if (options.signal?.aborted) controller.abort();
    let finish!:()=>void;
    const done=new Promise<void>(resolve=>{finish=resolve;});
    this.#active={controller,done};
    try {
      return await this.#supervisor.control_session(control=>body({deadline:options.deadline,signal:controller.signal},control));
    }
    catch (error) { if(initializing)this.#ready=false;throw safe(error,options.deadline); }
    finally {
      options.signal?.removeEventListener('abort',relay);
      this.#active=undefined;
      finish();
    }
  }
  async #tx<T>(instance_id:string,options:LeaseOptions,body:(tx:Tx,profile:RecoverySchemaProfile)=>Promise<T>,initializing=false,expectedProfile?:RecoverySchemaProfile):Promise<T> {
    return this.#resource.withLease(options,async(client,signal)=>{
      const lease={deadline:options.deadline,signal};
      let status:string|null;
      try { status=client.getTransactionStatus(); } catch { client.release(true);throw new ProviderUnavailable(); }
      if (status!=='I') { client.release(true);throw new InvalidRequest(); }
      let begun=false,committing=false,committed=false;
      const tx:Tx={query:async(sql,values,max=257)=>{
        const milliseconds=String(Math.max(1,Math.floor(Math.min(options.deadline-now(),2147483.647)*1000)));
        await bounded(client.query({text:"SELECT set_config('statement_timeout',$1,true)",values:[milliseconds],rowMode:'array'}),lease);
        const result=await bounded(client.query({text:sql,values,rowMode:'array'}),lease);
        try {
          if (typeof result!=='object'||result===null||types.isProxy(result)) throw new IntegrityViolation();
          const descriptor=Object.getOwnPropertyDescriptor(result,'rows');
          if (!descriptor||!('value' in descriptor)) throw new IntegrityViolation();
          return native_array(descriptor.value,0,max).map(row=>native_array(row,0,32));
        } catch (error) { if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error; }
      }};
      try {
        await bounded(client.query({text:'BEGIN ISOLATION LEVEL READ COMMITTED',rowMode:'array'}),lease);
        begun=true;
        await bounded(client.query({text:'SET LOCAL search_path=pg_catalog',rowMode:'array'}),lease);
        let profile:RecoverySchemaProfile;
        try{profile=recovery_profile(await tx.query(AUTHORITY_HISTORY_SQL,undefined,5));}
        catch(error){if(error instanceof IntegrityViolation)throw new UnsupportedCapability();throw error;}
        if(this.#securityGuardAdmitted&&profile!=='security_guard'||!initializing&&profile!==this.#profile
          ||expectedProfile!==undefined&&profile!==expectedProfile)throw new UnsupportedCapability();
        if(initializing||profile==='security_guard'){
          const catalog=profile==='security_guard'?AUTHORITY_SECURITY_GUARD_CATALOG_SQL:profile==='attestation'?AUTHORITY_ATTESTATION_CATALOG_SQL:AUTHORITY_PUBLICATION_CATALOG_SQL;
          const fingerprint=profile==='security_guard'?EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT:profile==='attestation'?EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT:EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT;
          const checks:readonly (readonly [string,boolean|string])[]=[[catalog,true],[AUTHORITY_FINGERPRINT_SQL,fingerprint],...(profile==='security_guard'?[[SECURITY_GUARD_OWNER_SQL,true] as const]:[])];
          for(const [sql,expected] of checks){
            let rows:unknown[][];
            try{rows=await tx.query(sql,undefined,1);}catch(error){if(error instanceof IntegrityViolation)throw new UnsupportedCapability();throw error;}
            if(rows.length!==1||rows[0].length!==1||rows[0][0]!==expected)throw new UnsupportedCapability();
          }
        }
        let role:unknown[][];
        try{role=await tx.query(profile==='security_guard'?RECOVERY_SECURITY_GUARD_ROLE_SQL:RECOVERY_ROLE_SQL,undefined,1);}
        catch(error){if(error instanceof IntegrityViolation)throw new UnsupportedCapability();throw error;}
        if (role.length!==1||role[0].length!==1||role[0][0]!==true) throw new UnauthorizedScope();
        await tx.query("SELECT set_config('cragkit_qdrant.backend_instance_id',$1,true)",[instance_id],1);
        const value=await body(tx,profile);
        parse_options(options);
        committing=true;
        await bounded(client.query({text:'COMMIT',rowMode:'array'}),lease);
        if (client.getTransactionStatus()!=='I') throw new ProviderUnavailable();
        committed=true;
        return value;
      } catch (error) {
        if (committing&&!committed) {
          client.release(true);
          let code:unknown;
          try { code=Object.getOwnPropertyDescriptor(error as object,'code')?.value; } catch { /* Redacted. */ }
          if (typeof code==='string'&&['23502','23503','23505','23514','40001','40P01'].includes(code)) throw safe(error,options.deadline);
          throw new CommitUnknown();
        }
        throw safe(error,options.deadline);
      } finally {
        if (begun&&!committing) {
          let clean=false;
          try {
            await bounded(client.query({text:'ROLLBACK',rowMode:'array'}),{deadline:now()+this.#resource.config.release_timeout});
            clean=client.getTransactionStatus()==='I';
          } catch { /* Destroy a connection whose cleanup is uncertain. */ }
          if (!clean) client.release(true);
        }
      }
    });
  }
  async #commit<T>(instance:string,options:LeaseOptions,body:(tx:Tx,profile:RecoverySchemaProfile)=>Promise<T>,readback:(tx:Tx,profile:RecoverySchemaProfile)=>Promise<T>,initializing=false):Promise<T> {
    let attempted:RecoverySchemaProfile|undefined;
    try { return await this.#tx(instance,options,(tx,profile)=>{attempted=profile;return body(tx,profile);},initializing); }
    catch (error) {
      if (!(error instanceof CommitUnknown)) throw error;
      if(attempted===undefined)throw new ProviderUnavailable();
      return this.#tx(instance,options,readback,initializing,attempted);
    }
  }
  async #backend(tx:Tx,instance:string,lock?:'SHARE'|'UPDATE',absent=false):Promise<Backend|null> {
    if (lock) {
      const locked=await tx.query(`SELECT instance_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1 FOR ${lock}`,[instance],2);
      if (!locked.length) { if(absent)return null;throw new ProviderUnavailable(); }
      if (locked.length!==1||locked[0].length!==1||locked[0][0]!==instance) throw new IntegrityViolation();
    }
    const rows=await tx.query('SELECT instance_id,backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1',[instance],2);
    if (!rows.length) { if(absent)return null;throw new ProviderUnavailable(); }
    if (rows.length!==1||rows[0].length!==7) throw new IntegrityViolation();
    const [id,namespace,storage,supervisor,rawEpoch,state,recovery]=rows[0];
    try {
      text(id);text(namespace);text(storage);text(supervisor);
      if (id!==instance||!['open','recovery_blocked'].includes(String(state))) throw new IntegrityViolation();
      if (state==='open'?recovery!==null:typeof recovery!=='string') throw new IntegrityViolation();
      if (recovery!==null) text(recovery);
      return Object.freeze({instance_id:id as string,backend_namespace:namespace as string,storage_identity:storage as string,
        supervisor_id:supervisor as string,epoch:db_count(rawEpoch),state:state as Backend['state'],recovery_id:recovery as string|null});
    } catch (error) { if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error; }
  }
  #identityMatches(backend:Backend,binding:Binding):void {
    if (backend.instance_id!==binding.instance_id||backend.backend_namespace!==this.#config.backend_namespace
      ||backend.storage_identity!==binding.storage_identity||backend.supervisor_id!==binding.supervisor_id) throw new IntegrityViolation();
  }
  #blocked(backend:Backend,binding:Binding):void {
    this.#identityMatches(backend,binding);
    if (backend.state!=='recovery_blocked'||backend.epoch!==binding.new_epoch||backend.recovery_id!==binding.recovery_id) throw new ProviderUnavailable();
  }
  async #owner(tx:Tx,binding:Binding,context:WriterContext,requireEpoch=true):Promise<readonly unknown[]> {
    const rows=await tx.query('SELECT instance_id,intent_id,owner_token::text,backend_epoch FROM cragkit_qdrant.document_owners WHERE (tenant_id,collection,document_id)=($1,$2,$3) FOR UPDATE',
      [context.scope.tenant_id,context.collection,context.document_id],2);
    if (!rows.length) throw new ProviderUnavailable();
    if (rows.length!==1||rows[0].length!==4) throw new IntegrityViolation();
    const row=rows[0];
    const epoch=db_count(row[3]);
    if (epoch<1||epoch>Number(binding.new_epoch)) throw new IntegrityViolation();
    if (row[0]!==binding.instance_id||row[1]!==context.intent_id||row[2]!==context.owner_token
      ||(requireEpoch&&epoch!==binding.new_epoch)) throw new ProviderUnavailable();
    return row;
  }
  async initialize(rawOptions:unknown):Promise<void> {
    const options=parse_options(rawOptions);
    await this.#work(options,async (lease,session)=>{
      this.#ready=false;this.#profile=null;
      let selected:RecoverySchemaProfile|null=null;
      const local=control(this.#supervisor);
      if (local.backend_namespace!==this.#config.backend_namespace) throw new UnsupportedCapability();
      const verify=async(tx:Tx,profile:RecoverySchemaProfile)=>{
        if(selected!==null&&profile!==selected)throw new UnsupportedCapability();
        const backend=await this.#backend(tx,String(local.instance_id));
        this.#identityMatches(backend!,local);
        if (local.recovery===null) {
          const expectedEpoch=Number(local.epoch)+(backend!.state==='recovery_blocked'?1:0);
          if (backend!.epoch!==expectedEpoch) throw new ProviderUnavailable();
        } else {
          const recovery=fields(local.recovery,['recovery_id','old_epoch','new_epoch']);
          if (backend!.epoch!==recovery.new_epoch
            ||![recovery.old_epoch,recovery.new_epoch].includes(local.epoch)) throw new ProviderUnavailable();
          if (backend!.state==='recovery_blocked') {
            if (backend!.recovery_id!==recovery.recovery_id) throw new ProviderUnavailable();
          } else if (!local.sealed||local.epoch!==recovery.new_epoch) {
            throw new ProviderUnavailable();
          }
        }
        return backend!;
      };
      const verified=await this.#commit(String(local.instance_id),lease,async(tx,profile)=>{
        selected=profile;
        const existing=await this.#backend(tx,String(local.instance_id),undefined,true);
        if (!existing) {
          if (local.epoch!==1||local.recovery!==null||local.sealed||!local.alive) throw new ProviderUnavailable();
          await tx.query('INSERT INTO cragkit_qdrant.backend_instances(instance_id,backend_namespace,storage_identity,supervisor_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING',
            [local.instance_id,local.backend_namespace,local.storage_identity,local.supervisor_id],0);
        }
        return verify(tx,profile);
      },verify,true);
      if (verified.state==='recovery_blocked') session.block_ordinary();
      this.#identity=local;
      if(selected===null)throw new UnsupportedCapability();
      this.#profile=selected;this.#ready=true;
      if(selected==='security_guard')this.#securityGuardAdmitted=true;
    },true);
  }
  async recover(rawRecovery:unknown,rawOptions:unknown):Promise<unknown> {
    const recovery_id=text(rawRecovery),options=parse_options(rawOptions);
    return this.#work(options,async (lease,session)=>{
      const local=control(this.#supervisor);
      if (local.recovery!==null
        &&fields(local.recovery,['recovery_id','old_epoch','new_epoch']).recovery_id!==recovery_id) {
        throw new ProviderUnavailable();
      }
      session.block_ordinary();
      const inspect=async(tx:Tx)=>{
        const backend=(await this.#backend(tx,String(local.instance_id),'UPDATE'))!;
        this.#identityMatches(backend,local);
        if (backend.state!=='recovery_blocked'||backend.recovery_id!==recovery_id||backend.epoch<2) throw new ProviderUnavailable();
        const prior=local.recovery===null?null:fields(local.recovery,['recovery_id','old_epoch','new_epoch']);
        if (prior) {
          if (prior.recovery_id!==recovery_id||prior.old_epoch!==backend.epoch-1||prior.new_epoch!==backend.epoch
            ||![backend.epoch-1,backend.epoch].includes(Number(local.epoch))) throw new ProviderUnavailable();
        } else if (local.epoch!==backend.epoch-1) throw new ProviderUnavailable();
        return {recovery_id,old_epoch:backend.epoch-1,new_epoch:backend.epoch};
      };
      const blocked=await this.#commit(String(local.instance_id),lease,async tx=>{
        const backend=(await this.#backend(tx,String(local.instance_id),'UPDATE'))!;
        this.#identityMatches(backend,local);
        if (backend.state==='open') {
          if (local.recovery!==null||local.sealed||local.epoch!==backend.epoch||backend.epoch===Number.MAX_SAFE_INTEGER) throw new ProviderUnavailable();
          await tx.query("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=epoch+1,recovery_id=$2 WHERE instance_id=$1",
            [local.instance_id,recovery_id],0);
        }
        return inspect(tx);
      },inspect);
      const proof=await session.recover(blocked,lease);
      const proven=physical(this.#supervisor.recovery_binding(proof));
      if (proven.instance_id!==local.instance_id||proven.storage_identity!==local.storage_identity||proven.supervisor_id!==local.supervisor_id
        ||proven.recovery_id!==recovery_id||proven.old_epoch!==blocked.old_epoch||proven.new_epoch!==blocked.new_epoch) throw new IntegrityViolation();
      return proof;
    });
  }
  async advance_owner(proof:unknown,rawContext:unknown,rawOptions:unknown):Promise<Readonly<{owner_token:string;backend_epoch:number}>> {
    const options=parse_options(rawOptions),context=parse_context(rawContext);
    return this.#work(options,async lease=>{
      const binding=physical(this.#supervisor.recovery_binding(proof));
      const verify=async(tx:Tx)=>{
        this.#blocked((await this.#backend(tx,String(binding.instance_id),'SHARE'))!,binding);
        await this.#owner(tx,binding,context);
        return Object.freeze({owner_token:context.owner_token,backend_epoch:Number(binding.new_epoch)});
      };
      return this.#commit(String(binding.instance_id),lease,async tx=>{
        this.#blocked((await this.#backend(tx,String(binding.instance_id),'SHARE'))!,binding);
        await this.#owner(tx,binding,context,false);
        await tx.query('UPDATE cragkit_qdrant.document_owners SET backend_epoch=$4 WHERE (tenant_id,collection,document_id)=($1,$2,$3)',
          [context.scope.tenant_id,context.collection,context.document_id,binding.new_epoch],0);
        return verify(tx);
      },verify);
    });
  }

  async #dispatchCommit<T>(instance:string,options:LeaseOptions,mutate:(tx:Tx)=>Promise<T>,confirm:(tx:Tx)=>Promise<T|null>,beforeRetry:()=>Promise<void>):Promise<T> {
    try{return await this.#tx(instance,options,mutate);}
    catch(error){
      if(!(error instanceof CommitUnknown))throw error;
      parse_options(options);
      const found=await this.#tx(instance,options,confirm);if(found!==null)return found;
      await beforeRetry();parse_options(options);
      try{return await this.#tx(instance,options,mutate);}
      catch(retry){
        if(!(retry instanceof CommitUnknown))throw retry;
        parse_options(options);const final=await this.#tx(instance,options,confirm);
        if(final===null)throw new ProviderUnavailable();return final;
      }
    }
  }
  async #dispatchIntent(tx:Tx,binding:Binding,context:WriterContext,plan?:RecoveryDispatchPlanData):Promise<readonly unknown[]> {
    this.#blocked((await this.#backend(tx,String(binding.instance_id),'SHARE'))!,binding);
    await this.#owner(tx,binding,context);
    const rows=await tx.query('SELECT instance_id,action,state,manifest_sha256,revision_id,generation_id,expected_active_generation_id,expected_authorization_revision,expected_mutation_epoch FROM cragkit_qdrant.publication_intents WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4)',
      [context.scope.tenant_id,context.collection,context.document_id,context.intent_id],2);
    if(rows.length!==1||rows[0].length!==9)throw new IntegrityViolation();
    const intent=rows[0];if(intent[0]!==binding.instance_id||intent[1]!=='stage')throw new UnsupportedCapability();
    if(!['writing','prepared'].includes(String(intent[2])))throw new ProviderUnavailable();
    if(plan&&!same([...intent.slice(3,8),db_count(intent[8])],[plan.manifest_sha256,plan.revision_id,plan.generation_id,plan.expected_active_generation_id,
      plan.expected_authorization_revision,plan.expected_mutation_epoch]))throw new IntegrityViolation();
    return intent;
  }
  async #dispatchRows(tx:Tx,binding:Binding,context:WriterContext,expected:ReadonlySet<string>):Promise<number> {
    const target=[context.scope.tenant_id,context.collection,context.document_id,context.intent_id];
    const rows=await tx.query('SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,state,completion_sha256,request_sha256 FROM cragkit_qdrant.dispatch_journal WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4) ORDER BY sequence LIMIT 257',target,257);
    if(rows.length>256)throw new IntegrityViolation();
    const ids=new Set<string>(),sequences=new Set<number>();let maximum=0;
    for(const row of rows){
      if(row.length!==11)throw new IntegrityViolation();
      const id=text(row[0]),sequence=db_count(row[2]),epoch=db_count(row[4]);text(row[5]);digest(row[10]);
      if(ids.has(id)||sequences.has(sequence)||sequence<1||sequence>256||epoch<1||epoch>Number(binding.new_epoch)
        ||row[1]!==binding.instance_id||row[3]!==context.owner_token||row[6]!=='complete_point_upsert'||typeof row[7]!=='boolean')throw new IntegrityViolation();
      if(row[8]==='settled'){digest(row[9]);}else{
        if(!['reserved','dispatched','unknown'].includes(String(row[8]))||row[9]!==null)throw new IntegrityViolation();
        if(row[5]===binding.credential_generation)throw new ProviderUnavailable();
      }
      ids.add(id);sequences.add(sequence);maximum=Math.max(maximum,sequence);
    }
    const points=await tx.query('SELECT dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id::text FROM cragkit_qdrant.dispatch_points WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4) LIMIT 2049',target,2049);
    if(points.length>2048)throw new IntegrityViolation();
    const memberships=new Map([...ids].map(id=>[id,new Set<string>()]));
    for(const row of points){
      if(row.length!==5)throw new IntegrityViolation();const id=text(row[0]),point=uuid(row[4]),set=memberships.get(id);
      if(!set||set.has(point)||!expected.has(point)||row[1]!==this.#config.backend_namespace||row[2]!==this.#config.physical_collection
        ||row[3]!==this.#config.collection_incarnation)throw new IntegrityViolation();set.add(point);
    }
    for(const set of memberships.values())if(set.size<1||set.size>8)throw new IntegrityViolation();
    const foreign=await tx.query("SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND intent_id<>$4 AND state<>'settled' LIMIT 1",target,1);
    if(foreign.length)throw new ProviderUnavailable();
    return maximum;
  }
  async #confirmDispatch(tx:Tx,plan:RecoveryDispatchPlanData):Promise<Readonly<{state:string;completion:string|null}>|null> {
    const context=plan.context,binding=plan.physical_binding;await this.#dispatchIntent(tx,binding,context,plan);
    const target=[context.scope.tenant_id,context.collection,context.document_id,context.intent_id,plan.attempt_binding.dispatch_id];
    const rows=await tx.query('SELECT instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,request_sha256,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=($1,$2,$3,$4,$5)',target,2);
    if(rows.length===0)return null;if(rows.length!==1||rows[0].length!==10)throw new IntegrityViolation();
    const row=rows[0];
    if(!same([row[0],db_count(row[1]),row[2],db_count(row[3]),...row.slice(4,8)],[binding.instance_id,plan.sequence,context.owner_token,binding.new_epoch,
      plan.attempt_binding.credential_generation,'complete_point_upsert',true,plan.request_sha256]))throw new IntegrityViolation();
    const points=await tx.query('SELECT backend_namespace,physical_collection,collection_incarnation,point_id::text FROM cragkit_qdrant.dispatch_points WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=($1,$2,$3,$4,$5) LIMIT 9',target,9);
    if(points.length!==plan.point_ids.length||new Set(points.map(row=>row[3])).size!==points.length)throw new IntegrityViolation();
    for(const point of points)if(point.length!==4||point[0]!==this.#config.backend_namespace||point[1]!==this.#config.physical_collection
      ||point[2]!==this.#config.collection_incarnation||!plan.point_ids.includes(uuid(point[3])))throw new IntegrityViolation();
    const state=text(row[8]);if(!['reserved','dispatched','unknown','settled'].includes(state))throw new IntegrityViolation();
    if(state==='settled')digest(row[9]);else if(row[9]!==null)throw new IntegrityViolation();
    return Object.freeze({state,completion:row[9] as string|null});
  }
  async #reserveRecovery(plan:RecoveryDispatchPlanData,options:LeaseOptions,beforeRetry:()=>Promise<void>):Promise<void> {
    const binding=plan.physical_binding,ctx=plan.context,instance=String(binding.instance_id);
    const confirm=async(tx:Tx)=>{const row=await this.#confirmDispatch(tx,plan);if(row&&row.state!=='reserved')throw new ProviderUnavailable();return row?true:null;};
    await this.#dispatchCommit(instance,options,async tx=>{
      await this.#dispatchIntent(tx,binding,ctx,plan);
      if(await confirm(tx))return true;
      const claims=await tx.query('SELECT backend_namespace,physical_collection,collection_incarnation,point_id::text,instance_id,revision_id,generation_id FROM cragkit_qdrant.point_claims WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND point_id=ANY($4::uuid[]) LIMIT 9',
        [ctx.scope.tenant_id,ctx.collection,ctx.document_id,plan.point_ids],9);
      if(claims.length!==plan.point_ids.length||new Set(claims.map(row=>row[3])).size!==claims.length)throw new IntegrityViolation();
      for(const row of claims)if(row.length!==7||row[0]!==this.#config.backend_namespace||row[1]!==this.#config.physical_collection
        ||row[2]!==this.#config.collection_incarnation||!plan.point_ids.includes(uuid(row[3]))||row[4]!==instance||row[5]!==plan.revision_id||row[6]!==plan.generation_id)throw new IntegrityViolation();
      const values=[ctx.scope.tenant_id,ctx.collection,ctx.document_id,ctx.intent_id,plan.attempt_binding.dispatch_id,
        instance,plan.sequence,ctx.owner_token,binding.new_epoch,plan.attempt_binding.credential_generation,'complete_point_upsert',true,Buffer.from(plan.request_bytes),plan.request_sha256];
      await tx.query('INSERT INTO cragkit_qdrant.dispatch_journal (tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token,backend_epoch,credential_generation,operation,recovery,request_bytes,request_sha256) VALUES($1,$2,$3,$4,$5,$6,$7,$8::uuid,$9,$10,$11,$12,$13,$14)',values,0);
      for(const id of plan.point_ids)await tx.query('INSERT INTO cragkit_qdrant.dispatch_points (tenant_id,collection,document_id,intent_id,dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::uuid)',
        [ctx.scope.tenant_id,ctx.collection,ctx.document_id,ctx.intent_id,plan.attempt_binding.dispatch_id,this.#config.backend_namespace,this.#config.physical_collection,this.#config.collection_incarnation,id],0);
      if(!(await confirm(tx)))throw new IntegrityViolation();return true;
    },confirm,beforeRetry);
  }
  async #markRecovery(plan:RecoveryDispatchPlanData,state:'dispatched'|'unknown'|'settled',options:LeaseOptions,completion:string|null,beforeRetry:()=>Promise<void>):Promise<void> {
    const instance=String(plan.physical_binding.instance_id),ctx=plan.context;
    const confirm=async(tx:Tx)=>{
      const row=await this.#confirmDispatch(tx,plan);if(!row)throw new IntegrityViolation();
      if(row.state===state){if(row.completion!==completion)throw new IntegrityViolation();return true;}
      if(row.state!==(state==='dispatched'?'reserved':'dispatched'))throw new ProviderUnavailable();return null;
    };
    await this.#dispatchCommit(instance,options,async tx=>{
      if(await confirm(tx))return true;
      const changed=await tx.query('UPDATE cragkit_qdrant.dispatch_journal SET state=$6,completion_sha256=$7 WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=($1,$2,$3,$4,$5) RETURNING dispatch_id',
        [ctx.scope.tenant_id,ctx.collection,ctx.document_id,ctx.intent_id,plan.attempt_binding.dispatch_id,state,completion],1);
      if(changed.length!==1||changed[0][0]!==plan.attempt_binding.dispatch_id)throw new IntegrityViolation();
      if(!(await confirm(tx)))throw new IntegrityViolation();return true;
    },confirm,beforeRetry);
  }
  async dispatch_stage_recovery(proof:unknown,rawContext:unknown,authorize:unknown,rawOptions:unknown,inputBudget?:VerificationBudget):Promise<Readonly<{batches:number;points:number}>> {
    const context=parse_context(rawContext),options=parse_options(rawOptions),budget=verification_budget(inputBudget);
    if(typeof authorize!=='function'||types.isProxy(authorize))throw new InvalidRequest();
    return this.#work(options,async(lease,session)=>{
      if(this.#profile!=='attestation'&&this.#profile!=='security_guard')throw new UnsupportedCapability();
      const lifetime={active:true};let inspection:ReturnType<SupervisorControlSession['recovery_transport_for']>|undefined;
      const authorizeCurrent=async()=>{
        parse_options(lease);const pending=authorize(context.scope,context.collection,context.document_id);
        if(!(pending instanceof Promise))throw new InvalidRequest();
        const allowed=await bounded(pending,lease);parse_options(lease);
        if(typeof allowed!=='boolean')throw new InvalidRequest();if(!allowed)throw new UnauthorizedScope();
      };
      try{
        await authorizeCurrent();
        const binding=physical(this.#supervisor.recovery_binding(proof));
        const preflight=await this.#writer.preflight_repair(context,lease);parse_options(lease);
        if(!['writing','prepared'].includes(preflight.intent.state))throw preflight.intent.state==='denied'?new UnauthorizedScope():new ProviderUnavailable();
        const projection=await this.#writer.project_stage(context,binding,lease);parse_options(lease);
        const expected=projection_data(projection,this.#writer);
        const inspectAttempt=session.issue_recovery_attempt(proof,{intent_id:context.intent_id,owner_token:context.owner_token,
          epoch:binding.new_epoch,recovery_id:binding.recovery_id,dispatch_id:'recovery-inspect-'+randomUUID()},lease);
        inspection=session.recovery_transport_for(inspectAttempt);
        const missing=await inspect_missing_readback(inspection,this.#config.physical_collection,expected,lease,budget);parse_options(lease);
        await inspection.close();inspection=undefined;parse_options(lease);
        await this.#writer.validate_projection(projection,lease);parse_options(lease);
        const expectedIds=new Set(expected.points.map(point=>point.point_id));
        const maximum=await this.#tx(String(binding.instance_id),lease,async tx=>{
          await this.#dispatchIntent(tx,binding,context);
          return this.#dispatchRows(tx,binding,context,expectedIds);
        });parse_options(lease);
        if(!missing.length)return Object.freeze({batches:0,points:0});
        const batches=Math.ceil(missing.length/8);
        if(maximum+batches+(preflight.intent.state==='writing'?Math.ceil(expected.points.length/8):0)>256)throw new ProviderUnavailable();
        let completed=0;
        for(let start=0;start<missing.length;start+=8){
          if(budget.remaining_bytes<=0)throw new ProviderUnavailable();
          await authorizeCurrent();
          const attempt=session.issue_recovery_attempt(proof,{intent_id:context.intent_id,owner_token:context.owner_token,
            epoch:binding.new_epoch,recovery_id:binding.recovery_id,dispatch_id:'recovery-dispatch-'+randomUUID()},lease);
          const attemptBinding=metadata(this.#supervisor.attempt_binding(attempt));
          const authorization=Object.freeze({}),sequence=maximum+completed+1;
          dispatchAuthorizations.set(authorization,Object.freeze({issuer:this,writer:this.#writer,supervisor:this.#supervisor,proof,attempt,
            data:Object.freeze({context,physical_binding:binding,attempt_binding:attemptBinding,sequence}),deadline:lease.deadline,signal:lease.signal,lifetime}));
          const plan=await this.#writer.project_recovery_dispatch(authorization,context,missing.slice(start,start+8),lease);parse_options(lease);
          const data=recovery_dispatch_plan_data(plan,authorization,this.#writer,lease);
          const beforeRetry=async()=>{await authorizeCurrent();await this.#writer.validate_recovery_dispatch(plan,authorization,lease);parse_options(lease);};
          await authorizeCurrent();await this.#writer.validate_recovery_dispatch(plan,authorization,lease);parse_options(lease);
          await this.#reserveRecovery(data,lease,beforeRetry);parse_options(lease);
          await authorizeCurrent();await this.#writer.validate_recovery_dispatch(plan,authorization,lease);parse_options(lease);
          await this.#markRecovery(data,'dispatched',lease,null,beforeRetry);parse_options(lease);
          await authorizeCurrent();await this.#writer.validate_recovery_dispatch(plan,authorization,lease);parse_options(lease);
          recovery_dispatch_authorization(authorization,this.#writer,lease);
          const handle=session.recovery_transport_for(attempt);
          try{
            let raw:readonly number[];
            try{raw=await handle.request('PUT','/collections/'+this.#config.physical_collection+'/points?wait=true&ordering=strong',
              {...lease,body:data.request_bytes});parse_options(lease);}
            catch(error){try{parse_options(lease);await this.#markRecovery(data,'unknown',lease,null,beforeRetry);}catch{/* Dispatched remains uncertain. */}throw error;}
            let ackBytes:Buffer;
            try{ackBytes=Buffer.from(native_array(raw,1,1048576).map(value=>count(value,0,255)));}
            catch{throw new IntegrityViolation();}
            const decoded=parse_response(ackBytes);
            if(typeof decoded!=='object'||decoded===null||Array.isArray(decoded))throw new IntegrityViolation();
            const response=decoded as Data,body=response.result;
            if(response.status!=='ok'||typeof body!=='object'||body===null||Array.isArray(body))throw new IntegrityViolation();
            const result=body as Data;
            if(result.status!=='completed'||Object.keys(result).some(key=>!['status','operation_id'].includes(key))){
              await this.#markRecovery(data,'unknown',lease,null,beforeRetry);throw new IntegrityViolation();
            }
            if(Object.hasOwn(result,'operation_id')){try{count(result.operation_id);}catch{throw new IntegrityViolation();}}
            const completion=hash(Buffer.from(raw));
            await handle.close();parse_options(lease);
            recovery_dispatch_authorization(authorization,this.#writer,lease);
            await authorizeCurrent();await this.#writer.validate_recovery_dispatch(plan,authorization,lease);parse_options(lease);
            await this.#markRecovery(data,'settled',lease,completion,beforeRetry);parse_options(lease);
          }finally{await handle.close();}
          completed++;
        }
        return Object.freeze({batches:completed,points:missing.length});
      }finally{
        lifetime.active=false;
        // An application callback receives no session capability. The session
        // itself still drains every admitted privileged operation on exit.
        if(inspection)await inspection.close();
      }
    });
  }

  async settle_retired(proof:unknown,receipt:unknown,rawOptions:unknown):Promise<Readonly<{settled_count:number}>> {
    const options=parse_options(rawOptions);
    return this.#work(options,async lease=>{
      const binding=physical(this.#supervisor.recovery_binding(proof));
      const evidence=receipt_data(receipt,this.#verifier);
      const projection=projection_data(evidence.projection,this.#writer);
      if (!same(evidence.physical_binding,binding)) throw new UnsupportedCapability();
      const context=parse_context(evidence.context);
      const expected=new Set(projection.points.map(point=>point.point_id));
      const completion=digest(evidence.readback_sha256);
      // The writer owns source authority. Never retain a supervisor SQL lease here.
      await this.#writer.validate_projection(evidence.projection,lease);
      if (!same(physical(this.#supervisor.recovery_binding(proof)),binding)) throw new UnsupportedCapability();
      let attempted:readonly string[]=[];
      const inspect=async (tx:Tx,reconcile=false):Promise<readonly string[]>=>{
        this.#blocked((await this.#backend(tx,String(binding.instance_id),'SHARE'))!,binding);
        await this.#owner(tx,binding,context);
        const target=[context.scope.tenant_id,context.collection,context.document_id,context.intent_id];
        const intents=await tx.query('SELECT instance_id,action,manifest_sha256,revision_id,generation_id FROM cragkit_qdrant.publication_intents WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4)',target,2);
        if (intents.length!==1||intents[0].length!==5) throw new IntegrityViolation();
        const intent=intents[0];
        if (intent[1]!=='stage') throw new UnsupportedCapability();
        if (intent[0]!==binding.instance_id||intent[2]!==projection.manifest_sha256
          ||intent[3]!==projection.revision_id||intent[4]!==projection.generation_id) throw new IntegrityViolation();
        const rows=await tx.query(`SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4) AND ${reconcile?'dispatch_id=ANY($5::text[])':"state<>'settled'"} ORDER BY sequence LIMIT 257`,reconcile?[...target,attempted]:target,257);
        if (rows.length>256) throw new IntegrityViolation();
        const ids:string[]=[];
        const sequences=new Set<number>();
        for (const row of rows) {
          if (row.length!==9) throw new IntegrityViolation();
          const id=text(row[0]),sequence=db_count(row[2]),epoch=db_count(row[4]);
          if (ids.includes(id)||sequences.has(sequence)||sequence<1||sequence>256||epoch<1||epoch>Number(binding.new_epoch)
            ||row[1]!==binding.instance_id||row[3]!==context.owner_token) throw new IntegrityViolation();
          text(row[5]);
          if (row[5]===binding.credential_generation) throw new ProviderUnavailable();
          if (row[6]!=='complete_point_upsert') throw new UnsupportedCapability();
          if (reconcile) {
            if (row[7]!=='settled'||row[8]!==completion) throw new ProviderUnavailable();
          } else if (!['reserved','dispatched','unknown'].includes(String(row[7]))||row[8]!==null) throw new IntegrityViolation();
          ids.push(id);
          sequences.add(sequence);
        }
        if (reconcile&&ids.length!==attempted.length) throw new ProviderUnavailable();
        if (!ids.length) return Object.freeze(ids);
        const points=await tx.query('SELECT dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id::text FROM cragkit_qdrant.dispatch_points WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4) AND dispatch_id=ANY($5::text[]) LIMIT 2049',[...target,ids],2049);
        if (points.length>2048) throw new IntegrityViolation();
        const membership=new Map(ids.map(id=>[id,new Set<string>()]));
        for (const row of points) {
          if (row.length!==5) throw new IntegrityViolation();
          const id=text(row[0]),point=uuid(row[4]),set=membership.get(id);
          if (!set||set.has(point)||!expected.has(point)||row[1]!==this.#config.backend_namespace
            ||row[2]!==this.#config.physical_collection||row[3]!==this.#config.collection_incarnation) throw new IntegrityViolation();
          set.add(point);
        }
        for (const set of membership.values()) if (set.size<1||set.size>8) throw new IntegrityViolation();
        return Object.freeze(ids);
      };
      return this.#commit(String(binding.instance_id),lease,async tx=>{
        attempted=await inspect(tx);
        for (const id of attempted) {
          const changed=await tx.query("UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=$6 WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=($1,$2,$3,$4,$5) RETURNING dispatch_id",
            [context.scope.tenant_id,context.collection,context.document_id,context.intent_id,id,completion],1);
          if (changed.length!==1||changed[0][0]!==id) throw new IntegrityViolation();
        }
        return Object.freeze({settled_count:attempted.length});
      },async tx=>{
        await inspect(tx,true);
        return Object.freeze({settled_count:attempted.length});
      });
    });
  }

  async reopen(proof:unknown,rawOptions:unknown):Promise<Readonly<{state:'open';epoch:number}>> {
    const options=parse_options(rawOptions);
    return this.#work(options,async (lease,session)=>{
      // Closing native issuance precedes the global SQL pending-work check.
      const barrier=await session.seal_recovery(proof,lease);
      const binding=physical(this.#supervisor.barrier_binding(barrier));
      const inspect=async (tx:Tx,requireOpen:boolean):Promise<Backend>=>{
        const backend=(await this.#backend(tx,String(binding.instance_id),'UPDATE'))!;
        this.#identityMatches(backend,binding);
        if (backend.epoch!==binding.new_epoch) throw new ProviderUnavailable();
        if (requireOpen) {
          if (backend.state!=='open'||backend.recovery_id!==null) throw new ProviderUnavailable();
        } else if (backend.state==='recovery_blocked') {
          if (backend.recovery_id!==binding.recovery_id) throw new ProviderUnavailable();
        } else if (backend.recovery_id!==null) throw new IntegrityViolation();
        const pending=await tx.query("SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE instance_id=$1 AND state<>'settled' LIMIT 1",[binding.instance_id],1);
        if (pending.length) throw new ProviderUnavailable();
        return backend;
      };
      await this.#commit(String(binding.instance_id),lease,async tx=>{
        const backend=await inspect(tx,false);
        if (backend.state==='recovery_blocked') await tx.query("UPDATE cragkit_qdrant.backend_instances SET state='open',recovery_id=NULL WHERE instance_id=$1",[binding.instance_id],0);
        await inspect(tx,true);
      },async tx=>{await inspect(tx,true);});
      const token:SQLSettlement=Object.freeze({});
      settlements.set(token,Object.freeze({issuer:this,supervisor:this.#supervisor,barrier,binding}));
      session.finish_recovery(barrier,token,lease);
      return Object.freeze({state:'open' as const,epoch:Number(binding.new_epoch)});
    });
  }

  close():Promise<void> {
    if (this.#closing) return this.#closing;
    this.#closed=true;
    this.#active?.controller.abort();
    this.#closing=(async()=>{
      const active=this.#active;
      if (active) await bounded(active.done,{deadline:now()+this.#resource.config.release_timeout});
    })();
    return this.#closing;
  }
}
