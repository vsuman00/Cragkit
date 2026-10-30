/** Same-session security evidence only; settlement belongs to the coordinator. */
import {randomUUID} from 'node:crypto';
import {types} from 'node:util';
import {PostgresQdrantWriter,writer_binding,require_security_guard_writer,security_recovery_projection,security_projection_data,purge_projection_data,PURGE_RETENTION_POLICY,type PurgeProjection,type SecurityProjection,type SecurityProjectionData} from './qdrant-writer.js';
import {require_publication_finalization} from './qdrant-publication-worker.js';
import {ManagedQdrantSupervisor,control_session_binding,type SupervisorControlSession,type SupervisorTransport} from './qdrant-supervisor.js';
import {verify_security_readback,security_readback_budget,type SecurityReadbackBudget} from './qdrant-security-readback.js';
import {context as parse_context,options as parse_options,metadata,fields,count,text,uuid,hash,type WriterContext,type Data} from './qdrant-writer-contract.js';
import {same} from './qdrant-contract.js';
import {bounded,now,type LeaseOptions} from './postgres-pool.js';
import {InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,DeadlineExceeded,IndexNotReady,EmbeddingProfileMismatch} from './errors.js';

export type SecurityReceipt=Readonly<Record<never,never>>;
export type SecurityReceiptData=Readonly<{projection:SecurityProjection;owner_context:WriterContext;security_context:WriterContext;
  physical_binding:Readonly<Data>;attempt_binding:Readonly<Data>;activity:number;intent_sha256:string;inventory_sha256:string;
  point_ids:readonly string[];readback_sha256:string;witness:readonly unknown[];encoded_bytes:readonly number[];sha256:string}>;
type Registration={writer:PostgresQdrantWriter;supervisor:ManagedQdrantSupervisor;closed:boolean};
const verifiers=new WeakMap<object,Registration>();
type Issued={issuer:QdrantSecurityVerifier;control:SupervisorControlSession;proof:unknown;attempt:unknown;
  deadline:number;signal?:AbortSignal;data:SecurityReceiptData};
const receipts=new WeakMap<object,Issued>();
export type OrdinarySecurityReceipt=Readonly<Record<never,never>>;
export type OrdinarySecurityReceiptData=Readonly<{context:WriterContext;projection:SecurityProjection;attempt_binding:Readonly<Data>;
  intent_sha256:string;inventory_sha256:string;readback_sha256:string;witness:readonly unknown[];encoded_bytes:readonly number[];sha256:string}>;
export type PurgeAbsenceReceipt=Readonly<Record<never,never>>;
export type PurgeAbsenceReceiptData=Readonly<{context:WriterContext;tombstone_context:WriterContext;projection:PurgeProjection;
  attempt_binding:Readonly<Data>;purge_payload_sha256:string;inventory_sha256:string;absence_sha256:string;
  witness:readonly unknown[];encoded_bytes:readonly number[];sha256:string}>;
