import {createHash} from 'node:crypto';
import {z} from 'zod';
import {QdrantPayloadSchema,PAYLOAD_FIELDS,parse_config,point_id,payload_tuple,same,type QdrantConfig,type QdrantNomination} from './qdrant-contract.js';
import {parse_request,parse_scope,type RetrievalRequest,type TrustedScope,type Filter} from './requests.js';
import {EvidenceSchema,type Evidence} from './results.js';
import {deep_freeze,identity,input_text,integer,valid_native_json,type DeepReadonly} from './shared.js';
import {IntegrityViolation,InvalidRequest,UnauthorizedScope,UnsupportedCapability} from './errors.js';

export const MAX_SOURCE_BYTES=16777216;
export const SOURCE_ROW_FIELDS=Object.freeze(['point_id','backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','source_sha256','text_sha256','dense_profile_id','sparse_profile_id','dense_profile','sparse_profile','authorization_revision','mutation_epoch','principal_ids','grant_ids','language','kind','tag','source_locator','parser_id','chunker_profile','source_bytes','canonical_utf8','excerpt_bytes','excerpt_utf8','active_generation_id','generation_published','generation_ever_published','tombstoned']);
export type SourceState='verified'|'unavailable'|'budget_exhausted';
export type Provenance=Readonly<{parser_id:string;chunker_profile:string;source_locator:string}>;
export type PrivateSource=Readonly<{canonical_text:string;source_sha256:string}>;
export class SourceFetch {
  constructor(readonly state:SourceState,readonly evidence:Evidence|null,readonly binding:object|null,readonly source_bytes:number,readonly stale:boolean,readonly private_source:PrivateSource|null){
    Object.freeze(this);
  }
  toJSON(){
    return {state:this.state,evidence:this.evidence,source_bytes:this.source_bytes,stale:this.stale};
  }
}
export function source_result(state:SourceState):SourceFetch{return new SourceFetch(state,null,null,0,false,null);}
export function native_options(value:unknown,keys:readonly string[]):void {
  try{
    if(value===null||typeof value!=='object'||Array.isArray(value)||(Object.getPrototypeOf(value)!==Object.prototype&&Object.getPrototypeOf(value)!==null)||Object.getOwnPropertySymbols(value).length)throw new Error();
    const names=Object.getOwnPropertyNames(value);
    if(names.length>keys.length)throw new Error();
    for(const key of names){
      if(key.length>256||!keys.includes(key))throw new Error();
      const descriptor=Object.getOwnPropertyDescriptor(value,key)!;
      if(!('value'in descriptor)||!descriptor.enumerable)throw new Error();
    }
  }catch{
    throw new InvalidRequest();
  }
}
export function fetch_options(value:unknown):{max_source_bytes:number;include_source:boolean}{
  try{
    if(!valid_native_json(value))throw new Error();
    return z.strictObject({max_source_bytes:integer(0,MAX_SOURCE_BYTES),include_source:z.boolean().default(false)}).parse(value);
  }catch{
    throw new InvalidRequest();
  }
}
const NominationSchema=z.strictObject({point_id:z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),branch:z.enum(['dense','sparse']),score:z.number().finite(),score_kind:z.enum(['cosine_similarity','dot_product']),score_direction:z.literal('higher_is_better'),verification:z.literal('UNVERIFIED'),payload:QdrantPayloadSchema});
function bounded_metadata(value:unknown):boolean{
  let nodes=0;
  const ancestors=new Set<object>();
  function visit(v:unknown,depth:number):boolean{
    if(++nodes>4096||depth>32)return false;
    if(v===null||typeof v==='boolean')return true;
    if(typeof v==='number')return Number.isFinite(v);
    if(typeof v==='string')return v.length<=1024&&!/[\uD800-\uDFFF]/u.test(v)&&Buffer.byteLength(v,'utf8')<=1024;
    if(typeof v!=='object'||ancestors.has(v)||Object.getOwnPropertySymbols(v).length)return false;
    const proto=Object.getPrototypeOf(v);
    if(proto!==null&&proto!==(Array.isArray(v)?Array.prototype:Object.prototype))return false;
    if(Array.isArray(v)&&v.length>4096)return false;
    const names=Object.getOwnPropertyNames(v);
    if(names.length>4097||(Array.isArray(v)&&names.length!==v.length+1))return false;
    ancestors.add(v);
    try{
      for(const key of names){
        if(key.length>256||/[\uD800-\uDFFF]/u.test(key)||Buffer.byteLength(key,'utf8')>256)return false;
        if(Array.isArray(v)&&key==='length')continue;
        if(Array.isArray(v)&&(!/^(?:0|[1-9][0-9]*)$/.test(key)||Number(key)>=v.length))return false;
        const descriptor=Object.getOwnPropertyDescriptor(v,key)!;
        if(!('value'in descriptor)||!descriptor.enumerable||!visit(descriptor.value,depth+1))return false;
      }
      return true;
    }finally{
      ancestors.delete(v);
    }
  }
  try{
    return visit(value,0);
  }catch{
    return false;
  }
}
export function validate_nomination(input:unknown,request:RetrievalRequest,scope:TrustedScope,config:QdrantConfig):QdrantNomination{
  let n:z.infer<typeof NominationSchema>;
  try{
    if(!bounded_metadata(input))throw new Error();
    n=NominationSchema.parse(input);
    if(n.branch==='dense'&&(n.score_kind!=='cosine_similarity'||n.score< -1.000001||n.score>1.000001))throw new Error();
    if(n.branch==='sparse'&&n.score_kind!=='dot_product')throw new Error();
  }catch{
    throw new InvalidRequest();
  }
  const p=n.payload;
  if(p.tenant_id!==scope.tenant_id||p.collection!==request.collection)throw new UnauthorizedScope();
  const contradiction=(n.branch==='sparse'&&config.sparse_profile===null)
    ||p.backend_namespace!==config.backend_namespace
    ||p.physical_collection!==config.physical_collection
    ||p.collection_incarnation!==config.collection_incarnation
    ||!same(p.dense_profile,config.dense_profile)
    ||!same(p.sparse_profile,config.sparse_profile)
    ||p.dense_profile_id!==config.dense_profile.profile_id
    ||p.sparse_profile_id!==(config.sparse_profile?.profile_id??'')
    ||n.point_id!==point_id(payload_tuple(p));
  if(contradiction)throw new IntegrityViolation();
  return deep_freeze(n);
}
export function compile_source_filters(filters:RetrievalRequest['required_filters'],start=1):readonly[string,readonly unknown[]]{
  const values:unknown[]=[];
  function visit(f:DeepReadonly<Filter>):string{
    if(f.op==='and'||f.op==='or')return '('+f.filters.map(visit).join(f.op==='and'?' AND ':' OR ')+')';
    if(f.op!=='eq'&&f.op!=='in')throw new UnsupportedCapability();
    const columns:Record<string,string>={document_id:'d.document_id',revision_id:'g.revision_id',language:'d.language',kind:'d.kind',tag:'d.tag'};
    const column=columns[f.field];
    if(!column)throw new InvalidRequest();
    if(f.op==='eq'){
      if(typeof f.value!=='string')throw new UnsupportedCapability();
      values.push(f.value);
      return `${column} = $${start+values.length-1}`;
    }
    if(f.op==='in'){
      if(!f.values.every(v=>typeof v==='string'))throw new UnsupportedCapability();
      values.push([...f.values]);
      return `${column} = ANY($${start+values.length-1}::text[])`;
    }
    throw new UnsupportedCapability();
  }
  return Object.freeze([`COALESCE((${filters.map(visit).join(' AND ')||'TRUE'}),FALSE)`,Object.freeze(values)]);
}
function matches(f:DeepReadonly<Filter>,row:Record<string,unknown>):boolean{
  if(f.op==='and')return f.filters.every(v=>matches(v,row));
  if(f.op==='or')return f.filters.some(v=>matches(v,row));
  if(f.op==='eq')return row[f.field]===f.value;
  if(f.op==='in')return f.values.some(v=>row[f.field]===v);
  return false;
}
export function row_integer(value:unknown):number {
  if(typeof value==='string'){
    if(value.length>16||!/^(?:0|[1-9][0-9]*)$/.test(value))throw new IntegrityViolation();
    const n=Number(value);
    if(!Number.isSafeInteger(n))throw new IntegrityViolation();
    return n;
  }
  if(typeof value!=='number'||!Number.isSafeInteger(value)||value<0)throw new IntegrityViolation();
  return value;
}
export function row_provenance(row:Record<string,unknown>):Provenance{
  try{
    const value={parser_id:row.parser_id,chunker_profile:row.chunker_profile,source_locator:row.source_locator};
    if(!bounded_metadata(value))throw new Error();
    return deep_freeze({parser_id:identity.parse(value.parser_id),chunker_profile:identity.parse(value.chunker_profile),source_locator:identity.parse(value.source_locator)});
  }catch{
    throw new IntegrityViolation();
  }
}
export function verify_source(input:unknown,rows:unknown,requestInput:unknown,scopeInput:unknown,configInput:unknown,options:{retained?:boolean;max_source_bytes:number;include_source?:boolean;bound_provenance?:Provenance}):SourceFetch{
  const request=parse_request(requestInput);
  const scope=parse_scope(scopeInput);
  const config=parse_config(configInput);
  const nom=validate_nomination(input,request,scope,config);
  compile_source_filters(request.required_filters);
  const budget=fetch_options({max_source_bytes:options.max_source_bytes,include_source:options.include_source??false});
  if(!Array.isArray(rows)||rows.length>1)throw new IntegrityViolation();
  if(!rows.length)return source_result('unavailable');
  const value=rows[0];
  try{
    native_options(value,SOURCE_ROW_FIELDS);
    const row=value as Record<string,unknown>;
    if(Object.keys(row).length!==SOURCE_ROW_FIELDS.length)throw new IntegrityViolation();
    // Snapshot the full payload separately from native byte buffers.
    const projected=Object.fromEntries(PAYLOAD_FIELDS.map(k=>[k,row[k]]));
    for(const k of ['language','kind','tag'])if(row[k]===null)delete projected[k];
    if(!bounded_metadata(projected)||!valid_native_json(projected))throw new IntegrityViolation();
    const payload=QdrantPayloadSchema.parse({...projected,start_byte:row_integer(row.start_byte),end_byte:row_integer(row.end_byte)});
    for(const k of ['point_id','backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','source_sha256','text_sha256','dense_profile_id','sparse_profile_id','dense_profile','sparse_profile']){
      const actual=k==='point_id'?row.point_id:k==='start_byte'?payload.start_byte:k==='end_byte'?payload.end_byte:row[k];
      const expected=k==='point_id'?nom.point_id:nom.payload[k as keyof typeof nom.payload];
      if(!same(actual,expected))throw new IntegrityViolation();
    }
    if(row.point_id!==point_id(payload_tuple(payload)))throw new IntegrityViolation();
    row_integer(row.mutation_epoch);
    const sourceBytes=row_integer(row.source_bytes);
    const excerptBytes=row_integer(row.excerpt_bytes);
    if(sourceBytes<1||sourceBytes>MAX_SOURCE_BYTES||excerptBytes<1||excerptBytes>32768||payload.end_byte>sourceBytes||payload.end_byte-payload.start_byte!==excerptBytes)throw new IntegrityViolation();
    if(typeof row.tombstoned!=='boolean'||typeof row.generation_published!=='boolean'||typeof row.generation_ever_published!=='boolean'||(row.active_generation_id!==null&&!identity.safeParse(row.active_generation_id).success))throw new IntegrityViolation();
    const provenance=row_provenance(row);
    if(options.bound_provenance&&!same(provenance,options.bound_provenance))throw new IntegrityViolation();
    if((row.canonical_utf8!==null&&!(row.canonical_utf8 instanceof Uint8Array))||(row.excerpt_utf8!==null&&!(row.excerpt_utf8 instanceof Uint8Array)))throw new IntegrityViolation();
    const loaded=row.canonical_utf8 instanceof Uint8Array?row.canonical_utf8.byteLength:0;
    if(row.canonical_utf8 instanceof Uint8Array&&row.canonical_utf8.byteLength!==sourceBytes)throw new IntegrityViolation();
    if(row.excerpt_utf8 instanceof Uint8Array&&row.excerpt_utf8.byteLength!==excerptBytes)throw new IntegrityViolation();
    if(loaded>budget.max_source_bytes)throw new IntegrityViolation();
    const authorized=!row.tombstoned
      &&payload.authorization_revision===scope.authorization_revision
      &&(payload.principal_ids.includes(scope.principal_id)||payload.grant_ids.some(g=>scope.grant_ids.includes(g)))
      &&request.required_filters.every(f=>matches(f,row));
    const published=row.generation_ever_published
      &&(options.retained||(row.generation_published&&row.active_generation_id===payload.generation_id));
    if(!authorized||!published)return new SourceFetch('unavailable',null,null,loaded,false,null);
    if(sourceBytes>budget.max_source_bytes){
      if(row.canonical_utf8!==null||row.excerpt_utf8!==null)throw new IntegrityViolation();
      return source_result('budget_exhausted');
    }
    if(!(row.canonical_utf8 instanceof Uint8Array)||!(row.excerpt_utf8 instanceof Uint8Array)||row.canonical_utf8.byteLength!==sourceBytes||row.excerpt_utf8.byteLength!==excerptBytes)throw new IntegrityViolation();
    const canonical=new Uint8Array(row.canonical_utf8);
    const excerpt=new Uint8Array(row.excerpt_utf8);
    const decoder=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true});
    const canonicalText=decoder.decode(canonical);
    const text=decoder.decode(canonical.subarray(payload.start_byte,payload.end_byte));
    if(!Buffer.from(canonical.subarray(payload.start_byte,payload.end_byte)).equals(Buffer.from(excerpt))||createHash('sha256').update(canonical).digest('hex')!==payload.source_sha256||createHash('sha256').update(excerpt).digest('hex')!==payload.text_sha256)throw new IntegrityViolation();
    const evidence_id=createHash('sha256').update(JSON.stringify(['cragkit.evidence.v1',payload.tenant_id,payload.collection,payload.document_id,payload.revision_id,payload.chunk_id,String(payload.start_byte),String(payload.end_byte),payload.text_sha256]),'utf8').digest('hex');
    const evidence=EvidenceSchema.parse({evidence_id,collection:payload.collection,document_id:payload.document_id,revision_id:payload.revision_id,chunk_id:payload.chunk_id,source_locator:provenance.source_locator,start_byte:payload.start_byte,end_byte:payload.end_byte,text,source_sha256:payload.source_sha256,text_sha256:payload.text_sha256});
    return new SourceFetch('verified',evidence,null,sourceBytes,row.active_generation_id!==payload.generation_id,budget.include_source?deep_freeze({canonical_text:canonicalText,source_sha256:payload.source_sha256}):null);
  }catch(e){
    if(e instanceof IntegrityViolation)throw e;
    throw new IntegrityViolation();
  }
}
