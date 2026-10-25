/** Optional native LangChain tool. The application owns outer tracing and wire serialization. */
import { DynamicStructuredTool, type StructuredToolCallInput, type ToolReturnType, type ToolRunnableConfig } from '@langchain/core/tools';
import { ToolMessage } from '@langchain/core/messages';
import { RunTree } from 'langsmith/run_trees';
import { withRunTree } from 'langsmith/traceable';
import { z } from 'zod';
import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { parse_request, parse_tool_request, parse_scope, parse_result,
  type RetrievalRequest, type TrustedScope, type ToolRequest } from 'cragkit/contracts';
import { Cl100kCounter, count_context } from 'cragkit/context';
import { CragkitError, ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from 'cragkit/errors';

export type ToolEngine={retrieve(request:RetrievalRequest,options:{scope:TrustedScope;deadline:number;signal:AbortSignal}):Promise<unknown>};
export type FinalSerializer=(actual:string|ToolMessage)=>string;
export type CreateToolOptions={engine:ToolEngine;template:unknown;scope:unknown;final_serializer:FinalSerializer;counter?:Cl100kCounter|null;name?:string};
const factory=Symbol('cragkit.tool.factory');
const inputText=(bytes:number)=>z.string().min(1).max(bytes).refine(value=>Buffer.byteLength(value,'utf8')<=bytes
  &&!/[\0\uD800-\uDFFF]/u.test(value)&&/[^ \t\r\n\f\v]/.test(value));
// A concrete object keeps SDK JSON-schema conversion usable; core parsing remains definitive.
const NarrowToolSchema=z.strictObject({schema_version:z.literal('0.1').default('0.1'),
  request_id:inputText(256).default(()=>randomUUID()),query:inputText(16384),collection:inputText(128),
  search_hints:z.array(inputText(256)).max(8).default([])});

function native(value:unknown):boolean{
  const seen=new Set<object>();let nodes=0;
  const visit=(item:unknown,depth:number):boolean=>{
    if(++nodes>4096||depth>32)return false;
    if(item===null||typeof item==='boolean')return true;
    if(typeof item==='number')return Number.isFinite(item)&&Math.abs(item)<=Number.MAX_SAFE_INTEGER;
    if(typeof item==='string')return !/[\uD800-\uDFFF]/u.test(item);
    if(typeof item!=='object'||seen.has(item)||Object.getOwnPropertySymbols(item).length)return false;
    if(!Array.isArray(item)&&![Object.prototype,null].includes(Object.getPrototypeOf(item)))return false;
    if(Array.isArray(item)&&(item.length>4096||Object.keys(item).length!==item.length))return false;
    seen.add(item);
    try{return Object.entries(Object.getOwnPropertyDescriptors(item)).every(([key,d])=>Array.isArray(item)&&key==='length'||'value'in d&&d.enumerable&&visit(d.value,depth+1));}
    finally{seen.delete(item);}
  };
  try{return visit(value,0);}catch{return false;}
}
function objectOptions(value:unknown,keys:readonly string[]):Record<string,unknown>{
  try{
    if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype||Object.getOwnPropertySymbols(value).length)throw new InvalidRequest();
    if(Object.entries(Object.getOwnPropertyDescriptors(value)).some(([key,d])=>!keys.includes(key)||!('value'in d)||!d.enumerable))throw new InvalidRequest();
    return value as Record<string,unknown>;
  }catch{throw new InvalidRequest();}
}
function identifier(value:unknown):string{
  if(typeof value!=='string'||Buffer.byteLength(value)>256||!/[^ \t\r\n\f\v]/.test(value)||/[\0\uD800-\uDFFF]/u.test(value))throw new InvalidRequest();
  return value;
}
function reject():never{throw new UnsupportedCapability();}
async function rejectAsync():Promise<never>{throw new UnsupportedCapability();}
async function* rejectStream():AsyncGenerator<never>{throw new UnsupportedCapability();}