const purgeReceipts=new WeakMap<object,Readonly<{issuer:QdrantSecurityVerifier;attempt:unknown;options:LeaseOptions;data:PurgeAbsenceReceiptData}>>();
const purgeVerifiers=new WeakMap<object,(attempt:unknown,context:WriterContext,projection:PurgeProjection,options:LeaseOptions,budget:SecurityReadbackBudget)=>Promise<PurgeAbsenceReceipt>>();
export async function verify_purge_ordinary(verifier:unknown,attempt:unknown,rawContext:unknown,projection:unknown,rawOptions:unknown,inputBudget?:SecurityReadbackBudget):Promise<PurgeAbsenceReceipt>{
  const original=registration(verifier),context=parse_context(rawContext),options=parse_options(rawOptions),budget=security_readback_budget(inputBudget);
  purge_projection_data(projection,original.writer);const verify=purgeVerifiers.get(verifier as object);
  if(!verify)throw new InvalidRequest();return verify(attempt,context,projection as PurgeProjection,options,budget);
}
export function purge_absence_receipt_data(receipt:unknown,verifier:QdrantSecurityVerifier,rawOptions:unknown):PurgeAbsenceReceiptData{
  const original=registration(verifier),options=parse_options(rawOptions);
  if(typeof receipt!=='object'||receipt===null||types.isProxy(receipt))throw new InvalidRequest();
  const issued=purgeReceipts.get(receipt);
  if(!issued||issued.issuer!==verifier||original.closed||options.deadline>issued.options.deadline||options.signal!==issued.options.signal)throw new InvalidRequest();
  parse_options(issued.options);require_publication_finalization(original.supervisor,options);
  if(!same(ordinaryBinding(original,issued.attempt,issued.data.context),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
}
const ordinaryReceipts=new WeakMap<object,Readonly<{issuer:QdrantSecurityVerifier;attempt:unknown;options:LeaseOptions;data:OrdinarySecurityReceiptData}>>();
const ordinaryVerifiers=new WeakMap<object,(attempt:unknown,context:WriterContext,options:LeaseOptions,budget:SecurityReadbackBudget)=>Promise<OrdinarySecurityReceipt>>();
function exact(value:unknown,prototype:object):boolean{return typeof value==='object'&&value!==null&&!types.isProxy(value)&&Object.getPrototypeOf(value)===prototype;}
function registration(value:unknown):Registration{
  if(!exact(value,QdrantSecurityVerifier.prototype))throw new InvalidRequest();const found=verifiers.get(value as object);
  if(!found)throw new InvalidRequest();writer_binding(found.writer);return found;
}
export function security_verifier_binding(verifier:unknown,writer:unknown,supervisor:unknown):void{
  const original=registration(verifier);writer_binding(writer);
  if(original.writer!==writer||original.supervisor!==supervisor||original.closed)throw new InvalidRequest();
}
export function security_verifier_supervisor(verifier:unknown,writer:PostgresQdrantWriter):ManagedQdrantSupervisor{
  const original=registration(verifier);writer_binding(writer);
  if(original.writer!==writer||original.closed)throw new InvalidRequest();return original.supervisor;
}
function ordinaryBinding(original:Registration,attempt:unknown,context:WriterContext):Readonly<Data>{
  const actual=metadata(original.supervisor.attempt_binding(attempt));
  if(Object.hasOwn(actual,'recovery_id'))throw new UnsupportedCapability();
  fields(actual,['instance_id','storage_identity','supervisor_id','epoch','credential_generation','intent_id','owner_token','dispatch_id']);
  for(const key of ['instance_id','storage_identity','supervisor_id','credential_generation','intent_id','dispatch_id'])text(actual[key]);
  uuid(actual.owner_token);count(actual.epoch,1);
  const writer=writer_binding(original.writer),profile=original.supervisor.profile_binding(writer.config);
  if(actual.instance_id!==writer.instance_id||actual.intent_id!==context.intent_id||actual.owner_token!==context.owner_token
    ||['instance_id','storage_identity','supervisor_id','epoch','credential_generation'].some(key=>actual[key]!==profile[key]))throw new UnsupportedCapability();
  return actual;
}
export async function verify_security_ordinary(verifier:unknown,attempt:unknown,rawContext:unknown,rawOptions:unknown,inputBudget?:SecurityReadbackBudget):Promise<OrdinarySecurityReceipt>{
  registration(verifier);const context=parse_context(rawContext),options=parse_options(rawOptions),budget=security_readback_budget(inputBudget);
  const verify=ordinaryVerifiers.get(verifier as object);if(!verify)throw new InvalidRequest();return verify(attempt,context,options,budget);
}
export function ordinary_security_receipt_data(receipt:unknown,verifier:QdrantSecurityVerifier,rawOptions:unknown):OrdinarySecurityReceiptData{
  const original=registration(verifier),options=parse_options(rawOptions);
  if(typeof receipt!=='object'||receipt===null||types.isProxy(receipt))throw new InvalidRequest();
  const issued=ordinaryReceipts.get(receipt);
  if(!issued||issued.issuer!==verifier||original.closed||options.deadline>issued.options.deadline||options.signal!==issued.options.signal)throw new InvalidRequest();
  parse_options(issued.options);require_publication_finalization(original.supervisor,options);
  if(!same(ordinaryBinding(original,issued.attempt,issued.data.context),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
}
function snapshot(control:unknown,supervisor:ManagedQdrantSupervisor,proof:unknown):Readonly<{physical_binding:Readonly<Data>;activity:number}>{
  const current=control_session_binding(control,supervisor,proof),physical=metadata(current.physical_binding);
  fields(physical,['instance_id','storage_identity','supervisor_id','recovery_id','old_epoch','new_epoch','credential_generation']);
  for(const key of ['instance_id','storage_identity','supervisor_id','recovery_id','credential_generation'])text(physical[key]);
  if(count(physical.new_epoch,1)!==count(physical.old_epoch,1)+1)throw new IntegrityViolation();
  return Object.freeze({physical_binding:physical,activity:count(current.activity)});
}
function attempt_binding(supervisor:ManagedQdrantSupervisor,attempt:unknown,physical:Readonly<Data>,owner:WriterContext,dispatch:string):Readonly<Data>{
  const actual=metadata(supervisor.attempt_binding(attempt));
  const wanted={instance_id:physical.instance_id,storage_identity:physical.storage_identity,supervisor_id:physical.supervisor_id,
    credential_generation:physical.credential_generation,intent_id:owner.intent_id,owner_token:owner.owner_token,
    epoch:physical.new_epoch,dispatch_id:dispatch,recovery_id:physical.recovery_id};
  if(!same(actual,wanted))throw new IntegrityViolation();return actual;
}
export function security_receipt_data(receipt:unknown,verifier:QdrantSecurityVerifier,control:unknown,rawOptions:unknown):SecurityReceiptData{
  const original=registration(verifier),options=parse_options(rawOptions);
  if(typeof receipt!=='object'||receipt===null||types.isProxy(receipt))throw new InvalidRequest();
  const issued=receipts.get(receipt);
  if(!issued||issued.issuer!==verifier||issued.control!==control||original.closed||options.deadline>issued.deadline||options.signal!==issued.signal)throw new InvalidRequest();
  parse_options({deadline:issued.deadline,signal:issued.signal});
  const current=snapshot(control,original.supervisor,issued.proof);
  if(current.activity!==issued.data.activity||!same(current.physical_binding,issued.data.physical_binding))throw new UnsupportedCapability();
  if(!same(metadata(original.supervisor.attempt_binding(issued.attempt)),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
}
function safe(error:unknown):Error{
  try{
    if(typeof error==='object'&&error!==null&&types.isProxy(error))return new ProviderUnavailable();
    for(const Kind of [InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,DeadlineExceeded,IndexNotReady,EmbeddingProfileMismatch])if(error instanceof Kind)return new Kind();
    if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  }catch{/* Never expose an error hook. */}return new ProviderUnavailable();
}
function freeze(value:unknown):unknown{
  if(value!==null&&typeof value==='object'){for(const child of Object.values(value))freeze(child);Object.freeze(value);}return value;
}
function ordered(ids:readonly string[]):readonly string[]{return Object.freeze([...new Set(ids)].sort((a,b)=>Buffer.compare(Buffer.from(a),Buffer.from(b))));}
function witness(source:SecurityProjectionData,owner:WriterContext,physical:Readonly<Data>,attempt:Readonly<Data>,activity:number):readonly unknown[]{
  const value=['cragkit.qdrant.security-readback.v1',
    [physical.instance_id,physical.storage_identity,physical.supervisor_id,physical.recovery_id,String(physical.old_epoch),String(physical.new_epoch),physical.credential_generation],
    [attempt.intent_id,attempt.owner_token,String(attempt.epoch),attempt.dispatch_id,attempt.recovery_id],String(activity),
    [owner.scope.tenant_id,owner.collection,owner.document_id,owner.intent_id,owner.owner_token],
    [owner.scope.tenant_id,owner.scope.principal_id,ordered(owner.scope.grant_ids),owner.scope.authorization_revision],
    [source.context.intent_id,source.context.owner_token,source.intent_sha256,source.authorization_revision,String(source.mutation_epoch),
      source.active_generation_id,source.tombstoned?'true':'false',ordered(source.principal_ids),ordered(source.grant_ids),source.language,source.kind,source.tag],
    [source.inventory_sha256,source.generations.map(group=>[group.revision_id,group.generation_id,group.manifest_sha256,group.point_ids])],
    source.points.map(point=>[point.point_id,point.dense.input_sha256,point.sparse?.input_sha256??null])];
  return freeze(value) as readonly unknown[];
}
export class QdrantSecurityVerifier {
  readonly #original:Registration;
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #pending=new Set<Promise<unknown>>();
  constructor(writer:PostgresQdrantWriter,supervisor:ManagedQdrantSupervisor){
    if(new.target!==QdrantSecurityVerifier)throw new InvalidRequest();
    writer_binding(writer);if(!exact(supervisor,ManagedQdrantSupervisor.prototype))throw new InvalidRequest();
    this.#original={writer,supervisor,closed:false};verifiers.set(this,this.#original);
    purgeVerifiers.set(this,(attempt,context,projection,options,budget)=>this.#verifyPurge(attempt,context,projection,options,budget));
    ordinaryVerifiers.set(this,(attempt,context,options,budget)=>this.#verifyOrdinary(attempt,context,options,budget));
  }
  async #await<T>(work:Promise<T>,options:LeaseOptions):Promise<T>{
    this.#pending.add(work);void work.then(()=>this.#pending.delete(work),()=>this.#pending.delete(work));
    const value=await bounded(work,options);parse_options(options);return value;
  }
  async #verifyOrdinary(attempt:unknown,context:WriterContext,caller:LeaseOptions,budget:SecurityReadbackBudget):Promise<OrdinarySecurityReceipt>{
    if(this.#original.closed||this.#active)throw new ProviderUnavailable();const {writer,supervisor}=this.#original;
    require_security_guard_writer(writer);const binding=ordinaryBinding(this.#original,attempt,context);
    const controller=new AbortController(),relay=()=>controller.abort();caller.signal?.addEventListener('abort',relay,{once:true});if(caller.signal?.aborted)controller.abort();
    let finish!:()=>void;const done=new Promise<void>(resolve=>{finish=resolve;});this.#active={controller,done};
    const options={deadline:caller.deadline,signal:controller.signal};let handle:SupervisorTransport|undefined;
    const check=()=>{parse_options(options);if(this.#original.closed||!same(ordinaryBinding(this.#original,attempt,context),binding))throw new UnsupportedCapability();};
    try{
      const projection=await this.#await(security_recovery_projection(writer,context,options),options);check();
      const source=security_projection_data(projection,writer);if(source.tombstoned)throw new UnsupportedCapability();
      handle=supervisor.transport_for(attempt);
      await this.#await(verify_security_readback(handle,writer_binding(writer).config,source,options,budget),options);check();
      await this.#await(handle.close(),options);handle=undefined;check();
      await this.#await(security_recovery_projection(writer,context,options,projection),options);check();
      const value=freeze(['cragkit.qdrant.security-ordinary-readback.v1',
        [binding.instance_id,binding.storage_identity,binding.supervisor_id,String(binding.epoch),binding.credential_generation,binding.intent_id,binding.owner_token,binding.dispatch_id],
        [context.scope.tenant_id,context.collection,context.document_id,context.scope.principal_id,ordered(context.scope.grant_ids),context.scope.authorization_revision],
        [source.intent_sha256,source.inventory_sha256,source.active_generation_id,source.authorization_revision,String(source.mutation_epoch),ordered(source.principal_ids),ordered(source.grant_ids),source.language,source.kind,source.tag,false],
        source.generations.map(group=>[group.revision_id,group.generation_id,group.manifest_sha256,group.point_ids]),
        source.points.map(point=>[point.point_id,point.dense.input_sha256,point.sparse?.input_sha256??null])]) as readonly unknown[];
      const encoded=Object.freeze(Array.from(Buffer.from(JSON.stringify(value)))),sha256=hash(Buffer.from(encoded));
      const data=Object.freeze({context,projection,attempt_binding:binding,intent_sha256:source.intent_sha256,inventory_sha256:source.inventory_sha256,
        readback_sha256:sha256,witness:value,encoded_bytes:encoded,sha256});const receipt=Object.freeze({});
      ordinaryReceipts.set(receipt,{issuer:this,attempt,options:caller,data});return receipt;
    }catch(error){throw safe(error);}
    finally{
      controller.abort();caller.signal?.removeEventListener('abort',relay);let failed=false;
      if(handle){const closing=handle.close();this.#pending.add(closing);void closing.then(()=>this.#pending.delete(closing),()=>this.#pending.delete(closing));try{await bounded(closing,{deadline:now()+2});}catch{failed=true;}}
      const drain=Promise.allSettled([...this.#pending]);
      try{await bounded(drain,{deadline:now()+2});}catch{this.#original.closed=true;void drain.then(()=>{this.#active=undefined;finish();});}
      if(!this.#pending.size){this.#active=undefined;finish();}if(failed)throw new ProviderUnavailable();
    }
  }
  async #verifyPurge(attempt:unknown,context:WriterContext,purgeProjection:PurgeProjection,caller:LeaseOptions,budget:SecurityReadbackBudget):Promise<PurgeAbsenceReceipt>{
    if(this.#original.closed||this.#active)throw new ProviderUnavailable();const {writer,supervisor}=this.#original;
    require_security_guard_writer(writer);const binding=ordinaryBinding(this.#original,attempt,context);
    const controller=new AbortController(),relay=()=>controller.abort();caller.signal?.addEventListener('abort',relay,{once:true});if(caller.signal?.aborted)controller.abort();
    let finish!:()=>void;const done=new Promise<void>(resolve=>{finish=resolve;});this.#active={controller,done};
    const options={deadline:caller.deadline,signal:controller.signal};let handle:SupervisorTransport|undefined;
    const check=()=>{parse_options(options);if(this.#original.closed||!same(ordinaryBinding(this.#original,attempt,context),binding))throw new UnsupportedCapability();};
    try{
      const purge=purge_projection_data(purgeProjection,writer);
      if(!same(purge.context,context)||purge.policy_id!==PURGE_RETENTION_POLICY)throw new InvalidRequest();
      await this.#await(writer.validate_purge_projection(purgeProjection,options),options);check();
      const source=security_projection_data(purge.projection,writer);if(!source.tombstoned)throw new UnsupportedCapability();
      handle=supervisor.transport_for(attempt);
      await this.#await(verify_security_readback(handle,writer_binding(writer).config,source,options,budget),options);check();
      await this.#await(handle.close(),options);handle=undefined;check();
      await this.#await(writer.validate_purge_projection(purgeProjection,options),options);check();
      // This hash is issued only after strict point reads and scoped EOF succeeded.
      const readback=hash(JSON.stringify(['cragkit.qdrant.purge-strict-absence.v1',source.inventory_sha256,source.point_ids,binding.dispatch_id]));
      const value=freeze(['cragkit.qdrant.purge-ordinary-absence.v1',binding.instance_id,binding.storage_identity,
        binding.supervisor_id,binding.credential_generation,String(binding.epoch),context.intent_id,context.owner_token,
        purge.tombstone_context.intent_id,purge.purge_payload_sha256,purge.tombstone_payload_sha256,purge.inventory_sha256,
        purge.policy_id,readback]) as readonly unknown[];
      const encoded=Object.freeze(Array.from(Buffer.from(JSON.stringify(value)))),sha256=hash(Buffer.from(encoded));
      const data:PurgeAbsenceReceiptData=Object.freeze({context,tombstone_context:purge.tombstone_context,projection:purgeProjection,
        attempt_binding:binding,purge_payload_sha256:purge.purge_payload_sha256,inventory_sha256:purge.inventory_sha256,
        absence_sha256:sha256,witness:value,encoded_bytes:encoded,sha256});
      const receipt=Object.freeze({});purgeReceipts.set(receipt,{issuer:this,attempt,options:caller,data});return receipt;
    }catch(error){throw safe(error);}
    finally{
      controller.abort();caller.signal?.removeEventListener('abort',relay);let failed=false;
      if(handle){const closing=handle.close();this.#pending.add(closing);void closing.then(()=>this.#pending.delete(closing),()=>this.#pending.delete(closing));try{await bounded(closing,{deadline:now()+2});}catch{failed=true;}}
      const drain=Promise.allSettled([...this.#pending]);
      try{await bounded(drain,{deadline:now()+2});}catch{this.#original.closed=true;void drain.then(()=>{this.#active=undefined;finish();});}
      if(!this.#pending.size){this.#active=undefined;finish();}if(failed)throw new ProviderUnavailable();
    }
  }
  async verify(proof:unknown,control:SupervisorControlSession,rawOwner:unknown,rawSecurity:unknown,rawOptions:unknown,inputBudget?:SecurityReadbackBudget):Promise<SecurityReceipt>{
    const owner=parse_context(rawOwner),security=parse_context(rawSecurity),caller=parse_options(rawOptions),budget=security_readback_budget(inputBudget);
    if(owner.collection!==security.collection||owner.document_id!==security.document_id||!same(owner.scope,security.scope))throw new InvalidRequest();
    if(this.#original.closed||this.#active)throw new ProviderUnavailable();
    const {writer,supervisor}=this.#original,physical=snapshot(control,supervisor,proof).physical_binding;
    if(physical.instance_id!==writer_binding(writer).instance_id)throw new UnsupportedCapability();
    const profile=supervisor.profile_binding(writer_binding(writer).config);
    if(profile.instance_id!==physical.instance_id||profile.storage_identity!==physical.storage_identity
      ||profile.supervisor_id!==physical.supervisor_id||profile.epoch!==physical.new_epoch
      ||profile.credential_generation!==physical.credential_generation)throw new UnsupportedCapability();
    const controller=new AbortController(),relay=()=>controller.abort();caller.signal?.addEventListener('abort',relay,{once:true});
    if(caller.signal?.aborted)controller.abort();let finish!:()=>void;const done=new Promise<void>(resolve=>{finish=resolve;});
    this.#active={controller,done};const options={deadline:caller.deadline,signal:controller.signal};
    let handle:SupervisorTransport|undefined;
    try{
      const projection=await this.#await(writer.project_security(security,options),options),source=security_projection_data(projection,writer);
      if(!same(source.context,security))throw new IntegrityViolation();
      if(!same(snapshot(control,supervisor,proof).physical_binding,physical))throw new UnsupportedCapability();
      const dispatch='security-readback-'+randomUUID();
      const attempt=control.issue_recovery_attempt(proof,{intent_id:owner.intent_id,owner_token:owner.owner_token,
        epoch:physical.new_epoch,recovery_id:physical.recovery_id,dispatch_id:dispatch},options);
      const attemptData=attempt_binding(supervisor,attempt,physical,owner,dispatch);
      handle=control.recovery_transport_for(attempt);
      const readback=verify_security_readback(handle,writer_binding(writer).config,source,options,budget);
      // The first readback continuation captures before any wrapper/cleanup await.
      const observed=await this.#await(readback.then(()=>{
        parse_options(options);const observed=snapshot(control,supervisor,proof);
        if(!same(observed.physical_binding,physical)||!same(metadata(supervisor.attempt_binding(attempt)),attemptData))throw new UnsupportedCapability();
        return observed;
      }),options);
      const unchanged=()=>{
        parse_options(options);const current=snapshot(control,supervisor,proof);
        if(current.activity!==observed.activity||!same(current.physical_binding,physical)
          ||!same(metadata(supervisor.attempt_binding(attempt)),attemptData))throw new UnsupportedCapability();
      };
      await this.#await(handle.close(),options);handle=undefined;unchanged();
      await this.#await(writer.validate_security_projection(projection,options),options);unchanged();
      const value=witness(source,owner,physical,attemptData,observed.activity),encoded=Object.freeze(Array.from(Buffer.from(JSON.stringify(value)))),sha256=hash(Buffer.from(encoded));
      const data:SecurityReceiptData=Object.freeze({projection,owner_context:owner,security_context:security,physical_binding:physical,
        attempt_binding:attemptData,activity:observed.activity,intent_sha256:source.intent_sha256,inventory_sha256:source.inventory_sha256,
        point_ids:source.point_ids,readback_sha256:sha256,witness:value,encoded_bytes:encoded,sha256});
      const receipt=Object.freeze({});receipts.set(receipt,{issuer:this,control,proof,attempt,deadline:caller.deadline,signal:caller.signal,data});return receipt;
    }catch(error){throw safe(error);}
    finally{
      controller.abort();caller.signal?.removeEventListener('abort',relay);
      let failed=false;
      if(handle){const closing=handle.close();this.#pending.add(closing);void closing.then(()=>this.#pending.delete(closing),()=>this.#pending.delete(closing));try{await bounded(closing,{deadline:now()+2});}catch{failed=true;}}
      const drain=Promise.allSettled([...this.#pending]);
      try{await bounded(drain,{deadline:now()+2});}catch{this.#original.closed=true;void drain.then(()=>{this.#active=undefined;finish();});}
      if(!this.#pending.size){this.#active=undefined;finish();}
      if(failed)throw new ProviderUnavailable();
    }
  }
  async close():Promise<void>{this.#original.closed=true;const active=this.#active;active?.controller.abort();if(active)await bounded(active.done,{deadline:now()+2});}
}
