/** Map a small caller-owned lexical index to native Cragkit evidence contracts. */
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {parse_request,parse_scope,parse_result,EvidenceSchema} from '../packages/typescript/dist/contracts.js';
import {pack_and_assess} from '../packages/typescript/dist/evidence.js';
import {DeadlineExceeded,IntegrityViolation,InvalidRequest,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability} from '../packages/typescript/dist/errors.js';

export const CAPABILITIES=Object.freeze({search:'lexical_substring',dense:false,source_resolution:'synchronous_immutable_utf8',
  required_filters:'string equality: document_id, revision_id, language, kind, tag',counting:'estimated'});
const FIELDS=['document_id','revision_id','language','kind','tag'];
const digest=value=>createHash('sha256').update(value).digest('hex');

export class ExistingIndexAdapter {
  #scope;#template;#records;#resolve;
  constructor(records,resolve_source,{scope,collection,required_filters=[],mode='lexical'}){
    if(mode!=='lexical'||typeof resolve_source!=='function')throw new UnsupportedCapability();
    if(!Array.isArray(records)||records.length>16||records.some(row=>!row||Object.getPrototypeOf(row)!==Object.prototype))throw new InvalidRequest();
    this.#scope=parse_scope(scope);
    this.#template=parse_request({request_id:'existing-index-example',query:'validate',collection,required_filters,
      limits:{max_candidates:16,max_attempts:1,max_provider_calls:0,max_context_tokens:2000,deadline_ms:5000},
      output_profile:{renderer:'cragkit.context.v2',counting_mode:'estimated',tokenizer:null,envelope_reserve_tokens:64}});
    for(const item of this.#template.required_filters){
      if(item.op!=='eq'||!FIELDS.includes(item.field)||typeof item.value!=='string')throw new UnsupportedCapability();
    }
    this.#records=structuredClone(records);this.#resolve=resolve_source;
  }
  #authorized(row){
    return row.tenant_id===this.#scope.tenant_id&&row.collection===this.#template.collection
      &&row.authorization_revision===this.#scope.authorization_revision&&Array.isArray(row.principal_ids)&&Array.isArray(row.grant_ids)
      &&row.principal_ids.length<=64&&row.grant_ids.length<=64&&[...row.principal_ids,...row.grant_ids].every(value=>typeof value==='string')
      &&(row.principal_ids.includes(this.#scope.principal_id)||row.grant_ids.some(value=>this.#scope.grant_ids.includes(value)));
  }
  #filtered(row){return this.#template.required_filters.every(item=>row[item.field]===item.value);}
  async retrieve(query,{deadline,signal}={}){
    if(typeof deadline!=='number'||!Number.isFinite(deadline)||(signal!==undefined&&!(signal instanceof AbortSignal)))throw new InvalidRequest();
    deadline=Math.min(deadline,performance.now()/1000+5);
    const check=()=>{if(signal?.aborted)throw new DOMException('Operation aborted.','AbortError');if(performance.now()/1000>=deadline)throw new DeadlineExceeded();};
    check();const request=parse_request({...this.#template,query}),evidence=[],sources=[],seen=new Set(),releaseRows=[];
    for(const row of this.#records){
      check();if(!this.#authorized(row))continue;
      try{
        for(const key of ['document_id','revision_id','chunk_id','source_locator','source_sha256','text_sha256']){
          if(typeof row[key]!=='string'||!row[key]||Buffer.byteLength(row[key])>256)throw new Error();
        }
        for(const key of ['source_sha256','text_sha256'])if(!/^[0-9a-f]{64}$/.test(row[key]))throw new Error();
        if(typeof row.search_text!=='string'||Buffer.byteLength(row.search_text)>8192||!Number.isSafeInteger(row.start_byte)||!Number.isSafeInteger(row.end_byte))throw new Error();
      }catch{throw new IntegrityViolation();}
      if(!this.#filtered(row)||!request.query.split(/\s+/u).filter(Boolean).every(term=>row.search_text.toLowerCase().includes(term.toLowerCase())))continue;
      let source;
      try{source=this.#resolve(row.tenant_id,row.collection,row.document_id,row.revision_id);}
      catch{throw new ProviderUnavailable();}
      if(source===null||source===undefined)throw new ProviderUnavailable();
      if(typeof source!=='object'||Object.getPrototypeOf(source)!==Object.prototype)throw new UnsupportedCapability();
      source=structuredClone(source);check();
      if(!this.#authorized(source)||!this.#filtered(source))throw new UnauthorizedScope();
      let item;
      try{
        if(['document_id','revision_id','source_sha256'].some(key=>source[key]!==row[key])||typeof source.text!=='string'||Buffer.byteLength(source.text)>65536)throw new Error();
        const raw=Buffer.from(source.text,'utf8');
        if(raw.length<1||raw.length>65536||digest(raw)!==row.source_sha256||new TextDecoder('utf-8',{fatal:true}).decode(raw)!==source.text)throw new Error();
        if(!(0<=row.start_byte&&row.start_byte<row.end_byte&&row.end_byte<=raw.length))throw new Error();
        const excerpt=raw.subarray(row.start_byte,row.end_byte),text=new TextDecoder('utf-8',{fatal:true}).decode(excerpt);
        if(digest(excerpt)!==row.text_sha256)throw new Error();
        const identity=[...['tenant_id','collection','document_id','revision_id','chunk_id'].map(key=>row[key]),row.start_byte,row.end_byte,row.text_sha256];
        item=EvidenceSchema.parse({evidence_id:'existing-'+digest(JSON.stringify(identity)),
          ...Object.fromEntries(['collection','document_id','revision_id','chunk_id','source_locator','start_byte','end_byte','source_sha256','text_sha256'].map(key=>[key,row[key]])),text});
      }catch{throw new IntegrityViolation();}
      evidence.push(item);
      releaseRows.push(row);
      const key=JSON.stringify([row.collection,row.document_id,row.revision_id]);
      if(!seen.has(key)){seen.add(key);sources.push(Object.fromEntries(['collection','document_id','revision_id','source_sha256','text'].map(name=>[name,source[name]])));}
    }
    const packed=await pack_and_assess(request.query,evidence,sources,{deadline,signal,max_tokens:2000,reserve:64,
      counting_mode:'estimated',surrounding_bytes:0});
    check();
    // Packing yields: reauthorize against the caller's current source authority.
    for(const row of releaseRows){
      let fresh;
      try{fresh=this.#resolve(row.tenant_id,row.collection,row.document_id,row.revision_id);}
      catch{throw new ProviderUnavailable();}
      if(fresh===null||fresh===undefined)throw new ProviderUnavailable();
      if(typeof fresh!=='object'||Object.getPrototypeOf(fresh)!==Object.prototype)throw new UnsupportedCapability();
      if(!this.#authorized(fresh)||!this.#filtered(fresh))throw new UnauthorizedScope();
      if(['document_id','revision_id','source_sha256'].some(key=>fresh[key]!==row[key])||typeof fresh.text!=='string'
        ||Buffer.byteLength(fresh.text)>65536||digest(fresh.text)!==row.source_sha256)throw new IntegrityViolation();
      check();
    }
    check();return parse_result({request_id:request.request_id,status:packed.status,execution:'complete',evidence:packed.evidence,
      facets:packed.facets,context:packed.context,limitations:[{code:'coverage_unknown'},...(packed.omitted_count?[{code:'truncated_evidence'}]:[])],
      usage:{attempt_count:1,provider_calls:0,provider_input_tokens:0,provider_output_tokens:0,cost_usd:0,cost_kind:'known',
        context_tokens:packed.context_tokens,context_counting:'estimated'},versions:{engine:'0.0.0',policy:'unassessed.v0',index:'existing_index_example.v1'}});
  }
}

export function demo_data(){
  const text='Café retries: at most three.\n',excerpt=text.slice(0,-1);
  const source={tenant_id:'tenant-a',collection:'docs',document_id:'retry',revision_id:'r1',authorization_revision:'auth-1',
    principal_ids:['reader-a'],grant_ids:[],language:'en',kind:'guide',tag:'public',text,source_sha256:digest(text)};
  const {text:unused,...record}=source;
  Object.assign(record,{chunk_id:'c1',source_locator:'synthetic:caller-owned/retry@r1',start_byte:0,end_byte:Buffer.byteLength(excerpt),
    text_sha256:digest(excerpt),search_text:excerpt});
  return {records:[record],source,scope:{tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:[],authorization_revision:'auth-1'}};
}
export async function demo(){
  const {records,source,scope}=demo_data();
  const adapter=new ExistingIndexAdapter(records,()=>structuredClone(source),{scope,collection:'docs',required_filters:[{op:'eq',field:'tag',value:'public'}]});
  return adapter.retrieve('retries',{deadline:performance.now()/1000+5});
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  process.stdout.write(JSON.stringify(await demo())+'\n');
}
