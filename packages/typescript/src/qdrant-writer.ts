/** Native SQL authority only. No Qdrant transport or write-authorizer callback. */
import { types } from 'node:util';
import { PoolResource, bounded, now, type PgClient, type LeaseOptions } from './postgres-pool.js';
import { DeadlineExceeded, EmbeddingProfileMismatch, IndexNotReady, IntegrityViolation, InvalidRequest,
  ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from './errors.js';
import { AUTHORITY_FINGERPRINT_SQL, AUTHORITY_HISTORY_SQL, AUTHORITY_PUBLICATION_HISTORY,
  AUTHORITY_PUBLICATION_CATALOG_SQL, EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,
  AUTHORITY_ATTESTATION_HISTORY,AUTHORITY_ATTESTATION_CATALOG_SQL,EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT,publication_schema_profile,type PublicationSchemaProfile } from './qdrant-authority.js';
import {attestation_receipt_data,publication_verifier_controller,type QdrantPublicationVerifier} from './qdrant-publication-verification.js';
import {require_publication_finalization} from './qdrant-publication-worker.js';
import { encode_manifest, encode_stage_intent, restore_dense_replay, restore_sparse_replay } from './qdrant-manifest.js';
import { same, point_id, parse_response, type QdrantConfig } from './qdrant-contract.js';
import { type TrustedScope } from './requests.js';
import { config as parseConfig, context as parseContext, options as parseOptions, scope as parseScope,
  stage_data, issue_verified_stage, operation as parseOperation, metadata, native_array, db_bytes, db_count, db_json,
  digest, count, text, uuid, hash, DispatchOptionsSchema, type Data, type WriterContext, type StagePlan, type StageData } from './qdrant-writer-contract.js';
export { prepare_stage } from './qdrant-writer-contract.js';

const INTENT_COLUMNS = ['action','state','payload_sha256','manifest_sha256','revision_id','generation_id',
  'authority_committed','replica_complete','purge_complete'];
const INTENT_PRIVATE = [...INTENT_COLUMNS, 'payload_bytes','manifest_bytes','expected_active_generation_id',
  'expected_authorization_revision','expected_mutation_epoch','instance_id'];
const TARGET = ['tenant_id','collection','document_id'];
const MEMBER_COLUMNS = ['revision_id','generation_id','chunk_id','point_id','start_byte','end_byte','source_sha256','text_sha256','excerpt_utf8'];
const CLAIM_COLUMNS = ['backend_namespace','physical_collection','collection_incarnation','point_id','instance_id',
  ...TARGET,'revision_id','generation_id','chunk_id','source_sha256','text_sha256','start_byte','end_byte',
  'dense_profile','sparse_profile','dense_input_sha256','sparse_input_sha256'];
const REPLAY_COLUMNS = [...TARGET,'revision_id','generation_id','chunk_id','backend_namespace','physical_collection',
  'collection_incarnation','point_id','dense_blob','dense_blob_sha256','sparse_blob','sparse_blob_sha256'];
const JOURNAL_COLUMNS = ['dispatch_id','sequence','owner_token','backend_epoch','credential_generation','operation',
  'recovery','request_bytes','request_sha256','state','completion_sha256'];
const DOCUMENT_COLUMNS = ['active_generation_id','principal_ids','grant_ids','authorization_revision','mutation_epoch','language','kind','tag','tombstoned'];
export type IntentView = Readonly<{action:string;state:string;payload_sha256:string;manifest_sha256:string|null;
  revision_id:string|null;generation_id:string|null;authority_committed:boolean;replica_complete:boolean;purge_complete:boolean}>;
export type DispatchView = Readonly<{dispatch_id:string;request_bytes:readonly number[];request_sha256:string;
  point_ids:readonly string[];operation:string;state:string}>;
export type ManagerBackend=Readonly<{instance_id:string;backend_namespace:string;storage_identity:string;supervisor_id:string;
  epoch:number;state:'open'|'recovery_blocked';recovery_id:string|null}>;
export type ManagerOwner=Readonly<{instance_id:string;intent_id:string;owner_token:string;backend_epoch:number}>;
export type ManagerSnapshot=Readonly<{intent:IntentView|null;document:Readonly<{active_generation_id:string|null;
  authorization_revision:string;mutation_epoch:number;tombstoned:boolean}>|null;backend:ManagerBackend;
  owner:ManagerOwner|null;max_sequence:number;pending:boolean}>;
export type PublicationAdmission=Readonly<{intent:IntentView;owner:Readonly<{owner_token:string;backend_epoch:number}>|null}>;
export type DispatchStatus=Readonly<{dispatch_id:string;sequence:number;owner_token:string;backend_epoch:number;
  credential_generation:string;operation:string;state:string;completion_sha256:string|null;request_sha256:string;point_ids:readonly string[]}>;
export type PreparationMetadata=Readonly<{owner_token:string;backend_epoch:number;authorization_revision:string;mutation_epoch:number;manifest_sha256:string;readback_sha256:string}>;
export type PreparationAttestation=Readonly<{tenant_id:string;collection:string;document_id:string;intent_id:string;instance_id:string;owner_token:string;backend_epoch:number;authorization_revision:string;mutation_epoch:number;manifest_sha256:string;expected_active_generation_id:string|null;credential_generation:string;verification_id:string;readback_sha256:string}>;
const ATTESTATION_COLUMNS=['tenant_id','collection','document_id','intent_id','instance_id','owner_token','backend_epoch','authorization_revision','mutation_epoch','manifest_sha256','expected_active_generation_id','credential_generation','verification_id','readback_sha256'] as const;
type WriterRegistration=Readonly<{resource:PoolResource;config:QdrantConfig;instance_id:string}>;
const writerRegistrations=new WeakMap<object,WriterRegistration>();

/** Constructor identity only: this metadata grants no readiness or write authority. */
export function writer_binding(input:unknown):Readonly<{config:QdrantConfig;instance_id:string}> {
  if(typeof input!=='object'||input===null||types.isProxy(input)
    ||Object.getPrototypeOf(input)!==PostgresQdrantWriter.prototype)throw new InvalidRequest();
  const original=writerRegistrations.get(input);
  if(!original)throw new InvalidRequest();
  return Object.freeze({config:original.config,instance_id:original.instance_id});
}
export type ExpectedProjection=Readonly<Record<never,never>>;
export type ProjectionPoint=Readonly<{point_id:string;payload:Readonly<Data>;dense:ReturnType<typeof restore_dense_replay>;sparse:ReturnType<typeof restore_sparse_replay>|null}>;
export type ProjectionData=Readonly<{context:WriterContext;physical_binding:Readonly<Data>;manifest_sha256:string;
  revision_id:string;generation_id:string;points:readonly ProjectionPoint[];tombstoned:boolean;authorization_revision:string;
  mutation_epoch:number;active_generation_id:string|null;principal_ids:readonly string[];grant_ids:readonly string[];
  language:string|null;kind:string|null;tag:string|null}>;
const projections=new WeakMap<object,Readonly<{issuer:PostgresQdrantWriter;data:ProjectionData}>>();
export function projection_data(input:unknown,writer:PostgresQdrantWriter):ProjectionData{
  if(typeof input!=='object'||input===null)throw new InvalidRequest();
  const found=projections.get(input);
  if(!found||found.issuer!==writer)throw new InvalidRequest();
  return found.data;
}
export type PublicationProjection=Readonly<Record<never,never>>;
export type PublicationProjectionData=Readonly<Omit<ProjectionData,'physical_binding'|'tombstoned'>&{
  attempt_binding:Readonly<Data>;
  tombstoned:false;
  point_ids:readonly string[];
  witness:readonly unknown[];
  encoded_bytes:readonly number[];
  readback_sha256:string;
  sha256:string;
}>;
const publicationProjections=new WeakMap<object,Readonly<{issuer:PostgresQdrantWriter;data:PublicationProjectionData}>>();

/** Nominal provenance only; a copied projection never becomes authority. */
export function publication_projection_data(input:unknown,writer:PostgresQdrantWriter):PublicationProjectionData {
  if(typeof input!=='object'||input===null)throw new InvalidRequest();
  const found=publicationProjections.get(input);
  if(!found||found.issuer!==writer)throw new InvalidRequest();
  return found.data;
}

function freeze_witness(value:unknown):unknown {
  if(Array.isArray(value)){
    for(const child of value)freeze_witness(child);
    Object.freeze(value);
  }
  return value;
}

function canonical_acl(values:readonly string[]):readonly string[] {
  return Object.freeze([...new Set(values)].sort((left,right)=>Buffer.compare(Buffer.from(left),Buffer.from(right))));
}

/** Dedicated writer capability, never a reader, owner, administrator or supervisor. */
export const WRITER_ROLE_SQL = `SELECT current_user=session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin AND NOT(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication))
 AND EXISTS(SELECT 1 FROM pg_roles capability WHERE capability.rolname='cragkit_qdrant_writer'
  AND NOT(capability.rolcanlogin OR capability.rolsuper OR capability.rolbypassrls OR capability.rolcreaterole OR capability.rolcreatedb OR capability.rolreplication)
  AND NOT EXISTS(SELECT 1 FROM pg_auth_members membership WHERE membership.member=capability.oid)
  AND pg_has_role(current_user,capability.oid,'USAGE'))
 AND NOT EXISTS(SELECT 1 FROM pg_roles WHERE pg_has_role(current_user,oid,'MEMBER') AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolname IN('cragkit_qdrant_supervisor','pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')))
 AND EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='cragkit_qdrant' AND has_schema_privilege(current_user,oid,'USAGE') AND NOT has_schema_privilege(current_user,oid,'CREATE') AND NOT pg_has_role(current_user,nspowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind IN('r','p') AND (pg_has_role(current_user,c.relowner,'MEMBER') OR has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(current_user,c.oid,'REFERENCES') OR (c.relname<>'schema_migrations' AND NOT row_security_active(c.oid))))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND
  has_table_privilege(current_user,c.oid,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','documents','document_revisions','generations','members','backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='INSERT' THEN c.relname IN ('documents','document_revisions','generations','members','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND
  has_column_privilege(current_user,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','documents','document_revisions','generations','members','backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='INSERT' THEN c.relname IN ('documents','document_revisions','generations','members','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
    OR (c.relname='members' AND a.attname='point_id') OR (c.relname='backend_instances' AND a.attname='epoch')
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_qdrant' AND has_function_privilege(current_user,p.oid,'EXECUTE') IS DISTINCT FROM (
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.supervisor_instance(text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.assert_publication(text,text,text,text)')))`;
export const WRITER_ATTESTATION_ROLE_SQL = `SELECT current_user=session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin AND NOT(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication))
 AND EXISTS(SELECT 1 FROM pg_roles capability WHERE capability.rolname='cragkit_qdrant_writer'
  AND NOT(capability.rolcanlogin OR capability.rolsuper OR capability.rolbypassrls OR capability.rolcreaterole OR capability.rolcreatedb OR capability.rolreplication)
  AND NOT EXISTS(SELECT 1 FROM pg_auth_members membership WHERE membership.member=capability.oid)
  AND pg_has_role(current_user,capability.oid,'USAGE'))
 AND NOT EXISTS(SELECT 1 FROM pg_roles WHERE pg_has_role(current_user,oid,'MEMBER') AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolname IN('cragkit_qdrant_supervisor','pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')))
 AND EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='cragkit_qdrant' AND has_schema_privilege(current_user,oid,'USAGE') AND NOT has_schema_privilege(current_user,oid,'CREATE') AND NOT pg_has_role(current_user,nspowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cragkit_qdrant' AND c.relkind IN('r','p') AND (pg_has_role(current_user,c.relowner,'MEMBER') OR has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(current_user,c.oid,'REFERENCES') OR (c.relname<>'schema_migrations' AND NOT row_security_active(c.oid))))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND
  has_table_privilege(current_user,c.oid,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','documents','document_revisions','generations','members','backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations','preparation_attestations')
   WHEN privilege='INSERT' THEN c.relname IN ('documents','document_revisions','generations','members','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations','preparation_attestations')
   WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND
  has_column_privilege(current_user,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','documents','document_revisions','generations','members','backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations','preparation_attestations')
   WHEN privilege='INSERT' THEN c.relname IN ('documents','document_revisions','generations','members','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations','preparation_attestations')
   WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
    OR (c.relname='members' AND a.attname='point_id') OR (c.relname='backend_instances' AND a.attname='epoch')
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_qdrant' AND has_function_privilege(current_user,p.oid,'EXECUTE') IS DISTINCT FROM (
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.supervisor_instance(text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.assert_publication(text,text,text,text)')))`;
const SCOPE_SQL = `SELECT set_config('cragkit_qdrant.tenant_id',$1,true),set_config('cragkit_qdrant.collection',$2,true),set_config('cragkit_qdrant.principal_id',$3,true),set_config('cragkit_qdrant.grant_ids',$4,true),set_config('cragkit_qdrant.authorization_revision',$5,true),set_config('cragkit_qdrant.writer_document_id',$6,true),set_config('cragkit_qdrant.writer_intent_id',$7,true),set_config('cragkit_qdrant.writer_owner_token',$8,true),set_config('cragkit_qdrant.backend_instance_id',$9,true)`;

function safe(error: unknown, deadline: number): Error {
  if (error instanceof DeadlineExceeded) return new DeadlineExceeded();
  if (error instanceof UnauthorizedScope) return new UnauthorizedScope();
  if (error instanceof UnsupportedCapability) return new UnsupportedCapability();
  if (error instanceof InvalidRequest) return new InvalidRequest();
  if (error instanceof IntegrityViolation) return new IntegrityViolation();
  if (error instanceof EmbeddingProfileMismatch) return new EmbeddingProfileMismatch();
  if (error instanceof IndexNotReady) return new IndexNotReady();
  if (error instanceof DOMException && error.name==='AbortError') return new DOMException('Operation aborted.','AbortError');
  let code: unknown;
  try { code=Object.getOwnPropertyDescriptor(error as object,'code')?.value; } catch { /* Never inspect error hooks. */ }
  if (code==='57014') return now()>=deadline ? new DeadlineExceeded() : new ProviderUnavailable();
  if (code==='42501') return new UnauthorizedScope();
  if (typeof code==='string' && ['42P01','42703','42883','3F000','42704'].includes(code)) return new UnsupportedCapability();
  if (typeof code==='string' && ['23503','23505','23514','23502'].includes(code)) return new IntegrityViolation();
  return new ProviderUnavailable();
}
class CommitUnknown extends Error {}
type Tx = {query:(sql:string,values?:readonly unknown[],max?:number)=>Promise<unknown[][]>};
type PointData = {claim:Data;replay:Data;dense:ReturnType<typeof restore_dense_replay>;sparse:ReturnType<typeof restore_sparse_replay>|null};
function exact(value: unknown, expected: unknown): boolean {
  if (Buffer.isBuffer(expected)) return db_bytes(value, expected.length).equals(expected);
  if (typeof expected==='number') return db_count(value)===expected;
  if (expected!==null && typeof expected==='object') return same(db_json(value),expected);
  return value===expected;
}
function intent_view(row: Data): IntentView {
  try {
    const action=text(row.action), state=text(row.state), payload_sha256=digest(row.payload_sha256);
    if(!['stage','update_authorization','tombstone','purge'].includes(action)
      ||!['staged','writing','prepared','published','conflict','denied','authority_committed','complete'].includes(state))throw new IntegrityViolation();
    const nullable=(value:unknown, hashed=false)=>value===null?null:hashed?digest(value):text(value);
    for (const key of ['authority_committed','replica_complete','purge_complete']) if(typeof row[key]!=='boolean') throw new IntegrityViolation();
    return Object.freeze({action,state,payload_sha256,manifest_sha256:nullable(row.manifest_sha256,true),
      revision_id:nullable(row.revision_id),generation_id:nullable(row.generation_id),
      authority_committed:row.authority_committed as boolean,replica_complete:row.replica_complete as boolean,purge_complete:row.purge_complete as boolean});
  } catch(error) { if(error instanceof InvalidRequest) throw new IntegrityViolation(); throw error; }
}

export class PostgresQdrantWriter {
  readonly #resource: PoolResource;
  readonly #config: QdrantConfig;
  readonly #instance: string;
  #initialized=false;
  #profile:PublicationSchemaProfile|null=null;
  #closed=false;
  #active?: {controller:AbortController;done:Promise<void>};
  #closing?: Promise<void>;
  constructor(resource: PoolResource, config: unknown, instance_id: unknown) {
    if (!(resource instanceof PoolResource)) throw new InvalidRequest();
    this.#resource=resource; this.#config=parseConfig(config); this.#instance=text(instance_id);
    writerRegistrations.set(this,Object.freeze({resource:this.#resource,config:this.#config,instance_id:this.#instance}));
  }
  async #work<T>(options: LeaseOptions, task:(options:LeaseOptions)=>Promise<T>, initialize=false):Promise<T> {
    if(this.#closed||this.#active) throw new ProviderUnavailable();
    if(!initialize&&!this.#initialized) throw new IndexNotReady();
    const controller=new AbortController();
    const onAbort=()=>controller.abort();
    options.signal?.addEventListener('abort',onAbort,{once:true});
    if(options.signal?.aborted) controller.abort();
    let finish!:()=>void;
    const done=new Promise<void>(resolve=>{finish=resolve;});
    this.#active={controller,done};
    try { return await task({deadline:options.deadline,signal:controller.signal}); }
    catch(error) { throw safe(error, options.deadline); }
    finally { options.signal?.removeEventListener('abort',onAbort); this.#active=undefined; finish(); }
  }
  async #tx<T>(context:WriterContext|null,options:LeaseOptions,body:(tx:Tx,profile:PublicationSchemaProfile)=>Promise<T>,preserveCommitCancellation=false,initializing=false):Promise<T> {
    return this.#resource.withLease(options,async(client,signal)=>{
      const lease={deadline:options.deadline,signal};
      let initialStatus:string|null;
      try{initialStatus=client.getTransactionStatus();}catch{client.release(true);throw new ProviderUnavailable();}
      if(initialStatus!=='I'){client.release(true);throw new InvalidRequest();}
      let begun=false,committed=false,commitAttempted=false;
      const tx:Tx={query:async(sql,values,max=65)=>{
        const timeout=String(Math.max(1,Math.floor(Math.min(options.deadline-now(),2147483.647)*1000)));
        await bounded(client.query({text:"SELECT set_config('statement_timeout',$1,true)",values:[timeout],rowMode:'array'}),lease);
        const result=await bounded(client.query({text:sql,values,rowMode:'array'}),lease);
        try {
          if(typeof result!=='object'||result===null||types.isProxy(result)) throw new IntegrityViolation();
          const descriptor=Object.getOwnPropertyDescriptor(result,'rows');
          if(!descriptor||!('value'in descriptor)) throw new IntegrityViolation();
          return native_array(descriptor.value,0,max).map(row=>native_array(row,0,64));
        } catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
      }};
      try {
        await bounded(client.query({text:'BEGIN ISOLATION LEVEL READ COMMITTED',rowMode:'array'}),lease); begun=true;
        await bounded(client.query({text:'SET LOCAL search_path=pg_catalog',rowMode:'array'}),lease);
        const profile=initializing?publication_schema_profile(await tx.query(AUTHORITY_HISTORY_SQL,undefined,4)):this.#profile;
        if(profile===null)throw new IndexNotReady();
        const role=await tx.query(profile==='attestation'?WRITER_ATTESTATION_ROLE_SQL:WRITER_ROLE_SQL,undefined,1);
        if(role.length!==1||role[0].length!==1||role[0][0]!==true) throw new UnauthorizedScope();
        if(context){
          const grants=JSON.stringify(context.scope.grant_ids);
          if(Buffer.byteLength(grants)>131072) throw new InvalidRequest();
          await tx.query(SCOPE_SQL,[context.scope.tenant_id,context.collection,context.scope.principal_id,grants,
            context.scope.authorization_revision,context.document_id,context.intent_id,context.owner_token,this.#instance],1);
        }
        const value=await body(tx,profile);
        commitAttempted=true;
        await bounded(client.query({text:'COMMIT',rowMode:'array'}),lease);
        if(client.getTransactionStatus()!=='I') throw new ProviderUnavailable();
        committed=true;
        return value;
      } catch(error) {
        if(commitAttempted&&!committed){
          client.release(true);
          let code:unknown;
          try{code=Object.getOwnPropertyDescriptor(error as object,'code')?.value;}catch{ /* No driver error hooks. */ }
          if(preserveCommitCancellation&&(error instanceof DeadlineExceeded
            ||(error instanceof DOMException&&error.name==='AbortError')||code==='57014'))throw safe(error,options.deadline);
          if(typeof code==='string'&&['23503','23505','23514','23502','40001','40P01'].includes(code))throw safe(error,options.deadline);
          throw new CommitUnknown();
        }
        throw safe(error,options.deadline);
      } finally {
        if(begun&&!committed&&!commitAttempted){
          let clean=false;
          try {
            await bounded(client.query({text:'ROLLBACK',rowMode:'array'}),{deadline:now()+this.#resource.config.release_timeout});
            clean=client.getTransactionStatus()==='I';
          } catch { /* An uncertain lease must never return to the pool. */ }
          if(!clean)client.release(true);
        }
      }
    });
  }
  #key(context:WriterContext):unknown[]{return [context.scope.tenant_id,context.collection,context.document_id];}
  async #select(tx:Tx,table:string,columns:readonly string[],context:WriterContext,extra='',params:readonly unknown[]=[],max=65):Promise<Data[]> {
    const locked=extra.endsWith(' FOR UPDATE');
    const condition=locked?extra.slice(0,-11):extra;
    const rows=await tx.query(`SELECT ${columns.map(column=>column==='point_id'||column==='owner_token'?column+'::text':column).join(',')} FROM cragkit_qdrant.${table} WHERE (tenant_id,collection,document_id)=($1,$2,$3)${condition} LIMIT ${max}${locked?' FOR UPDATE':''}`,[...this.#key(context),...params],max);
    if(rows.some(row=>row.length!==columns.length))throw new IntegrityViolation();
    return rows.map(row=>Object.fromEntries(columns.map((column,index)=>[column,row[index]])));
  }
  async #insert(tx:Tx,table:string,record:Data):Promise<void>{
    const columns=Object.keys(record);
    const values=columns.map(column=>['dense_profile','sparse_profile'].includes(column)&&record[column]!==null?JSON.stringify(record[column]):record[column]);
    await tx.query(`INSERT INTO cragkit_qdrant.${table} (${columns.join(',')}) VALUES (${columns.map((_,index)=>'$'+(index+1)).join(',')}) ON CONFLICT DO NOTHING`,values,0);
  }
  async #ensure(tx:Tx,table:string,record:Data,context:WriterContext,extra:string,params:readonly unknown[]):Promise<Data>{
    const columns=Object.keys(record);
    let rows=await this.#select(tx,table,columns,context,extra,params,2);
    if(rows.length===0){
      await this.#insert(tx,table,record);
      rows=await this.#select(tx,table,columns,context,extra,params,2);
    }
    if(rows.length!==1||columns.some(column=>!exact(rows[0][column],record[column])))throw new IntegrityViolation();
    return rows[0];
  }
  async #intent(tx:Tx,context:WriterContext):Promise<Data|null>{
    const rows=await this.#select(tx,'publication_intents',INTENT_PRIVATE,context,' AND intent_id=$4',[context.intent_id],2);
    if(rows.length>1)throw new IntegrityViolation();
    if(rows.length===0)return null;
    const row=rows[0];intent_view(row);
    if(row.instance_id!==this.#instance||hash(db_bytes(row.payload_bytes,1048576))!==row.payload_sha256)throw new IntegrityViolation();
    if(row.manifest_bytes!==null&&hash(db_bytes(row.manifest_bytes,1048576))!==row.manifest_sha256)throw new IntegrityViolation();
    db_count(row.expected_mutation_epoch);
    if(row.action==='stage'){
      const tuple=this.#payloadTuple(row);
      if(tuple.length!==11||!same(tuple.slice(0,10),['cragkit.qdrant.intent.v1','stage',context.intent_id,...this.#key(context),row.manifest_sha256,row.expected_active_generation_id,row.expected_authorization_revision,String(db_count(row.expected_mutation_epoch))]))throw new IntegrityViolation();
      let manifest:unknown[];
      try{manifest=native_array(JSON.parse(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(db_bytes(row.manifest_bytes,1048576))),18,18);}
      catch{throw new IntegrityViolation();}
      if(!same(manifest.slice(0,9),['cragkit.qdrant.manifest.v1',this.#config.backend_namespace,this.#config.physical_collection,this.#config.collection_incarnation,...this.#key(context),row.revision_id,row.generation_id]))throw new IntegrityViolation();
    }
    return row;
  }
  async #document(tx:Tx,context:WriterContext,lock=false):Promise<Data|null>{
    const rows=await this.#select(tx,'documents',DOCUMENT_COLUMNS,context,lock?' FOR UPDATE':'',[],2);
    if(rows.length>1)throw new IntegrityViolation();
    if(!rows.length)return null;
    const row=rows[0];
    if(typeof row.tombstoned!=='boolean')throw new IntegrityViolation();
    db_count(row.mutation_epoch);
    try {
      row.principal_ids=Object.freeze(native_array(db_json(row.principal_ids),0,64).map(value=>text(value)));
      row.grant_ids=Object.freeze(native_array(db_json(row.grant_ids),0,64).map(value=>text(value)));
      text(row.authorization_revision);
      if(row.active_generation_id!==null)text(row.active_generation_id);
      for(const key of ['language','kind','tag'])if(row[key]!==null){
        if(typeof row[key]!=='string'||(row[key] as string).length>1024||Buffer.byteLength(row[key] as string)>1024||(row[key] as string).includes('\0'))throw new InvalidRequest();
      }
    }catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
    return row;
  }
  async #fence(tx:Tx,context:WriterContext,intent:Data,lock=true):Promise<'denied'|'conflict'|null>{
    const document=await this.#document(tx,context,lock);
    let revision=intent.expected_authorization_revision,epoch=db_count(intent.expected_mutation_epoch);
    if(intent.authority_committed&&(intent.action==='update_authorization'||intent.action==='tombstone')){
      const tuple=this.#payloadTuple(intent);
      revision=native_array(tuple[8],7,7)[0];epoch++;
    }
    const needsTombstone=intent.action==='purge'||(intent.action==='tombstone'&&intent.authority_committed);
    if(!document||document.tombstoned!==needsTombstone||document.authorization_revision!==revision
      ||db_count(document.mutation_epoch)!==epoch)return 'denied';
    if(context.scope.authorization_revision!==document.authorization_revision)throw new UnauthorizedScope();
    if(intent.action==='stage'&&document.active_generation_id!==intent.expected_active_generation_id)return 'conflict';
    return null;
  }
  #payloadTuple(intent:Data):unknown[]{
    try {
      const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(db_bytes(intent.payload_bytes,1048576));
      return native_array(JSON.parse(text),9,11);
    }catch(error){if(error instanceof SyntaxError||error instanceof TypeError||error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
  }
  async #locks(tx:Tx,context:WriterContext,requireOwner=true):Promise<{epoch:number;owner:Data|null}>{
    const backend=await tx.query('SELECT backend_namespace,epoch,state FROM cragkit_qdrant.backend_instances WHERE instance_id=$1 FOR SHARE',[this.#instance],2);
    if(backend.length!==1||backend[0].length!==3||backend[0][0]!==this.#config.backend_namespace)throw new UnsupportedCapability();
    if(backend[0][2]!=='open')throw new ProviderUnavailable();
    const epoch=db_count(backend[0][1]);
    const owners=await this.#select(tx,'document_owners',['instance_id','intent_id','owner_token','backend_epoch'],context,' FOR UPDATE',[],2);
    if(owners.length>1)throw new IntegrityViolation();
    const owner=owners[0]??null;
    if(requireOwner&&(!owner||owner.instance_id!==this.#instance||owner.intent_id!==context.intent_id
      ||owner.owner_token!==context.owner_token||db_count(owner.backend_epoch)!==epoch))throw new ProviderUnavailable();
    return {epoch,owner};
  }
  #requireLockedOwner(context:WriterContext,locked:{epoch:number;owner:Data|null}):void{
    const owner=locked.owner;
    if(!owner||owner.instance_id!==this.#instance||owner.intent_id!==context.intent_id
      ||owner.owner_token!==context.owner_token||db_count(owner.backend_epoch)!==locked.epoch)throw new ProviderUnavailable();
  }
  async #updateIntent(tx:Tx,context:WriterContext,state:string,flags=false):Promise<IntentView>{
    await tx.query(`UPDATE cragkit_qdrant.publication_intents SET state=$4${flags?',authority_committed=true,replica_complete=true':''} WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$5)`,[...this.#key(context),state,context.intent_id],0);
    const row=await this.#intent(tx,context);if(!row)throw new IntegrityViolation();return intent_view(row);
  }
  async initialize(input:unknown):Promise<void>{
    const options=parseOptions(input);
    await this.#work(options,async lease=>{
      this.#initialized=false;this.#profile=null;
      const selected=await this.#tx(null,lease,async(tx,profile)=>{
        const catalog=profile==='attestation'?AUTHORITY_ATTESTATION_CATALOG_SQL:AUTHORITY_PUBLICATION_CATALOG_SQL;
        const fingerprint=profile==='attestation'?EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT:EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT;
        for(const [sql,expected] of [[catalog,true],[AUTHORITY_FINGERPRINT_SQL,fingerprint]] as const){
          const rows=await tx.query(sql,undefined,1);if(rows.length!==1||rows[0].length!==1||rows[0][0]!==expected)throw new UnsupportedCapability();
        }
        return profile;
      },false,true);
      this.#profile=selected;this.#initialized=true;
    },true);
  }
  async inspect(input:unknown,rawOptions:unknown):Promise<IntentView|null>{
    const context=parseContext(input),options=parseOptions(rawOptions);
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{const intent=await this.#intent(tx,context);return intent?intent_view(intent):null;}));
  }

  /** Manager metadata never substitutes for mutation admission or authority. */
  async #managerBackend(tx:Tx,lock=false):Promise<ManagerBackend> {
    const rows=await tx.query('SELECT instance_id,backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1'+(lock?' FOR SHARE':''),[this.#instance],2);
    if(rows.length===0)throw new ProviderUnavailable();
    if(rows.length!==1||rows[0].length!==7)throw new IntegrityViolation();
    try {
      const [instance_id,backend_namespace,storage_identity,supervisor_id,rawEpoch,state,recovery_id]=rows[0];
      for(const value of [instance_id,backend_namespace,storage_identity,supervisor_id])text(value);
      const epoch=db_count(rawEpoch);
      if(instance_id!==this.#instance||backend_namespace!==this.#config.backend_namespace||epoch<1
        ||typeof state!=='string'||!['open','recovery_blocked'].includes(state))throw new IntegrityViolation();
      if(state==='open'?recovery_id!==null:typeof recovery_id!=='string')throw new IntegrityViolation();
      if(recovery_id!==null)text(recovery_id);
      return Object.freeze({instance_id:instance_id as string,backend_namespace:backend_namespace as string,
        storage_identity:storage_identity as string,supervisor_id:supervisor_id as string,epoch,
        state:state as ManagerBackend['state'],recovery_id:recovery_id as string|null});
    } catch(error) {
      if(error instanceof InvalidRequest)throw new IntegrityViolation();
      throw error;
    }
  }

  async #managerOwner(tx:Tx,context:WriterContext,lock=false):Promise<ManagerOwner|null> {
    const rows=await this.#select(tx,'document_owners',['instance_id','intent_id','owner_token','backend_epoch'],context,lock?' FOR UPDATE':'',[],2);
    if(rows.length>1)throw new IntegrityViolation();
    if(rows.length===0)return null;
    try {
      const row=rows[0],backend_epoch=db_count(row.backend_epoch);
      if(backend_epoch<1)throw new IntegrityViolation();
      return Object.freeze({instance_id:text(row.instance_id),intent_id:text(row.intent_id),
        owner_token:uuid(row.owner_token),backend_epoch});
    } catch(error) {
      if(error instanceof InvalidRequest)throw new IntegrityViolation();
      throw error;
    }
  }

  async #managerPending(tx:Tx,context:WriterContext):Promise<boolean> {
    const rows=await this.#select(tx,'dispatch_journal',['state'],context," AND state<>'settled'",[],1);
    if(rows.some(row=>typeof row.state!=='string'||!['reserved','dispatched','unknown'].includes(row.state)))throw new IntegrityViolation();
    return rows.length!==0;
  }

  async preflight_repair(input:unknown,rawOptions:unknown):Promise<Readonly<{intent:IntentView;owner:ManagerOwner|null;backend:ManagerBackend;pending:boolean}>> {
    const context=parseContext(input),options=parseOptions(rawOptions);this.#requireAttestationProfile();
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const backend=await this.#managerBackend(tx,true);
      const owner=await this.#managerOwner(tx,context,true);
      const document=await this.#document(tx,context,true);
      if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      const intent=await this.#intent(tx,context);
      if(!intent)throw new InvalidRequest();
      if(intent.action!=='stage')throw new UnsupportedCapability();
      const pending=await this.#managerPending(tx,context);
      if(['published','conflict','denied'].includes(String(intent.state)))return Object.freeze({intent:intent_view(intent),owner,backend,pending});
      // Inspect original fences even when ordinary admission is blocked.
      const failure=await this.#fence(tx,context,intent,false);
      if(failure)return Object.freeze({intent:await this.#updateIntent(tx,context,failure),owner,backend,pending});
      await this.#loadStage(tx,context);
      return Object.freeze({intent:intent_view(intent),owner,backend,pending});
    },true));
  }

  async manager_snapshot(input:unknown,rawOptions:unknown):Promise<ManagerSnapshot> {
    const context=parseContext(input),options=parseOptions(rawOptions);
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const document=await this.#document(tx,context);
      if(document&&document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      const backend=await this.#managerBackend(tx);
      const owner=await this.#managerOwner(tx,context);
      const intent=await this.#intent(tx,context);
      const rows=await this.#select(tx,'dispatch_journal',['dispatch_id','sequence'],context,' AND intent_id=$4',[context.intent_id],257);
      if(rows.length>256)throw new IntegrityViolation();
      const ids=new Set<string>(),sequences=new Set<number>();
      let max_sequence=0;
      try {
        for(const row of rows){
          const id=text(row.dispatch_id),sequence=db_count(row.sequence);
          if(sequence<1||sequence>256||ids.has(id)||sequences.has(sequence))throw new IntegrityViolation();
          ids.add(id);
          sequences.add(sequence);
          max_sequence=Math.max(max_sequence,sequence);
        }
      } catch(error) {
        if(error instanceof InvalidRequest)throw new IntegrityViolation();
        throw error;
      }
      const pending=await this.#managerPending(tx,context);
      const current=document?Object.freeze({active_generation_id:document.active_generation_id as string|null,
        authorization_revision:document.authorization_revision as string,mutation_epoch:db_count(document.mutation_epoch),
        tombstoned:document.tombstoned as boolean}):null;
      return Object.freeze({intent:intent?intent_view(intent):null,document:current,backend,owner,max_sequence,pending});
    }));
  }

  async admit_publication(input:unknown,rawOptions:unknown):Promise<PublicationAdmission> {
    const context=parseContext(input),options=parseOptions(rawOptions);
    const admit=async(tx:Tx):Promise<PublicationAdmission>=>{
      let intent=await this.#intent(tx,context);
      if(!intent||intent.action!=='stage')throw new InvalidRequest();
      const preliminary=await this.#document(tx,context);
      if(!preliminary||preliminary.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      if(['published','conflict','denied'].includes(String(intent.state)))return Object.freeze({intent:intent_view(intent),owner:null});
      // Refresh authority after the owner wait, without requiring the old token.
      const backend=await this.#managerBackend(tx,true);
      const owner=await this.#managerOwner(tx,context,true);
      const document=await this.#document(tx,context,true);
      if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      intent=await this.#intent(tx,context);
      if(!intent||intent.action!=='stage')throw new IntegrityViolation();
      if(['published','conflict','denied'].includes(String(intent.state)))return Object.freeze({intent:intent_view(intent),owner:null});
      const denied=document.tombstoned||document.authorization_revision!==intent.expected_authorization_revision
        ||db_count(document.mutation_epoch)!==db_count(intent.expected_mutation_epoch);
      const conflict=document.active_generation_id!==intent.expected_active_generation_id;
      if(denied||conflict){
        const terminal=await this.#updateIntent(tx,context,denied?'denied':'conflict');
        return Object.freeze({intent:terminal,owner:null});
      }
      if(backend.state!=='open')throw new ProviderUnavailable();
      if(await this.#managerPending(tx,context))throw new ProviderUnavailable();
      await this.#loadStage(tx,context);
      const sameOwner=owner?.instance_id===this.#instance&&owner.intent_id===context.intent_id
        &&owner.owner_token===context.owner_token&&owner.backend_epoch===backend.epoch;
      if(owner&&!sameOwner){
        await tx.query('UPDATE cragkit_qdrant.document_owners SET instance_id=$4,intent_id=$5,owner_token=$6::uuid,backend_epoch=$7 WHERE (tenant_id,collection,document_id)=($1,$2,$3)',
          [...this.#key(context),this.#instance,context.intent_id,context.owner_token,backend.epoch],0);
      } else if(!owner){
        await this.#insert(tx,'document_owners',{...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),
          instance_id:this.#instance,intent_id:context.intent_id,owner_token:context.owner_token,backend_epoch:backend.epoch});
      }
      if(intent.state==='staged'||intent.state==='authority_committed')await this.#updateIntent(tx,context,'writing');
      const current=await this.#intent(tx,context);
      if(!current)throw new IntegrityViolation();
      return Object.freeze({intent:intent_view(current),owner:Object.freeze({owner_token:context.owner_token,backend_epoch:backend.epoch})});
    };
    return this.#work(options,async lease=>{
      try {
        return await this.#tx(context,lease,admit,true);
      } catch(error) {
        if(!(error instanceof CommitUnknown))throw error;
        if(lease.signal?.aborted)throw new DOMException('Operation aborted.','AbortError');
        if(now()>=lease.deadline)throw new DeadlineExceeded();
        // Confirm a committed receipt before considering any same-ID mutation.
        const confirmed=await this.#tx(context,lease,async tx=>{
          const document=await this.#document(tx,context);
          if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
          const intent=await this.#intent(tx,context);
          if(!intent||intent.action!=='stage')throw new IntegrityViolation();
          if(['published','conflict','denied'].includes(String(intent.state)))return Object.freeze({intent:intent_view(intent),owner:null});
          const backend=await this.#managerBackend(tx);
          const owner=await this.#managerOwner(tx,context);
          const pending=await this.#managerPending(tx,context);
          if(backend.state==='open'&&!pending&&['writing','prepared'].includes(String(intent.state))
            &&owner?.instance_id===this.#instance&&owner.intent_id===context.intent_id
            &&owner.owner_token===context.owner_token&&owner.backend_epoch===backend.epoch){
            return Object.freeze({intent:intent_view(intent),owner:Object.freeze({owner_token:context.owner_token,backend_epoch:backend.epoch})});
          }
          return null;
        },true);
        if(confirmed)return confirmed;
        // Only an actual lost COMMIT acknowledgment permits this one same-ID retry.
        return this.#tx(context,lease,admit,true);
      }
    });
  }
  async #mutation<T>(context:WriterContext,options:LeaseOptions,body:(tx:Tx)=>Promise<T>,reconcile:(tx:Tx)=>Promise<T>):Promise<T>{
    return this.#work(options,async lease=>{
      try { return await this.#tx(context,lease,body); }
      catch(error) {
        if(!(error instanceof CommitUnknown))throw error;
        // Reconcile the SAME identity once. Never retry DML after a lost ACK.
        return this.#tx(context,lease,reconcile);
      }
    });
  }
  async stage(plan:unknown,inputScope:unknown,rawOptions:unknown):Promise<IntentView>{
    const data=stage_data(plan),trusted=parseScope(inputScope),options=parseOptions(rawOptions,true);
    const record=data.record,intent=data.intent;
    if(record.tenant_id!==trusted.tenant_id||trusted.authorization_revision!==intent.expected_authorization_revision)throw new UnauthorizedScope();
    if(['backend_namespace','physical_collection','collection_incarnation','dense_profile','sparse_profile']
      .some(key=>!same(record[key],this.#config[key as keyof QdrantConfig])))throw new IntegrityViolation();
    const context=parseContext({scope:trusted,collection:record.collection,document_id:record.document_id,
      intent_id:intent.intent_id,owner_token:options.owner_token});
    const common=Object.fromEntries(TARGET.map(key=>[key,record[key]]));
    const intentRecord:Data={...common,intent_id:context.intent_id,instance_id:this.#instance,action:'stage',
      payload_bytes:Buffer.from(data.payload.encoded_bytes),payload_sha256:data.payload.sha256,
      manifest_bytes:Buffer.from(data.manifest.encoded_bytes),manifest_sha256:data.manifest.sha256,
      revision_id:record.revision_id,generation_id:record.generation_id,
      expected_active_generation_id:intent.expected_active_generation_id,
      expected_authorization_revision:intent.expected_authorization_revision,expected_mutation_epoch:intent.expected_mutation_epoch};
    const verify=async(tx:Tx):Promise<IntentView>=>{
      const stored=await this.#intent(tx,context);
      if(!stored||Object.keys(intentRecord).some(key=>!TARGET.includes(key)&&key!=='intent_id'&&!exact(stored[key],intentRecord[key])))throw new IntegrityViolation();
      await this.#stageFacts(tx,context,data);
      return intent_view(stored);
    };
    return this.#mutation(context,options,async tx=>{
      const existing=await this.#intent(tx,context);
      if(existing)return verify(tx);
      const prior=await this.#document(tx,context,true);
      if(prior&&intent.initial_authorization!==null)throw new IntegrityViolation();
      if(prior){
        if(prior.tombstoned||prior.authorization_revision!==intent.expected_authorization_revision
          ||db_count(prior.mutation_epoch)!==intent.expected_mutation_epoch)throw new UnauthorizedScope();
        if(prior.active_generation_id!==intent.expected_active_generation_id)throw new IntegrityViolation();
      }else if(intent.initial_authorization===null)throw new UnauthorizedScope();
      // The document lock serializes all new stage bindings. A generation is
      // one immutable manifest, even when a caller uses another stable intent.
      const otherBindings=await tx.query('SELECT manifest_sha256 FROM cragkit_qdrant.publication_intents WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND revision_id=$4 AND generation_id=$5 AND action=\'stage\' AND manifest_sha256<>$6 LIMIT 1',
        [...this.#key(context),record.revision_id,record.generation_id,data.manifest.sha256],1);
      if(otherBindings.length)throw new IntegrityViolation();
      await this.#ensure(tx,'publication_intents',intentRecord,context,' AND intent_id=$4',[context.intent_id]);
      if(!prior){
        const auth=metadata(intent.initial_authorization);
        const canonical=native_array(data.payload.value[10],7,7);
        const columns=[...TARGET,'principal_ids','grant_ids','authorization_revision','mutation_epoch','language','kind','tag','tombstoned'];
        const values=[...this.#key(context),canonical[1],canonical[2],auth.authorization_revision,1,auth.language,auth.kind,auth.tag,false];
        const inserted=await tx.query(`INSERT INTO cragkit_qdrant.documents (${columns.join(',')}) VALUES (${columns.map((_,i)=>'$'+(i+1)).join(',')}) ON CONFLICT DO NOTHING RETURNING document_id`,values,1);
        if(inserted.length!==1||inserted[0][0]!==context.document_id)throw new IntegrityViolation();
      }
      const source=Buffer.from(data.canonical_text,'utf8');
      await this.#ensure(tx,'document_revisions',{...common,revision_id:record.revision_id,canonical_utf8:source,
        source_sha256:record.source_sha256,source_locator:record.source_locator,parser_id:record.parser_id},context,' AND revision_id=$4',[record.revision_id]);
      await this.#ensure(tx,'generations',{...common,revision_id:record.revision_id,generation_id:record.generation_id,
        backend_namespace:record.backend_namespace,physical_collection:record.physical_collection,collection_incarnation:record.collection_incarnation,
        chunker_profile:record.chunker_profile,dense_profile_id:this.#config.dense_profile.profile_id,
        sparse_profile_id:this.#config.sparse_profile?.profile_id??'',dense_profile:this.#config.dense_profile,
        sparse_profile:this.#config.sparse_profile,expected_member_count:(plan as StagePlan).member_count},context,' AND generation_id=$4',[record.generation_id]);
      const members=native_array(record.members,1,64).map(value=>metadata(value));
      for(let i=0;i<members.length;i++){
        const member=members[i],dense=data.dense[i],sparse=data.sparse[i];
        const identity={...common,revision_id:record.revision_id,generation_id:record.generation_id,chunk_id:member.chunk_id};
        await this.#ensure(tx,'members',{...identity,point_id:member.point_id,start_byte:member.start_byte,end_byte:member.end_byte,
          source_sha256:record.source_sha256,text_sha256:member.text_sha256,
          excerpt_utf8:source.subarray(count(member.start_byte),count(member.end_byte))},context,
          ' AND revision_id=$4 AND generation_id=$5 AND chunk_id=$6',[record.revision_id,record.generation_id,member.chunk_id]);
        const physical={backend_namespace:record.backend_namespace,physical_collection:record.physical_collection,
          collection_incarnation:record.collection_incarnation,point_id:member.point_id};
        await this.#ensure(tx,'point_claims',{...physical,instance_id:this.#instance,...identity,
          source_sha256:record.source_sha256,text_sha256:member.text_sha256,start_byte:member.start_byte,end_byte:member.end_byte,
          dense_profile:this.#config.dense_profile,sparse_profile:this.#config.sparse_profile,
          dense_input_sha256:dense.input_sha256,sparse_input_sha256:sparse?.input_sha256??null},context,
          ' AND backend_namespace=$4 AND physical_collection=$5 AND collection_incarnation=$6 AND point_id=$7::uuid',
          [record.backend_namespace,record.physical_collection,record.collection_incarnation,member.point_id]);
        await this.#ensure(tx,'vector_replays',{...identity,...physical,dense_blob:Buffer.from(dense.blob),
          dense_blob_sha256:dense.blob_sha256,sparse_blob:sparse?Buffer.from(sparse.blob):null,
          sparse_blob_sha256:sparse?.blob_sha256??null},context,
          ' AND revision_id=$4 AND generation_id=$5 AND chunk_id=$6',[record.revision_id,record.generation_id,member.chunk_id]);
      }
      return verify(tx);
    },verify);
  }
  async #stageFacts(tx:Tx,context:WriterContext,data:ReturnType<typeof stage_data>):Promise<void>{
    const record=data.record;
    const revisions=await this.#select(tx,'document_revisions',['canonical_utf8','source_sha256','source_locator','parser_id'],context,' AND revision_id=$4',[record.revision_id],2);
    if(revisions.length!==1||!exact(revisions[0].canonical_utf8,Buffer.from(data.canonical_text))
      ||['source_sha256','source_locator','parser_id'].some(key=>!exact(revisions[0][key],record[key])))throw new IntegrityViolation();
    const stored=await this.#loadStage(tx,context);
    if(stored.manifest.sha256!==data.manifest.sha256
      ||!Buffer.from(stored.manifest.encoded_bytes).equals(Buffer.from(data.manifest.encoded_bytes)))throw new IntegrityViolation();
    const inputMembers=native_array(record.members,1,64).map(item=>metadata(item));
    for(let i=0;i<inputMembers.length;i++){
      const found=stored.points.find(point=>point.claim.chunk_id===inputMembers[i].chunk_id);
      if(!found||!db_bytes(found.replay.dense_blob,12326).equals(Buffer.from(data.dense[i].blob))
        ||(data.sparse[i]===null?found.replay.sparse_blob!==null:!db_bytes(found.replay.sparse_blob,231).equals(Buffer.from(data.sparse[i]!.blob))))throw new IntegrityViolation();
    }
  }
  async #point(tx:Tx,context:WriterContext,claim:Data):Promise<PointData>{
    if(claim.instance_id!==this.#instance||claim.backend_namespace!==this.#config.backend_namespace
      ||claim.physical_collection!==this.#config.physical_collection||claim.collection_incarnation!==this.#config.collection_incarnation
      ||!same(db_json(claim.dense_profile),this.#config.dense_profile)||!same(db_json(claim.sparse_profile),this.#config.sparse_profile))throw new IntegrityViolation();
    try {
      const tuple=['cragkit.qdrant.point.v1',this.#config.backend_namespace,this.#config.physical_collection,
        this.#config.collection_incarnation,context.scope.tenant_id,context.collection,context.document_id,
        text(claim.revision_id),text(claim.generation_id),text(claim.chunk_id),this.#config.dense_profile.profile_id,
        this.#config.sparse_profile?.profile_id??''];
      if(point_id(tuple)!==claim.point_id||claim.tenant_id!==context.scope.tenant_id||claim.collection!==context.collection
        ||claim.document_id!==context.document_id||db_count(claim.start_byte)>=db_count(claim.end_byte)
        ||db_count(claim.end_byte)-db_count(claim.start_byte)>32768)throw new IntegrityViolation();
      digest(claim.source_sha256);digest(claim.text_sha256);
    }catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
    const rows=await this.#select(tx,'vector_replays',REPLAY_COLUMNS,context,
      ' AND revision_id=$4 AND generation_id=$5 AND chunk_id=$6',[claim.revision_id,claim.generation_id,claim.chunk_id],2);
    if(rows.length!==1)throw new IntegrityViolation();
    const replay=rows[0];
    for(const key of [...TARGET,'revision_id','generation_id','chunk_id','backend_namespace','physical_collection','collection_incarnation','point_id']){
      if(replay[key]!==claim[key])throw new IntegrityViolation();
    }
    const dense=restore_dense_replay(Array.from(db_bytes(replay.dense_blob,12326)),replay.dense_blob_sha256,claim.dense_input_sha256,this.#config.dense_profile);
    let sparse:ReturnType<typeof restore_sparse_replay>|null=null;
    if(this.#config.sparse_profile===null){
      if(replay.sparse_blob!==null||replay.sparse_blob_sha256!==null||claim.sparse_input_sha256!==null)throw new IntegrityViolation();
    }else{
      sparse=restore_sparse_replay(Array.from(db_bytes(replay.sparse_blob,231)),replay.sparse_blob_sha256,claim.sparse_input_sha256,this.#config.sparse_profile);
    }
    return {claim,replay,dense,sparse};
  }
  async #loadStage(tx:Tx,context:WriterContext):Promise<{manifest:ReturnType<typeof encode_manifest>;points:PointData[];data:StageData}>{
    const intent=await this.#intent(tx,context);
    if(!intent||intent.action!=='stage')throw new IntegrityViolation();
    const generations=await this.#select(tx,'generations',['backend_namespace','physical_collection','collection_incarnation','revision_id','generation_id',
      'chunker_profile','dense_profile','sparse_profile','expected_member_count'],context,' AND generation_id=$4',[intent.generation_id],2);
    const revisions=await this.#select(tx,'document_revisions',['canonical_utf8','source_sha256','source_locator','parser_id'],context,
      ' AND revision_id=$4',[intent.revision_id],2);
    if(generations.length!==1||revisions.length!==1)throw new IntegrityViolation();
    const generation=generations[0],revision=revisions[0];
    const source=db_bytes(revision.canonical_utf8,16777216);
    let canonical:string;
    try {canonical=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(source);}
    catch(error){if(error instanceof TypeError)throw new IntegrityViolation();throw error;}
    const members=await this.#select(tx,'members',MEMBER_COLUMNS,context,' AND revision_id=$4 AND generation_id=$5',[intent.revision_id,intent.generation_id],65);
    const claims=await this.#select(tx,'point_claims',CLAIM_COLUMNS,context,' AND revision_id=$4 AND generation_id=$5',[intent.revision_id,intent.generation_id],65);
    const replays=await this.#select(tx,'vector_replays',['chunk_id'],context,' AND revision_id=$4 AND generation_id=$5',[intent.revision_id,intent.generation_id],65);
    const expected=db_count(generation.expected_member_count);
    if(expected<1||expected>64||members.length!==expected||claims.length!==expected||replays.length!==expected)throw new IntegrityViolation();
    const points:PointData[]=[];
    const metadataMembers:Data[]=[];
    for(const member of members){
      const matching=claims.filter(claim=>claim.chunk_id===member.chunk_id);
      if(matching.length!==1)throw new IntegrityViolation();
      const claim=matching[0];
      for(const key of ['revision_id','generation_id','chunk_id','point_id','source_sha256','text_sha256'])if(claim[key]!==member[key])throw new IntegrityViolation();
      for(const key of ['start_byte','end_byte'])if(db_count(claim[key])!==db_count(member[key]))throw new IntegrityViolation();
      if(!source.subarray(db_count(member.start_byte),db_count(member.end_byte)).equals(db_bytes(member.excerpt_utf8,32768)))throw new IntegrityViolation();
      points.push(await this.#point(tx,context,claim));
      metadataMembers.push({chunk_id:member.chunk_id,point_id:member.point_id,start_byte:db_count(member.start_byte),end_byte:db_count(member.end_byte),
        text_sha256:member.text_sha256,dense_input_sha256:claim.dense_input_sha256,sparse_input_sha256:claim.sparse_input_sha256});
    }
    const record:Data={...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),
      backend_namespace:generation.backend_namespace,physical_collection:generation.physical_collection,
      collection_incarnation:generation.collection_incarnation,revision_id:intent.revision_id,generation_id:intent.generation_id,
      source_sha256:revision.source_sha256,source_bytes:source.length,source_locator:revision.source_locator,
      parser_id:revision.parser_id,chunker_profile:generation.chunker_profile,dense_profile:db_json(generation.dense_profile),
      sparse_profile:db_json(generation.sparse_profile),members:metadataMembers};
    let manifest:ReturnType<typeof encode_manifest>,payload:ReturnType<typeof encode_stage_intent>,stageIntent:Data;
    try {
      manifest=encode_manifest(record,canonical);
      const tuple=this.#payloadTuple(intent);
      if(tuple.length!==11)throw new IntegrityViolation();
      let initial:Data|null=null;
      if(tuple[10]!==null){
        const auth=native_array(tuple[10],7,7);
        if(auth[6]!=='false')throw new IntegrityViolation();
        initial={authorization_revision:auth[0],principal_ids:auth[1],grant_ids:auth[2],language:auth[3],kind:auth[4],tag:auth[5],tombstoned:false};
      }
      stageIntent={intent_id:context.intent_id,...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),
        manifest_sha256:manifest.sha256,expected_active_generation_id:intent.expected_active_generation_id,
        expected_authorization_revision:intent.expected_authorization_revision,expected_mutation_epoch:db_count(intent.expected_mutation_epoch),
        initial_authorization:initial};
      payload=encode_stage_intent(stageIntent);
    }catch(error){if(error instanceof InvalidRequest||error instanceof UnsupportedCapability)throw new IntegrityViolation();throw error;}
    if(manifest.sha256!==intent.manifest_sha256||!Buffer.from(manifest.encoded_bytes).equals(db_bytes(intent.manifest_bytes,1048576)))throw new IntegrityViolation();
    if(payload.sha256!==intent.payload_sha256||!Buffer.from(payload.encoded_bytes).equals(db_bytes(intent.payload_bytes,1048576)))throw new IntegrityViolation();
    const dense=points.map(point=>Object.freeze({blob:Object.freeze(Array.from(db_bytes(point.replay.dense_blob,12326))),
      blob_sha256:digest(point.replay.dense_blob_sha256),input_sha256:point.dense.input_sha256,encoded:point.dense}));
    const sparse=points.map(point=>point.sparse===null?null:Object.freeze({blob:Object.freeze(Array.from(db_bytes(point.replay.sparse_blob,231))),
      blob_sha256:digest(point.replay.sparse_blob_sha256),input_sha256:point.sparse.input_sha256,encoded:point.sparse}));
    const data:StageData=Object.freeze({record:metadata(record),intent:metadata(stageIntent),canonical_text:canonical,manifest,payload,
      dense:Object.freeze(dense),sparse:Object.freeze(sparse)});
    return {manifest,points,data};
  }
  async load_stage(input:unknown,rawOptions:unknown):Promise<StagePlan>{
    const context=parseContext(input),options=parseOptions(rawOptions);
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const document=await this.#document(tx,context);
      if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      return issue_verified_stage((await this.#loadStage(tx,context)).data);
    }));
  }
  async #project(tx:Tx,context:WriterContext,physical:Readonly<Data>):Promise<ProjectionData>{
    const rows=await tx.query('SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1 FOR SHARE',[this.#instance],2);
    if(rows.length===0)throw new ProviderUnavailable();
    if(rows.length!==1||rows[0].length!==6)throw new IntegrityViolation();
    const [namespace,storage,supervisor,epoch,state,recovery]=rows[0];
    if(state!=='recovery_blocked')throw new ProviderUnavailable();
    if(db_count(epoch)!==physical.new_epoch||recovery!==physical.recovery_id)throw new ProviderUnavailable();
    if(namespace!==this.#config.backend_namespace||storage!==physical.storage_identity
      ||supervisor!==physical.supervisor_id)throw new IntegrityViolation();
    const owners=await this.#select(tx,'document_owners',['instance_id','intent_id','owner_token','backend_epoch'],context,' FOR UPDATE',[],2);
    if(owners.length!==1||owners[0].instance_id!==this.#instance||owners[0].intent_id!==context.intent_id
      ||owners[0].owner_token!==context.owner_token||db_count(owners[0].backend_epoch)!==physical.new_epoch)throw new ProviderUnavailable();
    const document=await this.#document(tx,context,true);
    if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
    const stage=await this.#loadStage(tx,context);
    const points=this.#projectionPoints(context,document,stage.points);
    return Object.freeze({context,physical_binding:physical,manifest_sha256:stage.manifest.sha256,
      revision_id:text(stage.data.record.revision_id),generation_id:text(stage.data.record.generation_id),points,
      tombstoned:document.tombstoned as boolean,authorization_revision:text(document.authorization_revision),mutation_epoch:db_count(document.mutation_epoch),
      active_generation_id:document.active_generation_id===null?null:text(document.active_generation_id),
      principal_ids:document.principal_ids as readonly string[],grant_ids:document.grant_ids as readonly string[],
      language:document.language as string|null,kind:document.kind as string|null,tag:document.tag as string|null});
  }

  /** Both recovery and ordinary verification use the exact current QC payload. */
  #projectionPoints(context:WriterContext,document:Data,source:readonly PointData[]):readonly ProjectionPoint[] {
    const points=source.map(point=>{
      const claim=point.claim;
      const payload:Data={backend_namespace:claim.backend_namespace,physical_collection:claim.physical_collection,
        collection_incarnation:claim.collection_incarnation,tenant_id:context.scope.tenant_id,collection:context.collection,
        document_id:context.document_id,revision_id:claim.revision_id,generation_id:claim.generation_id,chunk_id:claim.chunk_id,
        start_byte:db_count(claim.start_byte),end_byte:db_count(claim.end_byte),source_sha256:digest(claim.source_sha256),text_sha256:digest(claim.text_sha256),
        dense_profile_id:this.#config.dense_profile.profile_id,sparse_profile_id:this.#config.sparse_profile?.profile_id??'',
        dense_profile:this.#config.dense_profile,sparse_profile:this.#config.sparse_profile,
        authorization_revision:document.authorization_revision,principal_ids:document.principal_ids,grant_ids:document.grant_ids};
      for(const key of ['language','kind','tag'])if(document[key]!==null)payload[key]=document[key];
      return Object.freeze({point_id:uuid(claim.point_id),payload:metadata(payload),dense:point.dense,sparse:point.sparse});
    });
    points.sort((left,right)=>Buffer.compare(Buffer.from(left.point_id),Buffer.from(right.point_id)));
    return Object.freeze(points);
  }
  async project_stage(input:unknown,rawPhysical:unknown,rawOptions:unknown):Promise<ExpectedProjection>{
    const context=parseContext(input),options=parseOptions(rawOptions),physical=metadata(rawPhysical);
    const keys=['instance_id','storage_identity','supervisor_id','recovery_id','old_epoch','new_epoch','credential_generation'];
    if(Object.keys(physical).length!==keys.length||keys.some(key=>!Object.hasOwn(physical,key)))throw new InvalidRequest();
    for(const key of ['instance_id','storage_identity','supervisor_id','recovery_id','credential_generation'])text(physical[key]);
    const old=count(physical.old_epoch,1),next=count(physical.new_epoch,1);
    if(next!==old+1)throw new InvalidRequest();
    if(physical.instance_id!==this.#instance)throw new UnsupportedCapability();
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const data=await this.#project(tx,context,physical),projection=Object.freeze({});
      projections.set(projection,Object.freeze({issuer:this,data}));return projection;
    }));
  }
  async validate_projection(input:unknown,rawOptions:unknown):Promise<void>{
    const previous=projection_data(input,this),options=parseOptions(rawOptions);
    await this.#work(options,lease=>this.#tx(previous.context,lease,async tx=>{
      const current=await this.#project(tx,previous.context,previous.physical_binding);
      if(current.manifest_sha256!==previous.manifest_sha256||current.revision_id!==previous.revision_id
        ||current.generation_id!==previous.generation_id||current.points.length!==previous.points.length)throw new IntegrityViolation();
      if(current.tombstoned!==previous.tombstoned||current.authorization_revision!==previous.authorization_revision
        ||current.mutation_epoch!==previous.mutation_epoch||current.active_generation_id!==previous.active_generation_id
        ||!same(current.principal_ids,previous.principal_ids)||!same(current.grant_ids,previous.grant_ids)
        ||current.language!==previous.language||current.kind!==previous.kind||current.tag!==previous.tag)throw new UnauthorizedScope();
      for(let i=0;i<current.points.length;i++){
        const left=current.points[i],right=previous.points[i];
        if(left.point_id!==right.point_id||!same(left.payload,right.payload)||left.dense.input_sha256!==right.dense.input_sha256
          ||(left.sparse?.input_sha256??null)!==(right.sparse?.input_sha256??null))throw new IntegrityViolation();
      }
    }));
  }

  async #projectPublication(tx:Tx,context:WriterContext,attempt:Readonly<Data>):Promise<PublicationProjectionData> {
    const backends=await tx.query('SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=$1 FOR SHARE',[this.#instance],2);
    if(backends.length===0)throw new ProviderUnavailable();
    if(backends.length!==1||backends[0].length!==6)throw new IntegrityViolation();
    const [namespace,storage,supervisor,epoch,state,recovery]=backends[0];
    if(namespace!==this.#config.backend_namespace||storage!==attempt.storage_identity
      ||supervisor!==attempt.supervisor_id)throw new IntegrityViolation();
    if(state!=='open'||recovery!==null||db_count(epoch)!==attempt.epoch)throw new ProviderUnavailable();
    const owners=await this.#select(tx,'document_owners',['instance_id','intent_id','owner_token','backend_epoch'],context,' FOR UPDATE',[],2);
    if(owners.length!==1||owners[0].instance_id!==this.#instance||owners[0].intent_id!==context.intent_id
      ||owners[0].owner_token!==context.owner_token||db_count(owners[0].backend_epoch)!==attempt.epoch)throw new ProviderUnavailable();
    const document=await this.#document(tx,context,true);
    if(!document||document.authorization_revision!==context.scope.authorization_revision||document.tombstoned)throw new UnauthorizedScope();
    const pending=await this.#select(tx,'dispatch_journal',['state'],context," AND state<>'settled'",[],1);
    if(pending.length)throw new ProviderUnavailable();
    const stage=await this.#loadStage(tx,context);
    const points=this.#projectionPoints(context,document,stage.points);
    const revision_id=text(stage.data.record.revision_id);
    const generation_id=text(stage.data.record.generation_id);
    const authorization_revision=text(document.authorization_revision);
    const mutation_epoch=db_count(document.mutation_epoch);
    const active_generation_id=document.active_generation_id===null?null:text(document.active_generation_id);
    const principal_ids=document.principal_ids as readonly string[];
    const grant_ids=document.grant_ids as readonly string[];
    const language=document.language as string|null;
    const kind=document.kind as string|null;
    const tag=document.tag as string|null;
    const witness=freeze_witness([
      'cragkit.qdrant.publication.readback.v1',attempt.instance_id,attempt.storage_identity,attempt.supervisor_id,
      String(attempt.epoch),attempt.credential_generation,attempt.intent_id,attempt.owner_token,attempt.dispatch_id,
      context.scope.tenant_id,context.collection,context.document_id,revision_id,generation_id,stage.manifest.sha256,
      authorization_revision,String(mutation_epoch),active_generation_id,'false',
      points.map(point=>[point.point_id,point.dense.input_sha256,point.sparse?.input_sha256??null]),
      [canonical_acl(principal_ids),canonical_acl(grant_ids),language,kind,tag],
    ]) as readonly unknown[];
    const encoded_bytes=Object.freeze(Array.from(Buffer.from(JSON.stringify(witness))));
    const readback_sha256=hash(Buffer.from(encoded_bytes));
    return Object.freeze({context,attempt_binding:attempt,manifest_sha256:stage.manifest.sha256,revision_id,generation_id,
      authorization_revision,mutation_epoch,active_generation_id,tombstoned:false,points,
      point_ids:Object.freeze(points.map(point=>point.point_id)),principal_ids,grant_ids,language,kind,tag,
      witness,encoded_bytes,readback_sha256,sha256:readback_sha256});
  }

  async project_publication(input:unknown,rawAttempt:unknown,rawOptions:unknown):Promise<PublicationProjection> {
    const context=parseContext(input),options=parseOptions(rawOptions),attempt=metadata(rawAttempt);
    const keys=['instance_id','storage_identity','supervisor_id','epoch','credential_generation','intent_id','owner_token','dispatch_id'];
    if(Object.keys(attempt).length!==keys.length||keys.some(key=>!Object.hasOwn(attempt,key)))throw new InvalidRequest();
    for(const key of ['instance_id','storage_identity','supervisor_id','credential_generation','intent_id','dispatch_id'])text(attempt[key]);
    uuid(attempt.owner_token);
    count(attempt.epoch,1);
    if(attempt.instance_id!==this.#instance||attempt.intent_id!==context.intent_id
      ||attempt.owner_token!==context.owner_token)throw new UnsupportedCapability();
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const data=await this.#projectPublication(tx,context,attempt);
      const projection=Object.freeze({});
      publicationProjections.set(projection,Object.freeze({issuer:this,data}));
      return projection;
    }));
  }

  async validate_publication_projection(input:unknown,rawOptions:unknown):Promise<void> {
    const previous=publication_projection_data(input,this),options=parseOptions(rawOptions);
    await this.#work(options,lease=>this.#tx(previous.context,lease,async tx=>{
      const current=await this.#projectPublication(tx,previous.context,previous.attempt_binding);
      if(current.manifest_sha256!==previous.manifest_sha256||current.revision_id!==previous.revision_id
        ||current.generation_id!==previous.generation_id||current.points.length!==previous.points.length)throw new IntegrityViolation();
      if(current.authorization_revision!==previous.authorization_revision||current.mutation_epoch!==previous.mutation_epoch
        ||current.active_generation_id!==previous.active_generation_id||!same(current.principal_ids,previous.principal_ids)
        ||!same(current.grant_ids,previous.grant_ids)||current.language!==previous.language
        ||current.kind!==previous.kind||current.tag!==previous.tag)throw new UnauthorizedScope();
      for(let i=0;i<current.points.length;i++){
        const left=current.points[i],right=previous.points[i];
        if(left.point_id!==right.point_id||!same(left.payload,right.payload)||left.dense.input_sha256!==right.dense.input_sha256
          ||(left.sparse?.input_sha256??null)!==(right.sparse?.input_sha256??null))throw new IntegrityViolation();
      }
    }));
  }
  async acquire_owner(input:unknown,rawOptions:unknown):Promise<Readonly<{owner_token:string;backend_epoch:number}>>{
    const context=parseContext(input),options=parseOptions(rawOptions);
    const verify=async(tx:Tx)=>{
      const {epoch,owner}=await this.#locks(tx,context);
      if(!owner)throw new ProviderUnavailable();
      return Object.freeze({owner_token:context.owner_token,backend_epoch:epoch});
    };
    return this.#mutation(context,options,async tx=>{
      const {epoch,owner}=await this.#locks(tx,context,false);
      const intent=await this.#intent(tx,context);
      if(!intent)throw new InvalidRequest();
      const failure=await this.#fence(tx,context,intent);
      if(failure)throw new UnauthorizedScope();
      if(owner&&(owner.intent_id!==context.intent_id||owner.owner_token!==context.owner_token)){
        const pending=await this.#select(tx,'dispatch_journal',['state'],context," AND state<>'settled'",[],1);
        if(pending.length)throw new ProviderUnavailable();
      }
      if(owner){
        await tx.query('UPDATE cragkit_qdrant.document_owners SET instance_id=$4,intent_id=$5,owner_token=$6::uuid,backend_epoch=$7 WHERE (tenant_id,collection,document_id)=($1,$2,$3)',[...this.#key(context),this.#instance,context.intent_id,context.owner_token,epoch],0);
      }else await this.#insert(tx,'document_owners',{...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),
        instance_id:this.#instance,intent_id:context.intent_id,owner_token:context.owner_token,backend_epoch:epoch});
      if(intent.state==='staged'||intent.state==='authority_committed')await this.#updateIntent(tx,context,'writing');
      return verify(tx);
    },verify);
  }
  async #journal(tx:Tx,context:WriterContext,dispatch_id:string):Promise<Data|null>{
    const rows=await this.#select(tx,'dispatch_journal',JOURNAL_COLUMNS,context,' AND intent_id=$4 AND dispatch_id=$5',[context.intent_id,dispatch_id],2);
    if(rows.length>1)throw new IntegrityViolation();
    if(!rows.length)return null;
    const row=rows[0];
    if(hash(db_bytes(row.request_bytes,1048576))!==row.request_sha256||typeof row.recovery!=='boolean')throw new IntegrityViolation();
    db_count(row.sequence);db_count(row.backend_epoch);
    return row;
  }
  async #dispatchView(tx:Tx,context:WriterContext,journal:Data):Promise<DispatchView>{
    const points=await this.#select(tx,'dispatch_points',['point_id'],context,' AND intent_id=$4 AND dispatch_id=$5',[context.intent_id,journal.dispatch_id],9);
    if(points.length<1||points.length>8)throw new IntegrityViolation();
    const point_ids=points.map(point=>{
      try{return uuid(point.point_id);}catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
    }).sort();
    if(new Set(point_ids).size!==point_ids.length)throw new IntegrityViolation();
    return Object.freeze({dispatch_id:text(journal.dispatch_id),request_bytes:Object.freeze(Array.from(db_bytes(journal.request_bytes,1048576))),
      request_sha256:digest(journal.request_sha256),point_ids:Object.freeze(point_ids),operation:text(journal.operation),state:text(journal.state)});
  }

  async dispatch_status(input:unknown,rawId:unknown,rawOptions:unknown):Promise<DispatchStatus|null> {
    const context=parseContext(input),dispatch_id=text(rawId),options=parseOptions(rawOptions);
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const document=await this.#document(tx,context);
      if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      return this.#dispatchStatus(tx,context,dispatch_id);
    }));
  }

  async #dispatchStatus(tx:Tx,context:WriterContext,dispatch_id:string):Promise<DispatchStatus|null> {
      const journal=await this.#journal(tx,context,dispatch_id);
      if(!journal)return null;
      try {
        const instances=await this.#select(tx,'dispatch_journal',['instance_id'],context,' AND intent_id=$4 AND dispatch_id=$5',[context.intent_id,dispatch_id],2);
        if(instances.length!==1||instances[0].instance_id!==this.#instance)throw new IntegrityViolation();
        const sequence=db_count(journal.sequence),backend_epoch=db_count(journal.backend_epoch);
        const operation=text(journal.operation),state=text(journal.state);
        const owner_token=uuid(journal.owner_token),credential_generation=text(journal.credential_generation);
        if(journal.dispatch_id!==dispatch_id||sequence<1||sequence>256||backend_epoch<1
          ||!['complete_point_upsert','delete_points'].includes(operation)
          ||!['reserved','dispatched','unknown','settled'].includes(state))throw new IntegrityViolation();
        const completion_sha256=journal.completion_sha256===null?null:digest(journal.completion_sha256);
        if((state==='settled')!==(completion_sha256!==null))throw new IntegrityViolation();
        const view=await this.#dispatchView(tx,context,journal);
        const memberships=await this.#select(tx,'dispatch_points',['backend_namespace','physical_collection','collection_incarnation','point_id'],context,
          ' AND intent_id=$4 AND dispatch_id=$5',[context.intent_id,dispatch_id],9);
        if(memberships.length!==view.point_ids.length)throw new IntegrityViolation();
        for(const member of memberships){
          if(member.backend_namespace!==this.#config.backend_namespace||member.physical_collection!==this.#config.physical_collection
            ||member.collection_incarnation!==this.#config.collection_incarnation||!view.point_ids.includes(uuid(member.point_id)))throw new IntegrityViolation();
        }
        const claims=await this.#select(tx,'point_claims',['instance_id','backend_namespace','physical_collection','collection_incarnation','point_id'],context,
          ' AND point_id=ANY($4::uuid[])',[view.point_ids],9);
        if(claims.length!==view.point_ids.length||new Set(claims.map(claim=>claim.point_id)).size!==view.point_ids.length)throw new IntegrityViolation();
        for(const claim of claims){
          if(claim.instance_id!==this.#instance||claim.backend_namespace!==this.#config.backend_namespace
            ||claim.physical_collection!==this.#config.physical_collection||claim.collection_incarnation!==this.#config.collection_incarnation
            ||!view.point_ids.includes(uuid(claim.point_id)))throw new IntegrityViolation();
        }
        // The strict parser owns a bounded null-prototype graph. Native copies
        // let the existing descriptor guards validate operation shape safely.
        const native=(value:unknown):unknown=>{
          if(Array.isArray(value))return value.map(native);
          if(value!==null&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,native(item)]));
          return value;
        };
        const body=native(parse_response(Buffer.from(view.request_bytes)));
        if(typeof body!=='object'||body===null||Array.isArray(body)||Object.keys(body).length!==1
          ||!Object.hasOwn(body,'points'))throw new IntegrityViolation();
        const points=native_array((body as Data).points,1,8);
        const ids=points.map(point=>{
          if(operation==='delete_points')return uuid(point);
          if(typeof point!=='object'||point===null||Array.isArray(point))throw new IntegrityViolation();
          const keys=Object.keys(point);
          if(keys.length!==3||!['id','vector','payload'].every(key=>Object.hasOwn(point,key)))throw new IntegrityViolation();
          const record=point as Data;
          if(typeof record.vector!=='object'||record.vector===null||Array.isArray(record.vector)
            ||typeof record.payload!=='object'||record.payload===null||Array.isArray(record.payload))throw new IntegrityViolation();
          return uuid(record.id);
        }).sort();
        if(!same(ids,view.point_ids))throw new IntegrityViolation();
        return Object.freeze({dispatch_id,sequence,owner_token,backend_epoch,credential_generation,operation,state,
          completion_sha256,request_sha256:view.request_sha256,point_ids:view.point_ids});
      } catch(error) {
        if(error instanceof InvalidRequest)throw new IntegrityViolation();
        throw error;
      }
  }

  #requireAttestationProfile():void{
    if(this.#closed||this.#active)throw new ProviderUnavailable();
    if(!this.#initialized)throw new IndexNotReady();
    if(this.#profile!=='attestation')throw new UnsupportedCapability();
  }
  async #originalPreparation(tx:Tx,context:WriterContext,intent:Data):Promise<PreparationMetadata>{
    const rows=await this.#select(tx,'preparations',['instance_id','owner_token','backend_epoch','authorization_revision','mutation_epoch','manifest_sha256','readback_sha256'],context,' AND intent_id=$4',[context.intent_id],2);
    if(rows.length!==1)throw new IntegrityViolation();
    try{
      const row=rows[0],preparation=Object.freeze({owner_token:uuid(row.owner_token),backend_epoch:db_count(row.backend_epoch),authorization_revision:text(row.authorization_revision),mutation_epoch:db_count(row.mutation_epoch),manifest_sha256:digest(row.manifest_sha256),readback_sha256:digest(row.readback_sha256)});
      if(row.instance_id!==this.#instance||preparation.backend_epoch<1||preparation.manifest_sha256!==intent.manifest_sha256
        ||preparation.authorization_revision!==intent.expected_authorization_revision||preparation.mutation_epoch!==db_count(intent.expected_mutation_epoch))throw new IntegrityViolation();
      return preparation;
    }catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
  }
  async #currentAttestation(tx:Tx,context:WriterContext,intent:Data,epoch:number):Promise<PreparationAttestation|null>{
    const rows=await this.#select(tx,'preparation_attestations',ATTESTATION_COLUMNS,context,
      ' AND intent_id=$4 AND backend_epoch=$5 AND owner_token=$6::uuid AND instance_id=$7',[context.intent_id,epoch,context.owner_token,this.#instance],2);
    if(rows.length>1)throw new IntegrityViolation();if(rows.length===0)return null;
    try{
      const row=rows[0];
      for(const key of ['tenant_id','collection','document_id','intent_id','instance_id','authorization_revision','credential_generation','verification_id'])text(row[key],key==='collection');
      const result=Object.freeze({...row,owner_token:uuid(row.owner_token),backend_epoch:db_count(row.backend_epoch),mutation_epoch:db_count(row.mutation_epoch),manifest_sha256:digest(row.manifest_sha256),readback_sha256:digest(row.readback_sha256),expected_active_generation_id:row.expected_active_generation_id===null?null:text(row.expected_active_generation_id)}) as PreparationAttestation;
      if(result.tenant_id!==context.scope.tenant_id||result.collection!==context.collection||result.document_id!==context.document_id||result.intent_id!==context.intent_id||result.instance_id!==this.#instance
        ||result.owner_token!==context.owner_token||result.backend_epoch!==epoch||result.backend_epoch<1||result.manifest_sha256!==intent.manifest_sha256||result.authorization_revision!==intent.expected_authorization_revision
        ||result.mutation_epoch!==db_count(intent.expected_mutation_epoch)||result.expected_active_generation_id!==intent.expected_active_generation_id)throw new IntegrityViolation();
      return result;
    }catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
  }
  async attestation_snapshot(input:unknown,rawOptions:unknown):Promise<Readonly<{preparation:PreparationMetadata;attestation:PreparationAttestation|null}>>{
    const context=parseContext(input),options=parseOptions(rawOptions);this.#requireAttestationProfile();
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const locked=await this.#locks(tx,context);
      const intent=await this.#intent(tx,context);if(!intent||intent.action!=='stage'||intent.state!=='prepared')throw new InvalidRequest();
      const failure=await this.#fence(tx,context,intent);if(failure)throw failure==='denied'?new UnauthorizedScope():new ProviderUnavailable();
      if(await this.#managerPending(tx,context))throw new ProviderUnavailable();
      await this.#loadStage(tx,context);
      const preparation=await this.#originalPreparation(tx,context,intent);
      const attestation=await this.#currentAttestation(tx,context,intent,locked.epoch);
      if(preparation.backend_epoch>locked.epoch||(attestation&&locked.epoch<=preparation.backend_epoch))throw new IntegrityViolation();
      return Object.freeze({preparation,attestation});
    }));
  }
  async attest_prepared(receipt:unknown,verifier:QdrantPublicationVerifier,rawOptions:unknown):Promise<Readonly<{intent:IntentView;attestation:PreparationAttestation|null}>>{
    const parsed=parseOptions(rawOptions);this.#requireAttestationProfile();
    // Only deadline/signal cross the controller boundary; owner_token is SQL-only.
    const options:LeaseOptions={deadline:parsed.deadline,...(parsed.signal===undefined?{}:{signal:parsed.signal})};
    const proof=await attestation_receipt_data(receipt,verifier,this,options);
    const controller=publication_verifier_controller(verifier,this);
    const context=parseContext(proof.context);
    let projectionFailure:unknown;
    try{await this.validate_publication_projection(proof.projection,options);}
    catch(error){if(!(error instanceof UnauthorizedScope))throw error;projectionFailure=error;}
    await attestation_receipt_data(receipt,verifier,this,options);
    type Result=Readonly<{intent:IntentView;attestation:PreparationAttestation|null}>;
    const operation=async(tx:Tx,insert:boolean):Promise<Result|null>=>{
      require_publication_finalization(controller,options);
      const locked=await this.#locks(tx,context,false);
      const intent=await this.#intent(tx,context);if(!intent||intent.action!=='stage')throw new InvalidRequest();
      if(['conflict','denied'].includes(String(intent.state)))return Object.freeze({intent:intent_view(intent),attestation:null});
      if(intent.state!=='prepared')throw new InvalidRequest();
      const failure=await this.#fence(tx,context,intent);
      if(failure){const terminal=await this.#updateIntent(tx,context,failure);require_publication_finalization(controller,options);return Object.freeze({intent:terminal,attestation:null});}
      this.#requireLockedOwner(context,locked);
      if(projectionFailure)throw projectionFailure;
      if(await this.#managerPending(tx,context))throw new ProviderUnavailable();
      const preparation=await this.#originalPreparation(tx,context,intent);
      if(locked.epoch<=preparation.backend_epoch)throw new ProviderUnavailable();
      const current=await this.#projectPublication(tx,context,proof.attempt_binding);
      if(current.readback_sha256!==proof.readback_sha256||current.manifest_sha256!==intent.manifest_sha256||current.revision_id!==intent.revision_id||current.generation_id!==intent.generation_id)throw new IntegrityViolation();
      const record:PreparationAttestation=Object.freeze({tenant_id:context.scope.tenant_id,collection:context.collection,document_id:context.document_id,intent_id:context.intent_id,instance_id:this.#instance,
        owner_token:context.owner_token,backend_epoch:locked.epoch,authorization_revision:text(intent.expected_authorization_revision),mutation_epoch:db_count(intent.expected_mutation_epoch),manifest_sha256:digest(intent.manifest_sha256),
        expected_active_generation_id:intent.expected_active_generation_id===null?null:text(intent.expected_active_generation_id),credential_generation:text(proof.attempt_binding.credential_generation),verification_id:text(proof.attempt_binding.dispatch_id),readback_sha256:digest(proof.readback_sha256)});
      let attestation=await this.#currentAttestation(tx,context,intent,locked.epoch);
      if(attestation&&!same(attestation,record))throw new IntegrityViolation();
      require_publication_finalization(controller,options);
      if(!attestation&&insert){
        await this.#insert(tx,'preparation_attestations',record);
        attestation=await this.#currentAttestation(tx,context,intent,locked.epoch);
        if(!attestation||!same(attestation,record))throw new IntegrityViolation();
      }
      require_publication_finalization(controller,options);
      return attestation?Object.freeze({intent:intent_view(intent),attestation}):null;
    };
    return this.#work(options,async lease=>{
      const mutate=async(tx:Tx)=>{const result=await operation(tx,true);if(!result)throw new IntegrityViolation();return result;};
      try{return await this.#tx(context,lease,mutate,true);}
      catch(error){
        if(!(error instanceof CommitUnknown))throw error;
        const confirmed=await this.#tx(context,lease,tx=>operation(tx,false),true);
        if(confirmed)return confirmed;
        // The only retry follows an actual COMMIT-unknown and fresh exact-key absence.
        try{return await this.#tx(context,lease,mutate,true);}
        catch(retryError){if(!(retryError instanceof CommitUnknown))throw retryError;const final=await this.#tx(context,lease,tx=>operation(tx,false),true);if(!final)throw new ProviderUnavailable();return final;}
      }
    });
  }
  async publication_preparation(input:unknown,rawOptions:unknown):Promise<Readonly<{
    preparation:Readonly<{owner_token:string;backend_epoch:number;authorization_revision:string;mutation_epoch:number;
      manifest_sha256:string;readback_sha256:string}>;dispatch:DispatchStatus;
  }>|null> {
    const context=parseContext(input),options=parseOptions(rawOptions);
    return this.#work(options,lease=>this.#tx(context,lease,async tx=>{
      const document=await this.#document(tx,context);
      if(!document||document.authorization_revision!==context.scope.authorization_revision)throw new UnauthorizedScope();
      const backend=await this.#managerBackend(tx);
      const intent=await this.#intent(tx,context);
      if(!intent||intent.action!=='stage')throw new InvalidRequest();
      const rows=await this.#select(tx,'preparations',['instance_id','owner_token','backend_epoch','authorization_revision','mutation_epoch','manifest_sha256','readback_sha256'],context,
        ' AND intent_id=$4',[context.intent_id],2);
      if(rows.length===0){
        if(intent.state==='prepared'||intent.state==='published')throw new IntegrityViolation();
        return null;
      }
      if(rows.length!==1)throw new IntegrityViolation();
      try {
        const row=rows[0];
        const preparation=Object.freeze({owner_token:uuid(row.owner_token),backend_epoch:db_count(row.backend_epoch),
          authorization_revision:text(row.authorization_revision),mutation_epoch:db_count(row.mutation_epoch),
          manifest_sha256:digest(row.manifest_sha256),readback_sha256:digest(row.readback_sha256)});
        if(row.instance_id!==this.#instance||preparation.backend_epoch<1||preparation.manifest_sha256!==intent.manifest_sha256
          ||preparation.authorization_revision!==intent.expected_authorization_revision
          ||preparation.mutation_epoch!==db_count(intent.expected_mutation_epoch))throw new IntegrityViolation();
        if(backend.state!=='open'||backend.epoch!==preparation.backend_epoch)throw new ProviderUnavailable();
        if(await this.#managerPending(tx,context))throw new ProviderUnavailable();
        await this.#loadStage(tx,context);
        const journals=await this.#select(tx,'dispatch_journal',['dispatch_id','sequence','state'],context,' AND intent_id=$4',[context.intent_id],257);
        if(journals.length<1||journals.length>256)throw new IntegrityViolation();
        const ids=new Set<string>(),sequences=new Set<number>();
        let selected:string|null=null,max=0;
        for(const journal of journals){
          const id=text(journal.dispatch_id),sequence=db_count(journal.sequence);
          if(sequence<1||sequence>256||ids.has(id)||sequences.has(sequence))throw new IntegrityViolation();
          ids.add(id);sequences.add(sequence);
          if(journal.state!=='settled')throw new ProviderUnavailable();
          if(sequence>max){max=sequence;selected=id;}
        }
        const dispatch=await this.#dispatchStatus(tx,context,selected!);
        if(!dispatch||dispatch.state!=='settled'||dispatch.operation!=='complete_point_upsert'
          ||dispatch.owner_token!==preparation.owner_token||dispatch.backend_epoch!==preparation.backend_epoch)throw new IntegrityViolation();
        return Object.freeze({preparation,dispatch});
      } catch(error) {
        if(error instanceof InvalidRequest)throw new IntegrityViolation();
        throw error;
      }
    }));
  }
  async reserve_dispatch(input:unknown,rawDispatch:unknown,rawOptions:unknown):Promise<DispatchView>{
    const context=parseContext(input),options=parseOptions(rawOptions);
    let dispatch:ReturnType<typeof DispatchOptionsSchema.parse>;
    try{dispatch=DispatchOptionsSchema.parse(metadata(rawDispatch));}catch(error){if(error instanceof InvalidRequest)throw error;throw new InvalidRequest();}
    if(new Set(dispatch.point_ids).size!==dispatch.point_ids.length)throw new InvalidRequest();
    const point_ids=Object.freeze([...dispatch.point_ids].sort());
    const reconcile=async(tx:Tx)=>{
      await this.#locks(tx,context);
      const intent=await this.#intent(tx,context);
      if(!intent||await this.#fence(tx,context,intent))throw new UnauthorizedScope();
      const journal=await this.#journal(tx,context,dispatch.dispatch_id);
      if(!journal||journal.operation!==dispatch.operation||journal.credential_generation!==dispatch.credential_generation
        ||db_count(journal.sequence)!==dispatch.sequence||journal.owner_token!==context.owner_token||journal.recovery)throw new IntegrityViolation();
      const result=await this.#dispatchView(tx,context,journal);
      if(!same(result.point_ids,point_ids))throw new IntegrityViolation();
      return result;
    };
    return this.#mutation(context,options,async tx=>{
      const {epoch}=await this.#locks(tx,context);
      if(await this.#journal(tx,context,dispatch.dispatch_id))return reconcile(tx);
      const intent=await this.#intent(tx,context);
      if(!intent||await this.#fence(tx,context,intent))throw new UnauthorizedScope();
      const document=await this.#document(tx,context,true);
      if(!document)throw new UnauthorizedScope();
      if(dispatch.operation==='delete_points'){
        if(intent.action!=='purge'||!document.tombstoned)throw new InvalidRequest();
      }else if(document.tombstoned)throw new UnauthorizedScope();
      const pending=await this.#select(tx,'dispatch_journal',['state'],context," AND state<>'settled'",[],1);
      if(pending.length)throw new ProviderUnavailable();
      const claims=await this.#select(tx,'point_claims',CLAIM_COLUMNS,context,' AND point_id=ANY($4::uuid[])',[point_ids],9);
      if(claims.length!==point_ids.length||new Set(claims.map(claim=>claim.point_id)).size!==point_ids.length)throw new IntegrityViolation();
      const points:Data[]=[];
      for(const id of point_ids){
        const claim=claims.find(value=>value.point_id===id);
        if(!claim)throw new IntegrityViolation();
        if(dispatch.operation==='delete_points'){
          await this.#point(tx,context,claim);
          continue;
        }
        if(intent.action==='stage'&&(claim.revision_id!==intent.revision_id||claim.generation_id!==intent.generation_id))throw new IntegrityViolation();
        const restored=await this.#point(tx,context,claim);
        const payload:Data={backend_namespace:claim.backend_namespace,physical_collection:claim.physical_collection,
          collection_incarnation:claim.collection_incarnation,tenant_id:context.scope.tenant_id,collection:context.collection,
          document_id:context.document_id,revision_id:claim.revision_id,generation_id:claim.generation_id,chunk_id:claim.chunk_id,
          start_byte:db_count(claim.start_byte),end_byte:db_count(claim.end_byte),source_sha256:digest(claim.source_sha256),text_sha256:digest(claim.text_sha256),
          dense_profile_id:this.#config.dense_profile.profile_id,sparse_profile_id:this.#config.sparse_profile?.profile_id??'',
          dense_profile:this.#config.dense_profile,sparse_profile:this.#config.sparse_profile,
          authorization_revision:text(document.authorization_revision),principal_ids:db_json(document.principal_ids),grant_ids:db_json(document.grant_ids)};
        for(const key of ['language','kind','tag'])if(document[key]!==null)payload[key]=document[key];
        const vector:Data={dense:restored.dense.values};
        if(restored.sparse)vector.sparse={indices:restored.sparse.indices,values:restored.sparse.values};
        points.push({id,vector,payload});
      }
      const body=JSON.stringify(dispatch.operation==='delete_points'?{points:point_ids}:{points});
      if(Buffer.byteLength(body)>1048576)throw new InvalidRequest();
      const bytes=Buffer.from(body);
      const record:Data={...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),intent_id:context.intent_id,
        dispatch_id:dispatch.dispatch_id,instance_id:this.#instance,sequence:dispatch.sequence,owner_token:context.owner_token,
        backend_epoch:epoch,credential_generation:dispatch.credential_generation,operation:dispatch.operation,
        request_bytes:bytes,request_sha256:hash(bytes)};
      await this.#insert(tx,'dispatch_journal',record);
      for(const id of point_ids)await this.#insert(tx,'dispatch_points',{...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),
        intent_id:context.intent_id,dispatch_id:dispatch.dispatch_id,backend_namespace:this.#config.backend_namespace,
        physical_collection:this.#config.physical_collection,collection_incarnation:this.#config.collection_incarnation,point_id:id});
      return reconcile(tx);
    },reconcile);
  }
  async #mark(input:unknown,rawId:unknown,rawOptions:unknown,state:'dispatched'|'unknown'|'settled',receipt?:unknown):Promise<DispatchView>{
    const context=parseContext(input),dispatch_id=text(rawId),options=parseOptions(rawOptions);
    const completion=state==='settled'?digest(receipt):null;
    const verify=async(tx:Tx)=>{
      await this.#locks(tx,context);
      if(state==='dispatched'){
        const intent=await this.#intent(tx,context);
        if(!intent||await this.#fence(tx,context,intent))throw new UnauthorizedScope();
      }
      const journal=await this.#journal(tx,context,dispatch_id);
      if(!journal||journal.state!==state||(state==='settled'&&journal.completion_sha256!==completion))throw new ProviderUnavailable();
      return this.#dispatchView(tx,context,journal);
    };
    return this.#mutation(context,options,async tx=>{
      await this.#locks(tx,context);
      if(state==='dispatched'){
        const intent=await this.#intent(tx,context);
        if(!intent||await this.#fence(tx,context,intent))throw new UnauthorizedScope();
      }
      const rows=await this.#select(tx,'dispatch_journal',JOURNAL_COLUMNS,context,' AND intent_id=$4 AND dispatch_id=$5 FOR UPDATE',[context.intent_id,dispatch_id],2);
      if(rows.length!==1)throw new InvalidRequest();
      const journal=rows[0];
      if(journal.owner_token!==context.owner_token||journal.recovery)throw new IntegrityViolation();
      if(journal.state===state)return verify(tx);
      if(journal.state==='unknown'&&(state==='dispatched'||state==='settled'))throw new ProviderUnavailable();
      if(journal.state==='settled'||(state==='dispatched'&&journal.state!=='reserved'))throw new InvalidRequest();
      await tx.query('UPDATE cragkit_qdrant.dispatch_journal SET state=$6,completion_sha256=$7 WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=($1,$2,$3,$4,$5)',
        [...this.#key(context),context.intent_id,dispatch_id,state,completion],0);
      return verify(tx);
    },verify);
  }
  async mark_dispatched(context:unknown,dispatch_id:unknown,options:unknown):Promise<void>{await this.#mark(context,dispatch_id,options,'dispatched');}
  async mark_unknown(context:unknown,dispatch_id:unknown,options:unknown):Promise<void>{await this.#mark(context,dispatch_id,options,'unknown');}
  async settle_dispatch(context:unknown,dispatch_id:unknown,completion_sha256:unknown,options:unknown):Promise<void>{await this.#mark(context,dispatch_id,options,'settled',completion_sha256);}
  async prepare(input:unknown,rawReadback:unknown,rawOptions:unknown):Promise<IntentView>{
    const context=parseContext(input),readback=digest(rawReadback),options=parseOptions(rawOptions);
    const verify=async(tx:Tx)=>{
      const intent=await this.#intent(tx,context);
      if(intent&&['conflict','denied'].includes(String(intent.state)))return intent_view(intent);
      const rows=await this.#select(tx,'preparations',['instance_id','owner_token','backend_epoch','authorization_revision','mutation_epoch','manifest_sha256','readback_sha256'],context,
        ' AND intent_id=$4',[context.intent_id],2);
      if(rows.length!==1||!intent||!['prepared','published'].includes(String(intent.state))
        ||rows[0].instance_id!==this.#instance||rows[0].owner_token!==context.owner_token||rows[0].manifest_sha256!==intent.manifest_sha256
        ||rows[0].readback_sha256!==readback)throw new IntegrityViolation();
      return intent_view(intent);
    };
    return this.#mutation(context,options,async tx=>{
      const intent=await this.#intent(tx,context);
      if(!intent||intent.action!=='stage')throw new InvalidRequest();
      if(['published','conflict','denied'].includes(String(intent.state)))return verify(tx);
      if(!['writing','prepared'].includes(String(intent.state)))throw new InvalidRequest();
      const preliminary=await this.#fence(tx,context,intent,false);
      if(preliminary)return this.#updateIntent(tx,context,preliminary);
      const locked=await this.#locks(tx,context,false);
      const failure=await this.#fence(tx,context,intent);
      if(failure)return this.#updateIntent(tx,context,failure);
      this.#requireLockedOwner(context,locked);
      const epoch=locked.epoch;
      if(intent.state==='prepared')return verify(tx);
      const pending=await this.#select(tx,'dispatch_journal',['state'],context," AND state<>'settled'",[],1);
      if(pending.length)throw new ProviderUnavailable();
      await this.#loadStage(tx,context);
      const record:Data={...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),intent_id:context.intent_id,
        instance_id:this.#instance,owner_token:context.owner_token,backend_epoch:epoch,
        authorization_revision:intent.expected_authorization_revision,mutation_epoch:db_count(intent.expected_mutation_epoch),
        manifest_sha256:intent.manifest_sha256,readback_sha256:readback};
      await this.#ensure(tx,'preparations',record,context,' AND intent_id=$4',[context.intent_id]);
      await this.#updateIntent(tx,context,'prepared');
      return verify(tx);
    },verify);
  }
  async publish(input:unknown,rawOptions:unknown):Promise<IntentView>{
    const context=parseContext(input),options=parseOptions(rawOptions);
    const verify=async(tx:Tx)=>{
      const intent=await this.#intent(tx,context);
      if(!intent||!['published','conflict','denied'].includes(String(intent.state)))throw new ProviderUnavailable();
      if(intent.state==='published'){
        // The durable intent records this operation's committed outcome. A
        // later generation may now be active; replay never republishes it.
        if(!intent.authority_committed||!intent.replica_complete)throw new IntegrityViolation();
      }
      return intent_view(intent);
    };
    return this.#mutation(context,options,async tx=>{
      const intent=await this.#intent(tx,context);
      if(!intent||intent.action!=='stage')throw new InvalidRequest();
      if(['published','conflict','denied'].includes(String(intent.state)))return verify(tx);
      if(intent.state!=='prepared')throw new InvalidRequest();
      const preliminary=await this.#fence(tx,context,intent,false);
      if(preliminary)return this.#updateIntent(tx,context,preliminary);
      const locked=await this.#locks(tx,context,false);
      const failure=await this.#fence(tx,context,intent);
      if(failure)return this.#updateIntent(tx,context,failure);
      this.#requireLockedOwner(context,locked);
      const pending=await this.#select(tx,'dispatch_journal',['state'],context," AND state<>'settled'",[],1);
      if(pending.length)throw new ProviderUnavailable();
      await this.#loadStage(tx,context);
      const preparation=await this.#originalPreparation(tx,context,intent);
      const originalCurrent=preparation.owner_token===context.owner_token&&preparation.backend_epoch===locked.epoch;
      if(!originalCurrent){
        if(this.#profile!=='attestation')throw new ProviderUnavailable();
        const attestation=await this.#currentAttestation(tx,context,intent,locked.epoch);
        if(!attestation)throw new ProviderUnavailable();
        if(locked.epoch<=preparation.backend_epoch)throw new IntegrityViolation();
      }
      await tx.query('UPDATE cragkit_qdrant.generations SET published=false WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND generation_id<>$4 AND published',
        [...this.#key(context),intent.generation_id],0);
      await tx.query('UPDATE cragkit_qdrant.generations SET published=true,ever_published=true WHERE (tenant_id,collection,document_id,generation_id)=($1,$2,$3,$4)',
        [...this.#key(context),intent.generation_id],0);
      const changed=await tx.query('UPDATE cragkit_qdrant.documents SET active_generation_id=$4 WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND active_generation_id IS NOT DISTINCT FROM $5 AND authorization_revision=$6 AND mutation_epoch=$7 AND NOT tombstoned RETURNING document_id',
        [...this.#key(context),intent.generation_id,intent.expected_active_generation_id,intent.expected_authorization_revision,db_count(intent.expected_mutation_epoch)],1);
      if(changed.length!==1)throw new IntegrityViolation();
      await this.#updateIntent(tx,context,'published',true);
      return verify(tx);
    },verify);
  }
  async apply_security(input:unknown,inputScope:unknown,rawOptions:unknown):Promise<IntentView>{
    const options=parseOptions(rawOptions,true),change=parseOperation(input,inputScope,options.owner_token);
    const record=change.record;
    const context=parseContext({scope:change.scope,collection:record.collection,document_id:record.document_id,
      intent_id:record.intent_id,owner_token:change.owner_token});
    const desired=native_array(change.encoded.value[8],7,7);
    const encoded=Buffer.from(change.encoded.encoded_bytes);
    const intentRecord:Data={...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),intent_id:context.intent_id,
      instance_id:this.#instance,action:record.action,payload_bytes:encoded,payload_sha256:change.encoded.sha256,
      manifest_bytes:null,manifest_sha256:null,revision_id:null,generation_id:null,expected_active_generation_id:null,
      expected_authorization_revision:record.expected_authorization_revision,expected_mutation_epoch:record.expected_mutation_epoch};
    const verify=async(tx:Tx)=>{
      const existing=await this.#intent(tx,context);
      if(!existing||Object.keys(intentRecord).some(key=>!TARGET.includes(key)&&key!=='intent_id'&&!exact(existing[key],intentRecord[key])))throw new IntegrityViolation();
      return intent_view(existing);
    };
    return this.#mutation(context,options,async tx=>{
      const existing=await this.#intent(tx,context);
      if(existing){
        const result=await verify(tx);
        if(existing.authority_committed||['denied','conflict'].includes(result.state))return result;
      }
      if(context.scope.authorization_revision!==record.expected_authorization_revision)throw new UnauthorizedScope();
      if(!existing)await this.#ensure(tx,'publication_intents',intentRecord,context,' AND intent_id=$4',[context.intent_id]);
      // No backend/owner lock: revocation must commit despite unknown writes/recovery.
      const document=await this.#document(tx,context,true);
      const expectedEpoch=count(record.expected_mutation_epoch);
      if(!document||document.authorization_revision!==record.expected_authorization_revision
        ||db_count(document.mutation_epoch)!==expectedEpoch
        ||(document.tombstoned&&desired[6]!=='true'))return this.#updateIntent(tx,context,'denied');
      if(expectedEpoch===Number.MAX_SAFE_INTEGER)throw new InvalidRequest();
      const changed=await tx.query('UPDATE cragkit_qdrant.documents SET principal_ids=$4,grant_ids=$5,authorization_revision=$6,mutation_epoch=$7,language=$8,kind=$9,tag=$10,tombstoned=$11 WHERE (tenant_id,collection,document_id)=($1,$2,$3) AND authorization_revision=$12 AND mutation_epoch=$13 RETURNING document_id',
        [...this.#key(context),desired[1],desired[2],desired[0],expectedEpoch+1,desired[3],desired[4],desired[5],desired[6]==='true',record.expected_authorization_revision,expectedEpoch],1);
      if(changed.length!==1)return this.#updateIntent(tx,context,'denied');
      await tx.query("UPDATE cragkit_qdrant.publication_intents SET state='authority_committed',authority_committed=true WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4)",
        [...this.#key(context),context.intent_id],0);
      return verify(tx);
    },verify);
  }
  async bind_purge(input:unknown,inputScope:unknown,rawOptions:unknown):Promise<IntentView>{
    const options=parseOptions(rawOptions,true),bound=parseOperation(input,inputScope,options.owner_token,true),record=bound.record;
    const context=parseContext({scope:bound.scope,collection:record.collection,document_id:record.document_id,
      intent_id:record.intent_id,owner_token:bound.owner_token});
    const intentRecord:Data={...Object.fromEntries(TARGET.map((key,i)=>[key,this.#key(context)[i]])),intent_id:context.intent_id,
      instance_id:this.#instance,action:'purge',payload_bytes:Buffer.from(bound.encoded.encoded_bytes),payload_sha256:bound.encoded.sha256,
      manifest_bytes:null,manifest_sha256:null,revision_id:null,generation_id:null,expected_active_generation_id:null,
      expected_authorization_revision:record.expected_authorization_revision,expected_mutation_epoch:record.expected_mutation_epoch};
    const verify=async(tx:Tx)=>{
      const existing=await this.#intent(tx,context);
      if(!existing||Object.keys(intentRecord).some(key=>!TARGET.includes(key)&&key!=='intent_id'&&!exact(existing[key],intentRecord[key])))throw new IntegrityViolation();
      return intent_view(existing);
    };
    return this.#mutation(context,options,async tx=>{
      const existing=await this.#intent(tx,context);
      if(existing)return verify(tx);
      if(context.scope.authorization_revision!==record.expected_authorization_revision)throw new UnauthorizedScope();
      const document=await this.#document(tx,context,true);
      if(!document||!document.tombstoned||document.authorization_revision!==record.expected_authorization_revision
        ||db_count(document.mutation_epoch)!==record.expected_mutation_epoch)throw new UnauthorizedScope();
      const tombstones=await this.#select(tx,'publication_intents',['action','authority_committed','payload_sha256'],context,
        ' AND payload_sha256=$4',[record.tombstone_intent_payload_sha256],2);
      if(tombstones.length!==1||tombstones[0].action!=='tombstone'||tombstones[0].authority_committed!==true)throw new IntegrityViolation();
      await this.#ensure(tx,'publication_intents',intentRecord,context,' AND intent_id=$4',[context.intent_id]);
      await tx.query("UPDATE cragkit_qdrant.publication_intents SET state='authority_committed',authority_committed=true WHERE (tenant_id,collection,document_id,intent_id)=($1,$2,$3,$4)",
        [...this.#key(context),context.intent_id],0);
      return verify(tx);
    },verify);
  }
  async close():Promise<void>{
    if(!this.#closing){
      this.#closed=true;
      this.#closing=(async()=>{const active=this.#active;if(active){active.controller.abort();await bounded(active.done,{deadline:now()+this.#resource.config.close_timeout});}})();
    }
    return this.#closing;
  }
}
