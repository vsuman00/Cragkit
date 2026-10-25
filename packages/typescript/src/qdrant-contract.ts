import { createHash } from 'node:crypto';
import { z } from 'zod';
import { FAKE_PROFILE, OPENAI_PROFILE, EmbeddingBatchSchema, type EmbeddingBatch } from './embeddings.js';
import { parse_request, parse_scope, type Filter, type RetrievalRequest, type TrustedScope } from './requests.js';
import { deep_freeze, identity, input_text, integer, valid_native_json, type DeepReadonly } from './shared.js';
import { EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnsupportedCapability } from './errors.js';

export const SPARSE_PROFILE = deep_freeze({profile_id:'fake_manual_sparse_v1', encoder:'caller_supplied_fixture', model:'none', revision:'1', vocabulary:'fixture_uint32_v1', preprocessing:'none', weighting:'caller_supplied', corpus_statistics_revision:'none'});
const SparseProfileSchema = z.strictObject({profile_id:identity, encoder:identity, model:identity, revision:identity, vocabulary:identity, preprocessing:identity, weighting:identity, corpus_statistics_revision:identity});
const DenseProfileSchema = z.strictObject({profile_id:identity,provider:identity,model:identity,dimensions:integer(1,Number.MAX_SAFE_INTEGER),tokenizer:identity,normalization:identity});
export const QdrantConfigSchema = z.strictObject({backend_namespace:identity, physical_collection:z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/), collection_incarnation:identity, dense_profile:DenseProfileSchema, sparse_profile:SparseProfileSchema.nullable()}).transform(deep_freeze);
export type QdrantConfig = z.infer<typeof QdrantConfigSchema>;
export function same(a: unknown,b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const left=Object.keys(a), right=Object.keys(b);
  return left.length === right.length && left.every(k=>Object.hasOwn(b,k) && same((a as Record<string,unknown>)[k],(b as Record<string,unknown>)[k]));
}
export function parse_config(value: unknown): QdrantConfig {
  let config:QdrantConfig;
  try { if (!valid_native_json(value)) throw new Error(); config=QdrantConfigSchema.parse(value); } catch { throw new InvalidRequest(); }
  if ((!same(config.dense_profile,FAKE_PROFILE)&&!same(config.dense_profile,OPENAI_PROFILE)) || (config.sparse_profile !== null && (!same(config.sparse_profile,SPARSE_PROFILE)||same(config.dense_profile,OPENAI_PROFILE)))) throw new UnsupportedCapability();
  return config;
}

