export {QdrantSecurityManager} from './qdrant-security.js';
/** Optional native stage/publish manager. Dependencies remain application-owned. */
import {randomUUID,createHash} from 'node:crypto';
import {types} from 'node:util';
import {PostgresQdrantWriter,writer_binding,type IntentView,type DispatchStatus,type DispatchView} from './qdrant-writer.js';
import {PostgresQdrantRecovery,recovery_components} from './qdrant-recovery.js';
import {ManagedQdrantSupervisor,type SupervisorTransport} from './qdrant-supervisor.js';
import {QdrantReconciliationVerifier,VerificationBudget} from './qdrant-reconciliation.js';
import {QdrantPublicationVerifier,validate_publication_receipt} from './qdrant-publication-verification.js';
import {is_publication_controller,is_worker_controller,publication_worker_reference,publication_controller_profile,publication_issue_attempt,publication_attempt_binding,publication_transport_for,publication_before_write,publication_finalization,type OrdinaryPublicationController} from './qdrant-publication-worker.js';
import {ExecutionLedger,BudgetExhausted,type Reservation} from './execution.js';
import {type TrustedScope} from './requests.js';
import {same,parse_response,type QdrantConfig} from './qdrant-contract.js';
import {bounded,now,type LeaseOptions} from './postgres-pool.js';
import {config as parse_config,scope as parse_scope,context as parse_context,options as parse_options,
  fields,metadata,native_array,text,count,hash,prepare_stage,stage_data,type WriterContext,type Data} from './qdrant-writer-contract.js';
import {InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,
  DeadlineExceeded,IndexNotReady,EmbeddingProfileMismatch} from './errors.js';

export {PostgresQdrantWriter,PostgresQdrantRecovery,ManagedQdrantSupervisor,QdrantReconciliationVerifier};
export {ManagedQdrantPublicationWorkerHost,OwnedPublicationWorker} from './qdrant-publication-worker.js';

type Authority=Readonly<{writer:PostgresQdrantWriter;recovery:PostgresQdrantRecovery|null}>;
const authorities=new WeakMap<object,Authority>();
type TransportRegistration={supervisor:OrdinaryPublicationController;closed:boolean;handles:Set<SupervisorTransport>};
const transports=new WeakMap<object,TransportRegistration>();
type Session=Readonly<{attempt:unknown;binding:Readonly<Data>;handle:SupervisorTransport;factory:TransportRegistration}>;
type Ack=Readonly<Record<never,never>>;
const acknowledgments=new WeakMap<object,Readonly<{session:Session;sha256:string}>>();
type Reference=Readonly<{collection:string;document_id:string;intent_id:string}>;
type Result=Readonly<{intent_id:string;operation:'stage'|'publish'|'repair';state:string;revision_id:string|null;
  generation_id:string|null;authority_committed:boolean;replica_complete:boolean;published:boolean;purge_complete:boolean}>;
type Authorizer=(scope:TrustedScope,collection:string,document_id:string)=>Promise<boolean>;

function exact(value:unknown,prototype:object):boolean {
  return typeof value==='object'&&value!==null&&!types.isProxy(value)&&Object.getPrototypeOf(value)===prototype;
}
function safe(error:unknown):Error {
  for(const Kind of [InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,
    DeadlineExceeded,IndexNotReady,EmbeddingProfileMismatch,BudgetExhausted])if(error instanceof Kind)return new Kind();
  if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  return new ProviderUnavailable();
}
function reference(input:unknown):Reference {
  const value=fields(input,['collection','document_id','intent_id']);
  return Object.freeze({collection:text(value.collection,true),document_id:text(value.document_id),intent_id:text(value.intent_id)});
}
function result(intent_id:string,operation:'stage'|'publish'|'repair',intent:IntentView):Result {
  return Object.freeze({intent_id,operation,state:intent.state,revision_id:intent.revision_id,generation_id:intent.generation_id,
    authority_committed:intent.authority_committed,replica_complete:intent.replica_complete,published:intent.state==='published',purge_complete:intent.purge_complete});
}
function ack_data(ack:Ack,session:Session):string {
  const issued=acknowledgments.get(ack);
  if(!issued||issued.session!==session)throw new InvalidRequest();
  return issued.sha256;
}

