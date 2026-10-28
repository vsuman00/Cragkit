/** Ordinary readback evidence. This module neither dispatches nor publishes. */
import { types } from 'node:util';
import { ManagedQdrantSupervisor, type SupervisorTransport } from './qdrant-supervisor.js';
import {is_publication_controller,is_worker_controller,publication_attempt_binding,publication_transport_for,require_publication_finalization,type OrdinaryPublicationController} from './qdrant-publication-worker.js';
import { PostgresQdrantWriter, publication_projection_data,
  type PublicationProjection, type PublicationProjectionData } from './qdrant-writer.js';
import { verify_projection_readback, verification_budget, type VerificationBudget } from './qdrant-reconciliation.js';
import { context as parse_context, options as parse_options, metadata, fields, text, uuid, count,
  type Data, type WriterContext } from './qdrant-writer-contract.js';
import { same } from './qdrant-contract.js';
import { bounded, now, type LeaseOptions } from './postgres-pool.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable,
  UnauthorizedScope, UnsupportedCapability } from './errors.js';

export type PublicationReadbackReceipt=Readonly<Record<never,never>>;
export type PublicationReceiptData=Readonly<PublicationProjectionData&{projection:PublicationProjection}>;
type Issued=Readonly<{
  issuer:QdrantPublicationVerifier;
  supervisor:OrdinaryPublicationController;
  attempt:unknown;
  data:PublicationReceiptData;
}>;
const receipts=new WeakMap<object,Issued>();
const verifierOrigins=new WeakMap<object,Readonly<{writer:PostgresQdrantWriter;controller:OrdinaryPublicationController}>>();

/** Original native metadata only; no pool, receipt or controller permission. */
export function publication_verifier_controller(verifier:QdrantPublicationVerifier,expectedWriter:PostgresQdrantWriter):OrdinaryPublicationController{
  if(typeof verifier!=='object'||verifier===null||types.isProxy(verifier)
      ||Object.getPrototypeOf(verifier)!==QdrantPublicationVerifier.prototype)throw new InvalidRequest();
  const original=verifierOrigins.get(verifier);
  if(!original||original.writer!==expectedWriter||!is_publication_controller(original.controller))throw new InvalidRequest();
  return original.controller;
}

/** Recovery capabilities cannot be interpreted as ordinary publication attempts. */
function ordinary_binding(supervisor:ManagedQdrantSupervisor,attempt:unknown):Readonly<Data> {
  const value=metadata(supervisor.attempt_binding(attempt));
  if(Object.hasOwn(value,'recovery_id'))throw new UnsupportedCapability();
  fields(value,['instance_id','storage_identity','supervisor_id','epoch','credential_generation','intent_id','owner_token','dispatch_id']);
  for(const key of ['instance_id','storage_identity','supervisor_id','credential_generation','intent_id','dispatch_id'])text(value[key]);
  uuid(value.owner_token);
  count(value.epoch,1);
  return value;
}