// This admission guard is local to E batches; core wire admission stays at 4096 nodes.
function bounded_batch(value:unknown):boolean {
  let nodes=0;const ancestors=new Set<object>();
  function visit(v:unknown,depth:number):boolean {
    if(++nodes>16384||depth>8)return false;
    if(v===null||typeof v==='boolean')return true;
    if(typeof v==='number')return Number.isFinite(v);
    if(typeof v==='string')return v.length<=1024&&!/[\uD800-\uDFFF]/u.test(v)&&Buffer.byteLength(v,'utf8')<=1024;
    if(typeof v!=='object'||ancestors.has(v)||Object.getOwnPropertySymbols(v).length)return false;
    if(Array.isArray(v)&&Object.getPrototypeOf(v)!==Array.prototype&&Object.getPrototypeOf(v)!==null)return false;
    if(!Array.isArray(v)&&Object.getPrototypeOf(v)!==Object.prototype&&Object.getPrototypeOf(v)!==null)return false;
    if(Array.isArray(v)&&v.length>16384)return false;
    const keys=Object.getOwnPropertyNames(v);
    if(keys.length>16385||(Array.isArray(v)&&keys.length!==v.length+1))return false;
    ancestors.add(v);
    try{
      for(const key of keys){
        if(key.length>256||/[\uD800-\uDFFF]/u.test(key)||Buffer.byteLength(key,'utf8')>256)return false;
        if(Array.isArray(v)&&key==='length')continue;
        if(Array.isArray(v)&&(!/^(?:0|[1-9][0-9]*)$/.test(key)||Number(key)>=v.length))return false;
        const d=Object.getOwnPropertyDescriptor(v,key)!;
        if(!('value'in d)||!d.enumerable||!visit(d.value,depth+1))return false;
      }
      return true;
    }finally{ancestors.delete(v);}
  }
  try{return visit(value,0);}catch{return false;}
}
const BatchBindingSchema=z.strictObject({profile:DenseProfileSchema,vectors:z.array(z.array(z.unknown())).min(1).max(8),usage:z.strictObject({prompt_tokens:integer(0,2147483647).nullable(),total_tokens:integer(0,2147483647).nullable(),cost_usd:z.number().finite().nonnegative().nullable(),cost_kind:z.enum(['known','estimated','unknown'])}),provider_calls:z.literal(1),synthetic:z.boolean()});
export function bind_embedding_batch(batch:unknown,profile:unknown,options:{expected_items?:number}={}):EmbeddingBatch {
  let expected:z.infer<typeof DenseProfileSchema>,value:z.infer<typeof BatchBindingSchema>,count:number|undefined;
  try{
    if(!bounded_batch(profile)||!bounded_batch(options)||!bounded_batch(batch)||!valid_native_json(profile)||!valid_native_json(options))throw new Error();
    expected=DenseProfileSchema.parse(profile);
    count=z.strictObject({expected_items:integer(1,8).optional()}).parse(options).expected_items;
    value=BatchBindingSchema.parse(batch);
    if(count!==undefined&&value.vectors.length!==count)throw new Error();
  }catch{throw new InvalidRequest();}
  if((!same(expected,FAKE_PROFILE)&&!same(expected,OPENAI_PROFILE))||!same(value.profile,expected)||value.synthetic!==(expected.provider==='fake'))throw new EmbeddingProfileMismatch();
  const vectors=value.vectors.map(v=>{if(v.length!==1536)throw new EmbeddingProfileMismatch();return dense_vector(v);});
  const usage=value.usage;
  if((usage.prompt_tokens===null)!==(usage.total_tokens===null)||(usage.prompt_tokens!==null&&usage.total_tokens!==null&&usage.total_tokens<usage.prompt_tokens))throw new InvalidRequest();
  if(expected.provider==='fake'){
    if(usage.cost_kind!=='known'||usage.cost_usd!==0)throw new InvalidRequest();
  }else if(!((usage.cost_kind==='estimated'&&usage.cost_usd!==null&&usage.cost_usd<=1000000)||(usage.cost_kind==='unknown'&&usage.cost_usd===null)))throw new InvalidRequest();
  try{return EmbeddingBatchSchema.parse({...value,vectors});}catch{throw new InvalidRequest();}
}
export const PAYLOAD_FIELDS = Object.freeze(['backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','source_sha256','text_sha256','dense_profile_id','sparse_profile_id','dense_profile','sparse_profile','authorization_revision','principal_ids','grant_ids','language','kind','tag']);
const digest=z.string().regex(/^[a-f0-9]{64}$/);
export const QdrantPayloadSchema=z.strictObject({backend_namespace:identity,physical_collection:identity,collection_incarnation:identity,tenant_id:identity,collection:input_text(128),document_id:identity,revision_id:identity,generation_id:identity,chunk_id:identity,start_byte:integer(0,Number.MAX_SAFE_INTEGER),end_byte:integer(1,Number.MAX_SAFE_INTEGER),source_sha256:digest,text_sha256:digest,dense_profile_id:identity,sparse_profile_id:input_text(256,false),dense_profile:DenseProfileSchema,sparse_profile:SparseProfileSchema.nullable(),authorization_revision:identity,principal_ids:z.array(identity).max(64),grant_ids:z.array(identity).max(64),language:input_text(1024,false).optional(),kind:input_text(1024,false).optional(),tag:input_text(1024,false).optional()}).refine(v=>v.start_byte<v.end_byte).transform(deep_freeze);
export type QdrantPayload=z.infer<typeof QdrantPayloadSchema>;
export type Branch='dense'|'sparse';
export type QdrantNomination=Readonly<{point_id:string;branch:Branch;score:number;score_kind:'cosine_similarity'|'dot_product';score_direction:'higher_is_better';verification:'UNVERIFIED';payload:QdrantPayload}>;
export function point_id(tuple: unknown):string {
  try {
    if (!valid_native_json(tuple) || !Array.isArray(tuple) || tuple.length!==12 || tuple[0]!=='cragkit.qdrant.point.v1' || !tuple.every(v=>typeof v==='string')) throw new Error();
    tuple.forEach((v,i)=>{ if(i===5) input_text(128).parse(v); else if(i!==11||v!=='') identity.parse(v); });
    const namespace=Buffer.from('6ba7b8119dad11d180b400c04fd430c8','hex');
    const hash=createHash('sha1').update(namespace).update(Buffer.from(JSON.stringify(tuple),'utf8')).digest().subarray(0,16);
    hash[6]=(hash[6]&15)|80; hash[8]=(hash[8]&63)|128;
    const h=hash.toString('hex'); return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
  } catch { throw new InvalidRequest(); }
}
export function payload_tuple(p:QdrantPayload):string[] {return ['cragkit.qdrant.point.v1',p.backend_namespace,p.physical_collection,p.collection_incarnation,p.tenant_id,p.collection,p.document_id,p.revision_id,p.generation_id,p.chunk_id,p.dense_profile_id,p.sparse_profile_id];}
function condition(filter:DeepReadonly<Filter>):unknown {
  if (filter.op==='and'||filter.op==='or') return {[filter.op==='and'?'must':'should']:filter.filters.map(condition)};
  if (filter.op==='eq' && typeof filter.value==='string') return {key:filter.field,match:{value:filter.value}};
  if (filter.op==='in' && filter.values.every(v=>typeof v==='string')) return {key:filter.field,match:{any:filter.values}};
  throw new UnsupportedCapability();
}
export function compile_filter(request:unknown,scope:unknown):Readonly<Record<string,unknown>> {
  const r=parse_request(request),s=parse_scope(scope);
  const should:unknown[]=[{key:'principal_ids',match:{value:s.principal_id}}];
  if(s.grant_ids.length) should.push({key:'grant_ids',match:{any:[...s.grant_ids]}});
  return deep_freeze({must:[{key:'tenant_id',match:{value:s.tenant_id}},{key:'collection',match:{value:r.collection}},{should},...r.required_filters.map(condition)]});
}
function matches(f:DeepReadonly<Filter>,p:QdrantPayload):boolean {
  if(f.op==='and') return f.filters.every(v=>matches(v,p));
  if(f.op==='or') return f.filters.some(v=>matches(v,p));
  if(f.op==='eq') return p[f.field]===f.value;
  if(f.op==='in') return f.values.some(v=>p[f.field]===v);
  return false;
}
export function validate_payload(value:unknown,config:QdrantConfig,r:RetrievalRequest,s:TrustedScope,id:unknown):QdrantPayload {
  try {
    const p=QdrantPayloadSchema.parse(value);
    if(p.backend_namespace!==config.backend_namespace||p.physical_collection!==config.physical_collection||p.collection_incarnation!==config.collection_incarnation||p.tenant_id!==s.tenant_id||p.collection!==r.collection||!same(p.dense_profile,config.dense_profile)||!same(p.sparse_profile,config.sparse_profile)||p.dense_profile_id!==config.dense_profile.profile_id||p.sparse_profile_id!==(config.sparse_profile?.profile_id??'')||(!p.principal_ids.includes(s.principal_id)&&!p.grant_ids.some(g=>s.grant_ids.includes(g)))||!r.required_filters.every(f=>matches(f,p))||id!==point_id(payload_tuple(p))) throw new Error();
    return p;
  } catch {throw new IntegrityViolation();}
}
export function dense_vector(value:unknown):readonly number[] {
  try {
    if(!valid_native_json(value)) throw new Error();
    const v=z.array(z.number().finite()).length(1536).parse(value);
    const norm=Math.sqrt(v.reduce((a,b)=>a+b*b,0));
    if(!Number.isFinite(norm)||Math.abs(norm-1)>0.001||v.some(x=>!Number.isFinite(Math.fround(x)))) throw new Error();
    return Object.freeze(v);
  }catch{throw new InvalidRequest();}
}
export function sparse_vector(value:unknown):Readonly<{indices:readonly number[];values:readonly number[]}> {
  try {
    if(!valid_native_json(value)) throw new Error();
    const v=z.strictObject({indices:z.array(integer(0,4294967295)).min(1).max(16),values:z.array(z.number().finite().positive()).min(1).max(16)}).parse(value);
    if(v.indices.length!==v.values.length||v.indices.some((x,i)=>i>0&&x<=v.indices[i-1])||v.values.some(x=>!Number.isFinite(Math.fround(x))||Math.fround(x)<=0)) throw new Error();
    return deep_freeze(v);
  }catch{throw new InvalidRequest();}
}

