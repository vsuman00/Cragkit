/** Ordinary readback evidence. This module neither dispatches nor publishes. */
import { types } from 'node:util';
import { ManagedQdrantSupervisor, type SupervisorTransport } from './qdrant-supervisor.js';
import { PostgresQdrantWriter, publication_projection_data,
  type PublicationProjection, type PublicationProjectionData } from './qdrant-writer.js';
import { verify_projection_readback } from './qdrant-reconciliation.js';
import { context as parse_context, options as parse_options, metadata, fields, text, uuid, count,
  type Data, type WriterContext } from './qdrant-writer-contract.js';
import { same } from './qdrant-contract.js';
import { bounded, now } from './postgres-pool.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable,
  UnauthorizedScope, UnsupportedCapability } from './errors.js';

export type PublicationReadbackReceipt=Readonly<Record<never,never>>;
export type PublicationReceiptData=Readonly<PublicationProjectionData&{projection:PublicationProjection}>;
type Issued=Readonly<{
  issuer:QdrantPublicationVerifier;
  supervisor:ManagedQdrantSupervisor;
  attempt:unknown;
  data:PublicationReceiptData;
}>;
const receipts=new WeakMap<object,Issued>();

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
  if(!same(ordinary_binding(issued.supervisor,issued.attempt),issued.data.attempt_binding))throw new UnsupportedCapability();
  return issued.data;
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
  readonly #supervisor:ManagedQdrantSupervisor;
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #closed=false;

  constructor(writer:PostgresQdrantWriter,supervisor:ManagedQdrantSupervisor) {
    if(typeof writer!=='object'||writer===null||types.isProxy(writer)
      ||typeof supervisor!=='object'||supervisor===null||types.isProxy(supervisor)
      ||Object.getPrototypeOf(writer)!==PostgresQdrantWriter.prototype
      ||Object.getPrototypeOf(supervisor)!==ManagedQdrantSupervisor.prototype)throw new InvalidRequest();
    this.#writer=writer;
    this.#supervisor=supervisor;
  }

  async verify(attempt:unknown,input:unknown,rawOptions:unknown):Promise<PublicationReadbackReceipt> {
    const context:WriterContext=parse_context(input);
    const options=parse_options(rawOptions);
    if(this.#closed||this.#active)throw new ProviderUnavailable();
    const binding=ordinary_binding(this.#supervisor,attempt);
    if(binding.intent_id!==context.intent_id||binding.owner_token!==context.owner_token)throw new UnsupportedCapability();
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
      const projection=await this.#writer.project_publication(context,binding,lease);
      const expected=publication_projection_data(projection,this.#writer);
      transport=this.#supervisor.transport_for(attempt);
      const collection=String(expected.points[0].payload.physical_collection);
      await verify_projection_readback(transport,collection,expected,lease);
      await close_handle(transport);
      transport=undefined;
      // A source lease is never held across HTTP, and authority is fresh after it.
      await this.#writer.validate_publication_projection(projection,lease);
      if(!same(ordinary_binding(this.#supervisor,attempt),binding))throw new UnsupportedCapability();
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