/** A digest or serialized receipt is never sufficient to recover this provenance. */
export function publication_receipt_data(input:unknown,verifier:QdrantPublicationVerifier):PublicationReceiptData {
  if(typeof input!=='object'||input===null)throw new InvalidRequest();
  const issued=receipts.get(input);
  if(!issued||issued.issuer!==verifier)throw new InvalidRequest();
  if(is_worker_controller(issued.supervisor))throw new UnsupportedCapability();
  if(!same(ordinary_binding(issued.supervisor,issued.attempt),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
}

export async function validate_publication_receipt(input:unknown,verifier:QdrantPublicationVerifier,options:{deadline:number;signal?:AbortSignal}):Promise<PublicationReceiptData> {
  parse_options(options);
  if(typeof input!=='object'||input===null)throw new InvalidRequest();
  const issued=receipts.get(input);
  if(!issued||issued.issuer!==verifier)throw new InvalidRequest();
  if(!same(await publication_attempt_binding(issued.supervisor,issued.attempt,options),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
}

/** Private append admission requires both live native ownership and receipt provenance. */
export async function attestation_receipt_data(input:unknown,verifier:QdrantPublicationVerifier,expectedWriter:PostgresQdrantWriter,rawOptions:LeaseOptions):Promise<PublicationReceiptData>{
  const parsed=parse_options(rawOptions);
  const options:LeaseOptions={deadline:parsed.deadline,signal:parsed.signal};
  const controller=publication_verifier_controller(verifier,expectedWriter);
  require_publication_finalization(controller,options);
  const data=await validate_publication_receipt(input,verifier,options);
  if(publication_verifier_controller(verifier,expectedWriter)!==controller)throw new InvalidRequest();
  publication_projection_data(data.projection,expectedWriter);
  require_publication_finalization(controller,options);
  return data;
}

function safe(error:unknown):Error {
  if(error instanceof IntegrityViolation)return new IntegrityViolation();
  if(error instanceof InvalidRequest)return new InvalidRequest();
  if(error instanceof UnsupportedCapability)return new UnsupportedCapability();
  if(error instanceof UnauthorizedScope)return new UnauthorizedScope();
  if(error instanceof DeadlineExceeded)return new DeadlineExceeded();
  if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  return new ProviderUnavailable();
}

/** Cleanup has its own small allowance; failure never masquerades as readback. */
async function close_handle(transport:SupervisorTransport):Promise<void> {
  try {
    await bounded(transport.close(),{deadline:now()+2});
  } catch(error) {
    if(error instanceof DOMException&&error.name==='AbortError')throw new DOMException('Operation aborted.','AbortError');
    throw new ProviderUnavailable();
  }
}

export class QdrantPublicationVerifier {
  readonly #writer:PostgresQdrantWriter;
  readonly #supervisor:OrdinaryPublicationController;
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #closed=false;

  constructor(writer:PostgresQdrantWriter,supervisor:OrdinaryPublicationController) {
    if(typeof writer!=='object'||writer===null||types.isProxy(writer)
      ||typeof supervisor!=='object'||supervisor===null||types.isProxy(supervisor)
      ||Object.getPrototypeOf(writer)!==PostgresQdrantWriter.prototype
      ||!is_publication_controller(supervisor))throw new InvalidRequest();
    this.#writer=writer;
    this.#supervisor=supervisor;
    verifierOrigins.set(this,Object.freeze({writer,controller:supervisor}));
  }

  async verify(attempt:unknown,input:unknown,rawOptions:unknown,inputBudget?:VerificationBudget):Promise<PublicationReadbackReceipt> {
    const budget=verification_budget(inputBudget);
    const context:WriterContext=parse_context(input);
    const options=parse_options(rawOptions);
    if(this.#closed||this.#active)throw new ProviderUnavailable();
    const controller=new AbortController();
    const relay=()=>controller.abort();
    options.signal?.addEventListener('abort',relay,{once:true});
    if(options.signal?.aborted)controller.abort();
    let finish!:()=>void;
    const done=new Promise<void>(resolve=>{finish=resolve;});
    this.#active={controller,done};
    const lease={deadline:options.deadline,signal:controller.signal};
    let transport:SupervisorTransport|undefined;
    try {
      const binding=await publication_attempt_binding(this.#supervisor,attempt,lease);
      if(binding.intent_id!==context.intent_id||binding.owner_token!==context.owner_token)throw new UnsupportedCapability();
      const projection=await this.#writer.project_publication(context,binding,lease);
      const expected=publication_projection_data(projection,this.#writer);
      transport=publication_transport_for(this.#supervisor,attempt);
      const collection=String(expected.points[0].payload.physical_collection);
      await verify_projection_readback(transport,collection,expected,lease,budget);
      await close_handle(transport);
      transport=undefined;
      // A source lease is never held across HTTP, and authority is fresh after it.
      await this.#writer.validate_publication_projection(projection,lease);
      if(!same(await publication_attempt_binding(this.#supervisor,attempt,lease),binding))throw new UnsupportedCapability();
      parse_options(lease);
      const receipt=Object.freeze({});
      const data:PublicationReceiptData=Object.freeze({...expected,projection});
      receipts.set(receipt,Object.freeze({issuer:this,supervisor:this.#supervisor,attempt,data}));
      return receipt;
    } catch(error) {
      throw safe(error);
    } finally {
      controller.abort();
      options.signal?.removeEventListener('abort',relay);
      let cleanupError:unknown;
      if(transport){
        try {
          await close_handle(transport);
        } catch(error) {
          cleanupError=error;
        }
      }
      this.#active=undefined;
      finish();
      if(cleanupError)throw cleanupError;
    }
  }

  async close():Promise<void> {
    this.#closed=true;
    const active=this.#active;
    active?.controller.abort();
    if(active)await bounded(active.done,{deadline:now()+2});
  }
}
