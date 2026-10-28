/** Pure security readback diagnostics. No receipt or mutation authority is issued. */
import {types} from 'node:util';
import {config as parse_config,context as parse_context,options as parse_options,fields,native_array,metadata,uuid,count,type Data} from './qdrant-writer-contract.js';
import {QdrantPayloadSchema,parse_response,same,point_id} from './qdrant-contract.js';
import {verify_dense_readback,verify_sparse_readback} from './qdrant-vectors.js';
import {bounded} from './postgres-pool.js';
import {InvalidRequest,IntegrityViolation,ProviderUnavailable,DeadlineExceeded,UnsupportedCapability,UnauthorizedScope} from './errors.js';
import {type ProjectionPoint} from './qdrant-writer.js';
import {type SupervisorTransport} from './qdrant-supervisor.js';

const BYTES=8388608,CALLS=513,RESPONSE=1048576;
const budgets=new WeakMap<object,{bytes:number;calls:number}>();
export class SecurityReadbackBudget {
  constructor(...args:unknown[]){
    if(args.length||new.target!==SecurityReadbackBudget)throw new InvalidRequest();
    budgets.set(this,{bytes:BYTES,calls:CALLS});Object.freeze(this);
  }
  get remaining_bytes():number{return budget_state(this).bytes;}
  get remaining_calls():number{return budget_state(this).calls;}
}
function budget_state(value:unknown):{bytes:number;calls:number}{
  if(typeof value!=='object'||value===null||types.isProxy(value)||Object.getPrototypeOf(value)!==SecurityReadbackBudget.prototype
    ||!budgets.has(value))throw new InvalidRequest();
  return budgets.get(value)!;
}
export function security_readback_budget(value?:unknown):SecurityReadbackBudget{
  if(value===undefined)return new SecurityReadbackBudget();budget_state(value);return value as SecurityReadbackBudget;
}
const MUTABLE=['authorization_revision','principal_ids','grant_ids','language','kind','tag'];
const SCOPE=['backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id'];
function safe(error:unknown):Error{
  try{
    if(typeof error==='object'&&error!==null&&types.isProxy(error))return new ProviderUnavailable();
    for(const Kind of [InvalidRequest,IntegrityViolation,DeadlineExceeded,UnsupportedCapability,UnauthorizedScope])if(error instanceof Kind)return new Kind();
    if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  }catch{/* Untrusted diagnostic hooks never escape. */}
  return new ProviderUnavailable();
}
function payload(value:unknown):Readonly<Data>{
  try{
    const parsed=QdrantPayloadSchema.parse(metadata(value));
    return Object.freeze({...parsed});
  }catch{throw new IntegrityViolation();}
}
function immutable(value:Readonly<Data>):Data{return Object.fromEntries(Object.entries(value).filter(([key])=>!MUTABLE.includes(key)));}
function native(value:unknown):unknown{
  if(Array.isArray(value))return value.map(native);
  if(value!==null&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,child])=>[key,native(child)]));
  return value;
}
function envelope(raw:Buffer):Data{
  const parsed=native(parse_response(raw));
  if(parsed===null||typeof parsed!=='object'||Array.isArray(parsed))throw new IntegrityViolation();
  const record=parsed as Data;if(record.status!=='ok'||!Object.hasOwn(record,'result'))throw new IntegrityViolation();return record;
}
function rows(value:unknown,max:number):Data[]{
  try{return native_array(value,0,max).map(row=>fields(row,['id','payload','vector'],['shard_key']));}
  catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
}
export type SecurityInspection=Readonly<{present_ids:readonly string[];missing_ids:readonly string[];stale_ids:readonly string[]}>;
export async function inspect_security_readback(transport:SupervisorTransport,rawConfig:unknown,rawExpected:unknown,
  rawOptions:unknown,inputBudget?:SecurityReadbackBudget):Promise<SecurityInspection>{
  let admitted=false;
  try{
    const config=parse_config(rawConfig),parsedOptions=parse_options(rawOptions),budget=security_readback_budget(inputBudget);
    const options={deadline:parsedOptions.deadline,signal:parsedOptions.signal};
    // Only the structural subset is read: provenance belongs to the caller.
    if(typeof rawExpected!=='object'||rawExpected===null||types.isProxy(rawExpected)||Object.getPrototypeOf(rawExpected)!==Object.prototype)throw new InvalidRequest();
    const get=(key:string):unknown=>{const descriptor=Object.getOwnPropertyDescriptor(rawExpected,key);if(!descriptor||!('value'in descriptor))throw new InvalidRequest();return descriptor.value;};
    const context=parse_context(get('context')),tombstoned=get('tombstoned');if(typeof tombstoned!=='boolean')throw new InvalidRequest();
    const ids=native_array(get('point_ids'),0,2048).map(uuid),points=native_array(get('points'),0,2048).map(point=>fields(point,['point_id','payload','dense','sparse']));
    if(ids.length!==points.length||new Set(ids).size!==ids.length||!same(ids,[...ids].sort()))throw new InvalidRequest();
    const scope={...config,tenant_id:context.scope.tenant_id,collection:context.collection,document_id:context.document_id};
    const expected=new Map<string,ProjectionPoint>(),groups=new Map<string,number>();
    for(let index=0;index<points.length;index++){
      const point=points[index],id=uuid(point.point_id),p=payload(point.payload);
      if(id!==ids[index]||p.authorization_revision!==context.scope.authorization_revision||SCOPE.some(key=>p[key]!==scope[key as keyof typeof scope])||!same(p.dense_profile,config.dense_profile)
        ||!same(p.sparse_profile,config.sparse_profile)||p.dense_profile_id!==config.dense_profile.profile_id
        ||p.sparse_profile_id!==(config.sparse_profile?.profile_id??''))throw new InvalidRequest();
      if(point_id(['cragkit.qdrant.point.v1',...SCOPE.map(key=>String(p[key])),String(p.revision_id),String(p.generation_id),
        String(p.chunk_id),config.dense_profile.profile_id,config.sparse_profile?.profile_id??''])!==id)throw new InvalidRequest();
      const group=JSON.stringify([p.revision_id,p.generation_id]);groups.set(group,(groups.get(group)??0)+1);
      // Vector validators require native issued immutable vector encodings.
      const dense=fields(point.dense,['kind','name','profile','values','sealed_bytes','input_sha256']);
      if(!same(dense.profile,config.dense_profile))throw new InvalidRequest();
      const values=native_array(dense.values,1536,1536).map(value=>{if(typeof value!=='number'||!Number.isFinite(value))throw new InvalidRequest();return value;});
      const norm=Math.sqrt(values.reduce((sum,value)=>sum+value*value,0));
      verify_dense_readback(point.dense,values.map(value=>value/norm));
      if(config.sparse_profile===null){if(point.sparse!==null)throw new InvalidRequest();}
      else{
        const sparse=fields(point.sparse,['kind','name','profile','indices','values','sealed_bytes','input_sha256']);
        if(!same(sparse.profile,config.sparse_profile))throw new InvalidRequest();
        verify_sparse_readback(point.sparse,sparse.indices,sparse.values);
      }
      expected.set(id,Object.freeze({point_id:id,payload:p,dense:point.dense,sparse:point.sparse}) as ProjectionPoint);
    }
    if(groups.size>64||[...groups.values()].some(size=>size>64))throw new InvalidRequest();
    admitted=true;
    const request=async(path:string,body:unknown):Promise<Data>=>{
      parse_options(options);const state=budget_state(budget);
      if(state.calls===0||state.bytes===0)throw new ProviderUnavailable();
      state.calls--;const maximum=Math.min(RESPONSE,state.bytes);
      const pending=transport.request('POST',path,{deadline:options.deadline,signal:options.signal,
        body:Object.freeze(Array.from(Buffer.from(JSON.stringify(body)))),max_response_bytes:maximum}).then(raw=>{
        // Account for returned bytes even if the caller already timed out.
        // bounded observes late rejection; no late result resumes verification.
        if(!Array.isArray(raw)||types.isProxy(raw))throw new IntegrityViolation();
        const length=Object.getOwnPropertyDescriptor(raw,'length')!.value as number;
        const remaining=state.bytes;state.bytes=Math.max(0,remaining-length);
        if(length>remaining)throw new ProviderUnavailable();
        if(length>maximum)throw new IntegrityViolation();
        return raw;
      });
      const raw=await bounded(pending,options);
      let bytes:unknown[];
      try{bytes=native_array(raw,0,RESPONSE);}catch{throw new IntegrityViolation();}
      const buffer=Buffer.from(bytes.map(value=>{try{return count(value,0,255);}catch{throw new IntegrityViolation();}}));
      parse_options(options);return envelope(buffer);
    };
    const validate=(row:Data):Readonly<Data>=>{
      try{
        const id=uuid(row.id),point=expected.get(id);
        if(!point||(row.shard_key!==undefined&&row.shard_key!==null))throw new IntegrityViolation();
        const observed=payload(row.payload);
        if(!same(immutable(observed),immutable(point.payload)))throw new IntegrityViolation();
        const vectors=fields(row.vector,['dense',...(point.sparse?['sparse']:[])]);
        verify_dense_readback(point.dense,vectors.dense);
        if(point.sparse){const sparse=fields(vectors.sparse,['indices','values']);verify_sparse_readback(point.sparse,sparse.indices,sparse.values);}
        return observed;
      }catch(error){if(error instanceof InvalidRequest)throw new IntegrityViolation();throw error;}
    };
    const present=new Map<string,Readonly<Data>>(),stale=new Set<string>(),base='/collections/'+config.physical_collection+'/points';
    for(let start=0;start<ids.length;start+=8){
      const batch=ids.slice(start,start+8),response=await request(base,{ids:batch,with_payload:true,with_vector:true});
      for(const row of rows(response.result,batch.length)){
        const id=String(row.id);if(!batch.includes(id)||present.has(id))throw new IntegrityViolation();
        const observed=validate(row);present.set(id,observed);if(!same(observed,expected.get(id)!.payload))stale.add(id);
      }
    }
    const seen=new Set<string>(),offsets=new Set<string>();let offset:string|null=null;
    const filter={must:SCOPE.map(key=>({key,match:{value:scope[key as keyof typeof scope]}}))};
    for(let page=0;;page++){
      if(page>=257)throw new ProviderUnavailable();
      const response=await request(base+'/scroll',{filter,limit:8,with_payload:true,with_vector:true,...(offset===null?{}:{offset})});
      let result:Data;try{result=fields(response.result,['points','next_page_offset']);}catch{throw new IntegrityViolation();}
      const observed=rows(result.points,8);
      for(const row of observed){
        const id=String(row.id);if(seen.has(id)||seen.size>=2048)throw new IntegrityViolation();
        const p=validate(row);if(!present.has(id)||!same(p,present.get(id)))throw new IntegrityViolation();seen.add(id);
      }
      if(result.next_page_offset===null)break;
      let next:string;try{next=uuid(result.next_page_offset);}catch{throw new IntegrityViolation();}
      if(!observed.length||offsets.has(next))throw new IntegrityViolation();offsets.add(next);offset=next;
    }
    if(seen.size!==present.size)throw new IntegrityViolation();parse_options(options);
    return Object.freeze({present_ids:Object.freeze([...present.keys()].sort()),missing_ids:Object.freeze(ids.filter(id=>!present.has(id))),stale_ids:Object.freeze([...stale].sort())});
  }catch(error){if(!admitted&&error instanceof IntegrityViolation)throw new InvalidRequest();throw safe(error);}
}
export async function verify_security_readback(transport:SupervisorTransport,config:unknown,expected:unknown,options:unknown,budget?:SecurityReadbackBudget):Promise<void>{
  if(typeof expected!=='object'||expected===null||types.isProxy(expected))throw new InvalidRequest();
  const tombstoned=Object.getOwnPropertyDescriptor(expected,'tombstoned')?.value;
  const result=await inspect_security_readback(transport,config,expected,options,budget);
  if(tombstoned?result.present_ids.length!==0:result.missing_ids.length!==0||result.stale_ids.length!==0)throw new IntegrityViolation();
}