class RetrievalTool extends DynamicStructuredTool<typeof NarrowToolSchema,ToolRequest,unknown,string>{
  readonly #engine:ToolEngine;
  readonly #template:RetrievalRequest;
  readonly #scope:TrustedScope;
  readonly #serializer:FinalSerializer;
  readonly #counter:Cl100kCounter|null;
  readonly #boundName:string;
  constructor(token:symbol,engine:ToolEngine,template:RetrievalRequest,scope:TrustedScope,serializer:FinalSerializer,counter:Cl100kCounter|null,name:string){
    if(token!==factory)throw new UnsupportedCapability();
    super({name,description:'Retrieve scoped source-linked evidence with coverage and limitations.',schema:NarrowToolSchema,func:rejectAsync});
    this.#engine=engine;this.#template=template;this.#scope=scope;this.#serializer=serializer;this.#counter=counter;this.#boundName=name;
    Object.defineProperties(this,Object.fromEntries(['_callWithConfig','_batchWithConfig','_streamEventsV1','_streamEventsV2']
      .map(key=>[key,{value:reject,enumerable:false,writable:false,configurable:false}])));
    Object.freeze(this);
  }
  override async invoke<TInput extends StructuredToolCallInput<typeof NarrowToolSchema,unknown>,TConfig extends ToolRunnableConfig|undefined>(
    input:TInput,config?:TConfig,...extra:unknown[]):Promise<ToolReturnType<TInput,TConfig,string>>{
    if(extra.length)throw new InvalidRequest();
    const c=config===undefined?{}:objectOptions(config,['signal']);
    if(Object.hasOwn(c,'signal')&&!(c.signal instanceof AbortSignal))throw new InvalidRequest();
    const signal=c.signal as AbortSignal|undefined;
    return await withRunTree(new RunTree({name:'cragkit.tool',tracingEnabled:false}),()=>this.#execute(input,signal)) as ToolReturnType<TInput,TConfig,string>;
  }
  override async call<TArg extends StructuredToolCallInput<typeof NarrowToolSchema,unknown>,TConfig extends ToolRunnableConfig|undefined>(
    input:TArg,config?:TConfig,...extra:unknown[]):Promise<ToolReturnType<NonNullable<TArg>,TConfig,string>>{
    if(extra.length)throw new InvalidRequest();
    return await this.invoke(input,config) as ToolReturnType<NonNullable<TArg>,TConfig,string>;
  }
  async #execute(input:unknown,external?:AbortSignal):Promise<string|ToolMessage>{
    external?.throwIfAborted();
    let callId:string|null=null,args:ToolRequest;
    try{
      if(!native(input))throw new InvalidRequest();
      let value=input;
      if(value!==null&&typeof value==='object'&&!Array.isArray(value)&&(value as Record<string,unknown>).type==='tool_call'){
        const call=objectOptions(value,['type','id','name','args']);
        if(Object.keys(call).length!==4||call.name!==this.#boundName)throw new InvalidRequest();
        callId=identifier(call.id);value=call.args;
      }
      args=parse_tool_request(value);
      if(args.collection!==this.#template.collection)throw new InvalidRequest();
    }catch{throw new InvalidRequest();}
    const request=parse_request({...this.#template,...args}),scope=parse_scope(this.#scope);
    const deadline=performance.now()/1000+request.limits.deadline_ms/1000;
    const controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>|undefined,abort:(()=>void)|undefined;
    const check=()=>{external?.throwIfAborted();if(performance.now()/1000>=deadline)throw new DeadlineExceeded();};
    try{
      const boundary=new Promise<never>((_,reject)=>{
        timer=setTimeout(()=>{reject(new DeadlineExceeded());controller.abort();},Math.max(0,(deadline-performance.now()/1000)*1000));
        abort=()=>{reject(external!.reason);controller.abort(external!.reason);};external?.addEventListener('abort',abort,{once:true});
      });
      let raw:unknown;
      try{
        raw=await Promise.race([Promise.resolve().then(()=>{
          check();
          if(request.output_profile.counting_mode==='strict'){
            count_context([],{max_tokens:request.limits.max_context_tokens,reserve:request.output_profile.envelope_reserve_tokens,
              counter:this.#counter,counting_mode:'strict'});
          }
          return this.#engine.retrieve(request,{scope,deadline,signal:controller.signal});
        }),boundary]);
        check();
      }catch(error){
        if(error instanceof CragkitError)throw error;
        if(external?.aborted)throw external.reason;
        throw new ProviderUnavailable();
      }
      let content:string;
      try{
        if(!raw||typeof raw!=='object'||Object.getPrototypeOf(raw)!==Object.prototype)throw new IntegrityViolation();
        const field=Object.getOwnPropertyDescriptor(raw,'result');
        if(!field||!('value'in field))throw new IntegrityViolation();
        const result=parse_result(field.value);
        if(result.request_id!==request.request_id)throw new IntegrityViolation();
        content=JSON.stringify(result);
        if(Buffer.byteLength(content)>262144)throw new ContextBudgetTooSmall();
      }catch(error){if(error instanceof ContextBudgetTooSmall)throw error;throw new IntegrityViolation();}
      const actual:string|ToolMessage=callId===null?content:new ToolMessage({content,name:this.#boundName,tool_call_id:callId});
      let serialized:unknown;
      try{serialized=this.#serializer(actual);}catch(error){if(error instanceof CragkitError)throw error;throw new InvalidRequest();}
      if(typeof serialized!=='string'||!native(serialized))throw new InvalidRequest();
      const size=Buffer.byteLength(serialized,'utf8');
      if(size>262144)throw new ContextBudgetTooSmall();
      const profile=request.output_profile;
      let tokens:number;
      if(profile.counting_mode==='strict'){
        if(this.#counter===null)throw new UnsupportedCapability();
        tokens=Cl100kCounter.prototype.count.call(this.#counter,serialized);
      }else tokens=Math.ceil(size/4);
      if(tokens+profile.envelope_reserve_tokens>request.limits.max_context_tokens)throw new ContextBudgetTooSmall();
      check();return actual;
    }finally{
      if(timer!==undefined)clearTimeout(timer);if(abort)external?.removeEventListener('abort',abort);controller.abort();
    }
  }
  override _call=rejectAsync;
  override batch=rejectAsync;
  override stream=rejectAsync;
  override streamEvents=reject;
  override streamLog=rejectStream;
  override transform=rejectStream;
  override _streamIterator=rejectStream;
  override _streamLog=rejectStream;
  override _transformStreamWithConfig=rejectStream;
}

export function create_tool(options:CreateToolOptions):DynamicStructuredTool<typeof NarrowToolSchema,ToolRequest,unknown,string>{
  const o=objectOptions(options,['engine','template','scope','final_serializer','counter','name']);
  const engine=o.engine as ToolEngine;
  if(!engine||typeof engine.retrieve!=='function'||typeof o.final_serializer!=='function'
    ||Object.prototype.toString.call(o.final_serializer)==='[object AsyncFunction]')throw new InvalidRequest();
  const template=objectOptions(o.template,['collection','required_filters','limits','output_profile']);
  if(!Object.hasOwn(template,'collection')||!native(template))throw new InvalidRequest();
  const bound=parse_request({...template,query:'validation',request_id:'template-validation'}),scope=parse_scope(o.scope);
  const name=identifier(o.name===undefined?'cragkit_retrieve':o.name);
  const counter=o.counter as Cl100kCounter|null??null,profile=bound.output_profile;
  if(profile.counting_mode==='strict'){
    if(!(counter instanceof Cl100kCounter)||Object.getPrototypeOf(counter)!==Cl100kCounter.prototype||profile.tokenizer!=='cl100k_base')throw new UnsupportedCapability();
    count_context([],{max_tokens:bound.limits.max_context_tokens,reserve:profile.envelope_reserve_tokens,counter,counting_mode:'strict'});
  }else count_context([],{max_tokens:bound.limits.max_context_tokens,reserve:profile.envelope_reserve_tokens,counter,counting_mode:'estimated'});
  return new RetrievalTool(factory,engine,bound,scope,o.final_serializer as FinalSerializer,counter,name);
}