// Syntax validation precedes this scan; keys retain their decoded spellings.
export function parse_response(raw:unknown):unknown {
  try {
    if(!(raw instanceof Uint8Array)||raw.byteLength>1048576) throw new Error();
    const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw);
    JSON.parse(text);
    let at=0,nodes=0;
    const ws=()=>{while(at<text.length&&/[ \t\r\n]/.test(text[at])) at++;};
    function str():string {const start=at++;while(text[at]!=='"'){if(text[at]==='\\') at++;at++;}at++;const s=JSON.parse(text.slice(start,at)) as string;if(/[\uD800-\uDFFF]/u.test(s)) throw new Error();return s;}
    function val(depth:number):unknown {
      if(++nodes>32768||depth>32) throw new Error();ws();
      if(text[at]==='"') return str();
      if(text[at]==='{'){at++;ws();const out:Record<string,unknown>=Object.create(null);if(text[at]==='}'){at++;return out;}for(;;){ws();const key=str();ws();at++;if(Object.hasOwn(out,key))throw new Error();out[key]=val(depth+1);ws();if(text[at++]==='}')return out;}}
      if(text[at]==='['){at++;ws();const out:unknown[]=[];if(text[at]===']'){at++;return out;}for(;;){out.push(val(depth+1));ws();if(text[at++]===']')return out;}}
      const start=at;while(at<text.length&&!/[ \t\r\n,\]}]/.test(text[at]))at++;const token=text.slice(start,at);
      if(token==='null')return null;if(token==='true')return true;if(token==='false')return false;
      if(token.length>128)throw new Error();const n=Number(token);if(!Number.isFinite(n))throw new Error();return n;
    }
    return val(0);
  }catch{throw new IntegrityViolation();}
}