/** This holder is not readiness; the manager checks its full original graph. */
export class PostgresQdrantPublicationAuthority {
  constructor(writer:PostgresQdrantWriter,recovery:PostgresQdrantRecovery|null) {
    writer_binding(writer);
    if(recovery!==null&&!exact(recovery,PostgresQdrantRecovery.prototype))throw new InvalidRequest();
    authorities.set(this,Object.freeze({writer,recovery}));
    Object.freeze(this);
  }
}

/** The manager opens its own attempt handles on this borrowed native controller. */
export class ManagedQdrantPublicationTransport {
  constructor(supervisor:OrdinaryPublicationController) {
    if(!is_publication_controller(supervisor))throw new InvalidRequest();
    transports.set(this,{supervisor,closed:false,handles:new Set()});
    Object.freeze(this);
  }

  async close():Promise<void> {
    const factory=transports.get(this);
    if(!factory)throw new InvalidRequest();
    factory.closed=true;
    const deadline=now()+2;
    let failed=false;
    for(const handle of [...factory.handles]){
      try {
        await bounded(handle.close(),{deadline});
        factory.handles.delete(handle);
      } catch { failed=true; }
    }
    if(failed)throw new ProviderUnavailable();
  }
}

export class QdrantPublicationManager {
  readonly #authority:Authority;
  readonly #supervisor:OrdinaryPublicationController;
  readonly #config:QdrantConfig;
  readonly #authorizer:Authorizer;
  readonly #transport:TransportRegistration;
  readonly #verifier:QdrantPublicationVerifier;
  #ready=false;
  #closed=false;
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #pending=new Set<Promise<unknown>>();

  constructor(authority:PostgresQdrantPublicationAuthority,transport:ManagedQdrantPublicationTransport,
    config:unknown,supervisor:OrdinaryPublicationController,authorize_write:Authorizer) {
    if(!exact(authority,PostgresQdrantPublicationAuthority.prototype)||!exact(transport,ManagedQdrantPublicationTransport.prototype)
      ||!is_publication_controller(supervisor)||typeof authorize_write!=='function'||types.isProxy(authorize_write))throw new InvalidRequest();
    const original=authorities.get(authority);
    const factory=transports.get(transport);
    if(!original||!factory||factory.supervisor!==supervisor)throw new InvalidRequest();
    this.#config=parse_config(config);
    const writer=writer_binding(original.writer);
    if(!same(writer.config,this.#config))throw new UnsupportedCapability();
    if(is_worker_controller(supervisor)){if(original.recovery!==null)throw new InvalidRequest();}
    else {if(original.recovery===null)throw new InvalidRequest();recovery_components(original.recovery,original.writer,supervisor,this.#config);}
    this.#authority=original;
    this.#supervisor=supervisor;
    this.#authorizer=authorize_write;
    this.#transport=factory;
    this.#verifier=new QdrantPublicationVerifier(original.writer,supervisor);
  }

  #admit(initialize=false):void {
    if(this.#closed||this.#active)throw new ProviderUnavailable();
    if(!initialize&&!this.#ready)throw new IndexNotReady();
  }

  async #await<T>(pending:Promise<T>,options:LeaseOptions):Promise<T> {
    this.#pending.add(pending);
    void pending.then(()=>this.#pending.delete(pending),()=>this.#pending.delete(pending));
    const value=await bounded(pending,options);
    parse_options(options);
    return value;
  }

  async #operation<T>(options:LeaseOptions,body:(options:LeaseOptions)=>Promise<T>,initialize=false):Promise<T> {
    this.#admit(initialize);
    const controller=new AbortController(),relay=()=>controller.abort();
    options.signal?.addEventListener('abort',relay,{once:true});
    if(options.signal?.aborted)controller.abort();
    let finish!:()=>void;
    const done=new Promise<void>(resolve=>{finish=resolve;});
    this.#active={controller,done};
    try {
      return await body({deadline:options.deadline,signal:controller.signal});
    } catch(error) {
      throw safe(error);
    } finally {
      controller.abort();
      options.signal?.removeEventListener('abort',relay);
      const drain=Promise.allSettled([...this.#pending]);
      try {
        await bounded(drain,{deadline:now()+2});
      } catch {
        // Retain admission until actual uncooperative work finishes; do not queue.
        this.#closed=true;
        void drain.then(()=>{this.#active=undefined;finish();});
      }
      if(this.#pending.size===0){this.#active=undefined;finish();}
    }
  }

  #profile(options:LeaseOptions,open=false):Promise<Readonly<Data>> {
    return this.#readProfile(options,open);
  }

  async #readProfile(options:LeaseOptions,open:boolean):Promise<Readonly<Data>> {
    const profile=await publication_controller_profile(this.#supervisor,this.#config,options);
    if(profile.instance_id!==writer_binding(this.#authority.writer).instance_id)throw new UnsupportedCapability();
    if(open&&(!profile.alive||profile.sealed||profile.recovery!==null))throw new ProviderUnavailable();
    return profile;
  }

  async #authorize(context:WriterContext,options:LeaseOptions):Promise<void> {
    const pending=Promise.resolve().then(()=>{
      const value=this.#authorizer(context.scope,context.collection,context.document_id);
      if(!(value instanceof Promise)||types.isProxy(value))throw new InvalidRequest();
      return value;
    });
    const permitted=await this.#await(pending,options);
    if(typeof permitted!=='boolean')throw new InvalidRequest();
    if(!permitted)throw new UnauthorizedScope();
  }

  #ledger(ledger:ExecutionLedger,rawOptions:unknown):LeaseOptions {
    if(!exact(ledger,ExecutionLedger.prototype))throw new InvalidRequest();
    const options=parse_options(rawOptions);
    try { return parse_options({deadline:Math.min(options.deadline,ledger.deadline),signal:options.signal}); }
    catch(error){if(error instanceof DeadlineExceeded)throw error;if(error instanceof DOMException)throw error;throw new InvalidRequest();}
  }

  async #attempt<T>(ledger:ExecutionLedger,options:LeaseOptions,body:(options:LeaseOptions)=>Promise<T>):Promise<T> {
    return this.#operation(options,async lease=>{
      let token:Reservation|undefined=ledger.reserve({attempts:1});
      try {
        ledger.dispatch(token);
        const value=await body(lease);
        parse_options(lease);
        ledger.reconcile(token);
        token=undefined;
        return value;
      } finally {
        if(token)ledger.abandon(token);
      }
    });
  }

  async initialize(rawOptions:unknown):Promise<void> {
    const options=parse_options(rawOptions);
    await this.#operation(options,async lease=>{
      await this.#profile(lease);
      await this.#await(this.#authority.writer.initialize(lease),lease);
      if(this.#authority.recovery)await this.#await(this.#authority.recovery.initialize(lease),lease);
      const profile=await this.#profile(lease);
      if(is_worker_controller(this.#supervisor)){
        const captured=publication_worker_reference(this.#supervisor);
        const context=parse_context({...metadata(captured.reference),scope:captured.scope,owner_token:randomUUID()});
        const snapshot=await this.#await(this.#authority.writer.manager_snapshot(context,lease),lease);
        if(snapshot.backend.state!=='open'||snapshot.backend.instance_id!==profile.instance_id
          ||snapshot.backend.epoch!==profile.epoch||snapshot.backend.storage_identity!==profile.storage_identity
          ||snapshot.backend.supervisor_id!==profile.supervisor_id)throw new ProviderUnavailable();
      }
      this.#ready=true;
    },true);
  }

  async stage(change:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result> {
    this.#admit();
    if(is_worker_controller(this.#supervisor))throw new UnsupportedCapability();
    const plan=prepare_stage(change),data=stage_data(plan),scope=parse_scope(inputScope),options=this.#ledger(ledger,rawOptions);
    if(data.record.tenant_id!==scope.tenant_id)throw new UnauthorizedScope();
    const configured=parse_config(Object.fromEntries(Object.keys(this.#config).map(key=>[key,data.record[key]])));
    if(!same(configured,this.#config))throw new UnsupportedCapability();
    const context=parse_context({scope,collection:data.record.collection,document_id:data.record.document_id,
      intent_id:data.intent.intent_id,owner_token:randomUUID()});
    return this.#attempt(ledger,options,async lease=>{
      await this.#authorize(context,lease);
      const snapshot=await this.#await(this.#authority.writer.manager_snapshot(context,lease),lease);
      if(snapshot.intent){
        if(snapshot.intent.action!=='stage'||snapshot.intent.payload_sha256!==plan.payload_sha256
          ||snapshot.intent.manifest_sha256!==plan.manifest_sha256)throw new IntegrityViolation();
        if(['published','conflict','denied'].includes(snapshot.intent.state))return result(context.intent_id,'stage',snapshot.intent);
      }
      const profile=await this.#profile(lease,true);
      if(snapshot.backend.state!=='open'||snapshot.backend.epoch!==profile.epoch
        ||snapshot.backend.storage_identity!==profile.storage_identity||snapshot.backend.supervisor_id!==profile.supervisor_id)throw new ProviderUnavailable();
      const staged=await this.#await(this.#authority.writer.stage(plan,scope,{...lease,owner_token:context.owner_token}),lease);
      return result(context.intent_id,'stage',staged);
    });
  }

  #session(context:WriterContext,epoch:number,dispatch_id:string,options:LeaseOptions):Promise<Session> {
    return this.#openSession(context,epoch,dispatch_id,options);
  }

  async #openSession(context:WriterContext,epoch:number,dispatch_id:string,options:LeaseOptions):Promise<Session> {
    if(this.#transport.closed)throw new ProviderUnavailable();
    const attempt=await publication_issue_attempt(this.#supervisor,{intent_id:context.intent_id,owner_token:context.owner_token,epoch,dispatch_id},options);
    const binding=await publication_attempt_binding(this.#supervisor,attempt,options);
    if(Object.hasOwn(binding,'recovery_id')||binding.intent_id!==context.intent_id||binding.owner_token!==context.owner_token
      ||binding.epoch!==epoch||binding.dispatch_id!==dispatch_id)throw new UnsupportedCapability();
    const handle=publication_transport_for(this.#supervisor,attempt);
    this.#transport.handles.add(handle);
    return Object.freeze({attempt,binding,handle,factory:this.#transport});
  }

  async #closeHandle(session:Session):Promise<void> {
    try {
      await this.#await(session.handle.close(),{deadline:now()+2});
      session.factory.handles.delete(session.handle);
    } catch(error) {
      if(error instanceof DOMException&&error.name==='AbortError')throw error;
      throw new ProviderUnavailable();
    }
  }

  async #send(session:Session,reservation:DispatchView,options:LeaseOptions):Promise<Ack> {
    if(reservation.dispatch_id!==session.binding.dispatch_id)throw new IntegrityViolation();
    const raw=await this.#await(session.handle.request('PUT','/collections/'+this.#config.physical_collection+'/points?wait=true&ordering=strong',
      {...options,body:reservation.request_bytes,max_response_bytes:1048576}),options);
    let bytes:Buffer;
    try { bytes=Buffer.from(native_array(raw,1,1048576).map(value=>count(value,0,255))); }
    catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
    const parsed=parse_response(bytes);
    if(typeof parsed!=='object'||parsed===null||Array.isArray(parsed))throw new IntegrityViolation();
    const envelope=parsed as Data,record=envelope.result;
    if(envelope.status!=='ok'||typeof record!=='object'||record===null||Array.isArray(record))throw new IntegrityViolation();
    const completed=record as Data;
    if(completed.status!=='completed'||Object.keys(completed).some(key=>!['status','operation_id'].includes(key)))throw new IntegrityViolation();
    if(Object.hasOwn(completed,'operation_id')){
      try { count(completed.operation_id); } catch { throw new IntegrityViolation(); }
    }
    const ack=Object.freeze({});
    acknowledgments.set(ack,Object.freeze({session,sha256:hash(bytes)}));
    return ack;
  }

  #matches(status:DispatchStatus|null,session:Session,sequence:number,point_ids:readonly string[]):status is DispatchStatus {
    return status!==null&&status.dispatch_id===session.binding.dispatch_id&&status.owner_token===session.binding.owner_token
      &&status.backend_epoch===session.binding.epoch&&status.credential_generation===session.binding.credential_generation
      &&status.sequence===sequence&&status.operation==='complete_point_upsert'&&same(status.point_ids,point_ids);
  }

  async #reserve(context:WriterContext,session:Session,sequence:number,point_ids:readonly string[],options:LeaseOptions):Promise<DispatchView> {
    const request={dispatch_id:session.binding.dispatch_id,sequence,credential_generation:session.binding.credential_generation,
      operation:'complete_point_upsert',point_ids};
    try { return await this.#await(this.#authority.writer.reserve_dispatch(context,request,options),options); }
    catch(error){
      if(!(error instanceof ProviderUnavailable))throw error;
      const status=await this.#await(this.#authority.writer.dispatch_status(context,String(session.binding.dispatch_id),options),options);
      if(!this.#matches(status,session,sequence,point_ids)||status.state!=='reserved')throw new ProviderUnavailable();
      return this.#await(this.#authority.writer.reserve_dispatch(context,request,options),options);
    }
  }

  async #mark(context:WriterContext,session:Session,sequence:number,point_ids:readonly string[],options:LeaseOptions):Promise<void> {
    const id=String(session.binding.dispatch_id);
    try { await this.#await(this.#authority.writer.mark_dispatched(context,id,options),options); }
    catch(error){
      if(!(error instanceof ProviderUnavailable))throw error;
      const status=await this.#await(this.#authority.writer.dispatch_status(context,id,options),options);
      if(!this.#matches(status,session,sequence,point_ids))throw new IntegrityViolation();
      if(status.state==='dispatched')return;
      if(status.state!=='reserved')throw new ProviderUnavailable();
      await this.#authorize(context,options);
      await this.#await(this.#authority.writer.mark_dispatched(context,id,options),options);
    }
  }

  async #settle(context:WriterContext,session:Session,sequence:number,point_ids:readonly string[],ack:Ack,options:LeaseOptions):Promise<void> {
    const completion=ack_data(ack,session),id=String(session.binding.dispatch_id);
    try { await this.#await(this.#authority.writer.settle_dispatch(context,id,completion,options),options); }
    catch(error){
      if(!(error instanceof ProviderUnavailable))throw error;
      const status=await this.#await(this.#authority.writer.dispatch_status(context,id,options),options);
      if(!this.#matches(status,session,sequence,point_ids))throw new IntegrityViolation();
      if(status.state==='settled'){
        if(status.completion_sha256!==completion)throw new IntegrityViolation();
        return;
      }
      if(status.state!=='dispatched')throw new ProviderUnavailable();
      await this.#await(this.#authority.writer.settle_dispatch(context,id,completion,options),options);
    }
  }

  async #unknown(context:WriterContext,id:string,options:LeaseOptions):Promise<void> {
    try {
      parse_options(options);
      await this.#await(this.#authority.writer.mark_unknown(context,id,options),options);
    } catch { /* The immutable reserved/dispatched journal still blocks successors. */ }
  }

  async #writeBatch(context:WriterContext,epoch:number,sequence:number,ids:readonly string[],options:LeaseOptions):Promise<unknown> {
    await this.#authorize(context,options);
    const id='publication-'+randomUUID();
    const session=await this.#session(context,epoch,id,options);
    let closed=false;
    try {
      const reservation=await this.#reserve(context,session,sequence,ids,options);
      await this.#mark(context,session,sequence,ids,options);
      await publication_before_write(this.#supervisor,session.attempt,{dispatch_id:String(session.binding.dispatch_id),sequence,request_bytes:reservation.request_bytes},options);
      let ack:Ack;
      try {
        ack=await this.#send(session,reservation,options);
        await this.#closeHandle(session);
        closed=true;
      } catch(error) {
        await this.#unknown(context,id,options);
        throw error;
      }
      await this.#settle(context,session,sequence,ids,ack,options);
      return session.attempt;
    } finally {
      if(!closed)await this.#closeHandle(session);
    }
  }

  async publish(input:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result> {
    this.#admit();
    const ref=reference(input),scope=parse_scope(inputScope),options=this.#ledger(ledger,rawOptions);
    const lookup=parse_context({...ref,scope,owner_token:randomUUID()});
    return this.#attempt(ledger,options,lease=>this.#publishBody(ref,lookup,lease,'publish'));
  }

  async #publishBody(ref:Reference,lookup:WriterContext,lease:LeaseOptions,operation:'publish'|'repair',budget=new VerificationBudget()):Promise<Result> {
      await this.#authorize(lookup,lease);
      const writer=this.#authority.writer;
      const initial=await this.#await(writer.manager_snapshot(lookup,lease),lease);
      if(!initial.intent||initial.intent.action!=='stage')throw new InvalidRequest();
      if(['published','conflict','denied'].includes(initial.intent.state)){
        const historical=await this.#await(writer.admit_publication(lookup,lease),lease);
        return result(ref.intent_id,operation,historical.intent);
      }
      const prepared=initial.intent.state==='prepared'
        ?await this.#await(writer.publication_preparation(lookup,lease),lease):null;
      if(initial.intent.state==='prepared'&&!prepared)throw new IntegrityViolation();
      const context=parse_context({...lookup,owner_token:prepared?.preparation.owner_token??lookup.owner_token});
      const admission=await this.#await(writer.admit_publication(context,lease),lease);
      if(!admission.owner)return result(ref.intent_id,operation,admission.intent);
      const snapshot=await this.#await(writer.manager_snapshot(context,lease),lease);
      const profile=await this.#profile(lease,true);
      if(snapshot.pending||snapshot.backend.state!=='open'||snapshot.backend.epoch!==profile.epoch
        ||snapshot.backend.storage_identity!==profile.storage_identity||snapshot.backend.supervisor_id!==profile.supervisor_id
        ||snapshot.owner?.owner_token!==context.owner_token||snapshot.owner.intent_id!==context.intent_id
        ||snapshot.owner.backend_epoch!==snapshot.backend.epoch)throw new ProviderUnavailable();
      let attempt:unknown;
      if(prepared){
        if(prepared.dispatch.credential_generation!==profile.credential_generation
          ||prepared.dispatch.backend_epoch!==profile.epoch)throw new ProviderUnavailable();
        const session=await this.#session(context,prepared.dispatch.backend_epoch,prepared.dispatch.dispatch_id,lease);
        attempt=session.attempt;
        await this.#closeHandle(session);
      } else {
        const plan=await this.#await(writer.load_stage(context,lease),lease);
        const members=native_array(stage_data(plan).record.members,1,64).map(member=>text(metadata(member).point_id)).sort();
        const batches=Math.ceil(members.length/8);
        if(snapshot.max_sequence+batches>256)throw new BudgetExhausted();
        for(let start=0;start<members.length;start+=8){
          if(budget.remaining_bytes<=0)throw new ProviderUnavailable();
          attempt=await this.#writeBatch(context,snapshot.backend.epoch,snapshot.max_sequence+1+start/8,Object.freeze(members.slice(start,start+8)),lease);
        }
      }
      const receipt=await this.#await(this.#verifier.verify(attempt,context,lease,budget),lease);
      const verified=await validate_publication_receipt(receipt,this.#verifier,lease);
      if(prepared&&verified.readback_sha256!==prepared.preparation.readback_sha256)throw new IntegrityViolation();
      let finalization!:Promise<Result>;
      finalization=publication_finalization(this.#supervisor,attempt,async()=>{
        try {
          const current=await validate_publication_receipt(receipt,this.#verifier,lease);
          await this.#authorize(context,lease);
          await this.#await(writer.validate_publication_projection(current.projection,lease),lease);
          if(!prepared){
            try {
              const outcome=await this.#await(writer.prepare(context,current.readback_sha256,lease),lease);
              if(['denied','conflict','published'].includes(outcome.state))return result(ref.intent_id,operation,outcome);
            }
            catch(error){
              if(!(error instanceof ProviderUnavailable))throw error;
              const durable=await this.#await(writer.publication_preparation(context,lease),lease);
              if(!durable||durable.preparation.readback_sha256!==current.readback_sha256
                ||durable.preparation.owner_token!==context.owner_token||durable.preparation.backend_epoch!==current.attempt_binding.epoch)throw new ProviderUnavailable();
            }
          }
          await this.#authorize(context,lease);
          let published:IntentView;
          try { published=await this.#await(writer.publish(context,lease),lease); }
          catch(error){
            if(!(error instanceof ProviderUnavailable))throw error;
            const outcome=await this.#await(writer.manager_snapshot(context,lease),lease);
            if(!outcome.intent||outcome.intent.state!=='published')throw error;
            published=outcome.intent;
          }
          return result(ref.intent_id,operation,published);
        } finally {
          // The scope cannot expire while a timed-out callback still executes.
          // Exclude this enclosing promise from its own actual-unwind drain.
          await Promise.allSettled([...this.#pending].filter(pending=>pending!==finalization));
        }
      },lease);
      return this.#await(finalization,lease);
  }

  async repair(input:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result> {
    this.#admit();
    if(is_worker_controller(this.#supervisor)||this.#authority.recovery===null)throw new UnsupportedCapability();
    const ref=reference(input),scope=parse_scope(inputScope),options=this.#ledger(ledger,rawOptions);
    const lookup=parse_context({...ref,scope,owner_token:randomUUID()});
    return this.#attempt(ledger,options,async lease=>{
      const budget=new VerificationBudget();
      const writer=this.#authority.writer,recovery=this.#authority.recovery!;
      // Authorize before scoped source inspection; preflight gates the exact profile.
      await this.#authorize(lookup,lease);
      let snapshot=await this.#await(writer.preflight_repair(lookup,lease),lease);
      if(['published','denied','conflict'].includes(snapshot.intent.state))return result(ref.intent_id,'repair',snapshot.intent);
      const owner=snapshot.owner;
      if(owner&&(owner.instance_id!==snapshot.backend.instance_id||owner.intent_id!==ref.intent_id))throw new ProviderUnavailable();
      if((snapshot.intent.state==='prepared'||snapshot.pending||snapshot.backend.state==='recovery_blocked')
        &&(!owner||owner.instance_id!==snapshot.backend.instance_id||owner.intent_id!==ref.intent_id))throw new ProviderUnavailable();
      const context=parse_context({...lookup,owner_token:owner?.intent_id===ref.intent_id?owner.owner_token:lookup.owner_token});
      const needsRecovery=snapshot.pending||snapshot.backend.state==='recovery_blocked'
        ||snapshot.intent.state==='prepared'&&owner!.backend_epoch!==snapshot.backend.epoch;
      if(needsRecovery){
        await this.#authorize(context,lease);
        const id=snapshot.backend.recovery_id??'g1-'+createHash('sha256').update(JSON.stringify([
          'cragkit.qdrant.repair-recovery.v1',snapshot.backend.instance_id,String(snapshot.backend.epoch)])).digest('hex');
        const uncertain=snapshot.pending;
        const proof=await this.#await(recovery.recover(id,lease),lease);
        await this.#await(recovery.advance_owner(proof,context,lease),lease);
        if(uncertain){
          const verifier=recovery_components(recovery,writer,this.#supervisor,this.#config);
          let receipt;
          try{receipt=await this.#await(verifier.verify(proof,context,lease,budget),lease);}
          catch(error){
            if(!(error instanceof IntegrityViolation))throw error;
            const authorize=async(selected:TrustedScope,collection:string,document_id:string):Promise<boolean>=>{
              if(!same(selected,context.scope)||collection!==context.collection||document_id!==context.document_id)throw new InvalidRequest();
              await this.#authorize(context,lease);return true;
            };
            await this.#await(recovery.dispatch_stage_recovery(proof,context,authorize,lease,budget),lease);
            receipt=await this.#await(verifier.verify(proof,context,lease,budget),lease);
          }
          await this.#await(recovery.settle_retired(proof,receipt,lease),lease);
        }
        await this.#await(recovery.reopen(proof,lease),lease);
        snapshot=await this.#await(writer.preflight_repair(context,lease),lease);
        if(['published','denied','conflict'].includes(snapshot.intent.state))return result(ref.intent_id,'repair',snapshot.intent);
      }
      if(snapshot.intent.state!=='prepared')return this.#publishBody(ref,context,lease,'repair',budget);
      const durable=await this.#await(writer.attestation_snapshot(context,lease),lease);
      if(durable.preparation.backend_epoch===snapshot.backend.epoch)return this.#publishBody(ref,context,lease,'repair',budget);
      const profile=await this.#profile(lease,true),epoch=count(profile.epoch,1);
      if(durable.preparation.backend_epoch>snapshot.backend.epoch)throw new IntegrityViolation();
      if(epoch!==snapshot.backend.epoch||durable.preparation.backend_epoch>=epoch)throw new ProviderUnavailable();
      if(durable.attestation&&durable.attestation.credential_generation!==profile.credential_generation)throw new ProviderUnavailable();
      const id=durable.attestation?.verification_id??'g1-'+createHash('sha256').update(JSON.stringify([
        'cragkit.qdrant.repair-verification.v1',snapshot.backend.instance_id,ref.intent_id,context.owner_token,
        String(profile.epoch),profile.credential_generation,snapshot.intent.manifest_sha256])).digest('hex');
      const session=await this.#session(context,epoch,id,lease);
      await this.#closeHandle(session);
      const receipt=await this.#await(this.#verifier.verify(session.attempt,context,lease,budget),lease);
      let finalization!:Promise<Result>;
      finalization=publication_finalization(this.#supervisor,session.attempt,async()=>{
        try{
          const current=await validate_publication_receipt(receipt,this.#verifier,lease);
          await this.#authorize(context,lease);
          await this.#await(writer.validate_publication_projection(current.projection,lease),lease);
          const attested=await this.#await(writer.attest_prepared(receipt,this.#verifier,lease),lease);
          if(['published','denied','conflict'].includes(attested.intent.state))return result(ref.intent_id,'repair',attested.intent);
          await this.#authorize(context,lease);
          let published:IntentView;
          try{published=await this.#await(writer.publish(context,lease),lease);}
          catch(error){
            if(!(error instanceof ProviderUnavailable))throw error;
            const confirmed=await this.#await(writer.manager_snapshot(context,lease),lease);
            if(confirmed.intent?.state!=='published')throw error;
            published=confirmed.intent;
          }
          return result(ref.intent_id,'repair',published);
        }finally{await Promise.allSettled([...this.#pending].filter(pending=>pending!==finalization));}
      },lease);
      return this.#await(finalization,lease);
    });
  }

  async close():Promise<void> {
    this.#closed=true;
    const active=this.#active;
    active?.controller.abort();
    if(active)await bounded(active.done,{deadline:now()+2});
    await this.#verifier.close();
  }
}
