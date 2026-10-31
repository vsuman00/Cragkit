/** Optional native stdio MCP host. Engines and their clients remain caller-owned. */
import { Server, ProtocolError, specTypeSchemas, deserializeMessage, serializeMessage,
  type CallToolResult, type JSONRPCMessage, type Transport } from '@modelcontextprotocol/server';
import { Readable, Writable } from 'node:stream';
import { performance } from 'node:perf_hooks';
import { z } from 'zod';
import { parse_request, parse_tool_request, parse_scope, parse_result,
  ToolRequestSchema, type RetrievalRequest, type TrustedScope } from 'cragkit/contracts';
import { Cl100kCounter, count_context } from 'cragkit/context';
import { CragkitError, ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation,
  InvalidRequest, ProviderUnavailable, UnsupportedCapability } from 'cragkit/errors';

export type RetrievalEngine = {retrieve(request:RetrievalRequest,
  options:{scope:TrustedScope;deadline:number;signal:AbortSignal}):Promise<unknown>};
export type CreateServerOptions = {engine:RetrievalEngine;template:unknown;scope:unknown;
  final_serializer:(actual:CallToolResult)=>string;counter?:Cl100kCounter|null};
const MAX_FRAME=65536,MAX_OUTPUT=262144;
const CODES=new Set(['invalid_request','unauthorized_scope','unsupported_capability','index_not_ready',
  'embedding_profile_mismatch','provider_unavailable','deadline_exceeded','context_budget_too_small','integrity_violation']);
// Public pipe accessors select the concrete object between native-JSON
// admission and the output freeze transform. Custom UTF-8 predicates remain
// enforced by parse_tool_request, since JSON Schema counts code points.
const generatedInputSchema=z.toJSONSchema(ToolRequestSchema.in.out,{io:'input'});
if(generatedInputSchema.type!=='object')throw new UnsupportedCapability();
// The SDK's synchronous validator checks JSON values and narrows Zod's
// recursive JSON-schema type to the SDK's finite-depth Tool representation.
const checkedTool=specTypeSchemas.Tool['~standard'].validate({name:'cragkit_retrieve',inputSchema:generatedInputSchema});
if(checkedTool.issues!==undefined)throw new UnsupportedCapability();
const inputSchema=checkedTool.value.inputSchema;
const failure=(code:string):CallToolResult=>({content:[{type:'text',text:code}],isError:true});

function options(value:unknown,keys:readonly string[]):Record<string,unknown>{
  try{
    if(value===null||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype
      ||Object.getOwnPropertySymbols(value).length)throw new InvalidRequest();
    if(Object.entries(Object.getOwnPropertyDescriptors(value)).some(([key,d])=>!keys.includes(key)||!('value'in d)||!d.enumerable))throw new InvalidRequest();
    return value as Record<string,unknown>;
  }catch{throw new InvalidRequest();}
}

/** Bounds frames before invoking the official SDK parser; protocol serialization stays SDK-owned. */
export class BoundedStdioTransport implements Transport {
  onclose?:()=>void;
  onerror?:(error:Error)=>void;
  onmessage?:Transport['onmessage'];
  #parts:Buffer[]=[];
  #size=0;
  #started=false;
  #closed=false;
  constructor(readonly input:Readable=process.stdin,readonly output:Writable=process.stdout){}
  #data=(value:unknown):void=>{
    if(this.#closed)return;
    if(!Buffer.isBuffer(value)){this.#fail();return;}
    let offset=0;
    while(offset<value.length){
      const end=value.indexOf(10,offset),stop=end<0?value.length:end+1;
      const size=stop-offset;
      if(this.#size+size>MAX_FRAME){this.#fail();return;}
      this.#parts.push(value.subarray(offset,stop));this.#size+=size;offset=stop;
      if(end>=0){
        try{
          const line=new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(this.#parts,this.#size));
          this.#parts=[];this.#size=0;
          this.onmessage?.(deserializeMessage(line));
        }catch{this.#fail();return;}
      }else if(this.#size===MAX_FRAME){this.#fail();return;}
    }
  };
  #end=():void=>{if(this.#size)this.onerror?.(new Error('invalid_request'));void this.close();};
  #fail=():void=>{this.onerror?.(new Error('invalid_request'));void this.close();};
  async start():Promise<void>{
    if(this.#started||this.#closed)throw new InvalidRequest();
    this.#started=true;
    this.input.on('data',this.#data);this.input.on('end',this.#end);this.input.on('close',this.#end);
    this.input.on('error',this.#fail);this.output.on('error',this.#fail);
  }
  async send(message:JSONRPCMessage):Promise<void>{
    if(this.#closed)throw new ProviderUnavailable();
    // SDK validation errors must never echo rejected arguments or schema details.
    const safe='error'in message?{jsonrpc:'2.0' as const,id:message.id,
      error:{code:message.error.code,message:'invalid_request'}}:message;
    const text=serializeMessage(safe);
    await new Promise<void>((resolve,reject)=>this.output.write(text,error=>error?reject(new ProviderUnavailable()):resolve()));
  }
  async close():Promise<void>{
    if(this.#closed)return;
    this.#closed=true;this.#parts=[];this.#size=0;
    this.input.off('data',this.#data);this.input.off('end',this.#end);this.input.off('close',this.#end);
    this.input.off('error',this.#fail);this.output.off('error',this.#fail);
    this.onclose?.();
  }
}

export class RetrievalHost {
  readonly server:Server;
  readonly #engine:RetrievalEngine;
  readonly #template:RetrievalRequest;
  readonly #scope:TrustedScope;
  readonly #serializer:(actual:CallToolResult)=>string;
  readonly #counter:Cl100kCounter|null;
  #active:Promise<unknown>|null=null;
  #controller:AbortController|null=null;
  #stop:(()=>void)|null=null;
  #closed=false;
  #serving=false;
  #finished:(()=>void)|null=null;
  constructor(engine:RetrievalEngine,template:RetrievalRequest,scope:TrustedScope,
    serializer:(actual:CallToolResult)=>string,counter:Cl100kCounter|null){
    this.#engine=engine;this.#template=template;this.#scope=scope;this.#serializer=serializer;this.#counter=counter;
    this.server=new Server({name:'cragkit',version:'1.0.0-rc.1'},{capabilities:{tools:{}}});
    this.server.setRequestHandler('tools/list',async()=>({tools:[{name:'cragkit_retrieve',
      description:'Retrieve scoped source-linked evidence with coverage and limitations.',inputSchema,
      annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false}}]}));
    this.server.setRequestHandler('tools/call',async(request,ctx)=>{
      try{
        if(request.params.name!=='cragkit_retrieve')throw new InvalidRequest();
        return await this.retrieve(request.params.arguments,ctx.mcpReq.signal);
      }catch(error){
        if(ctx.mcpReq.signal.aborted)throw new ProtocolError(-32603,'invalid_request');
        const actual=failure(error instanceof CragkitError&&CODES.has(error.code)?error.code:'provider_unavailable');
        try{this.#checkOutput(actual);}catch{throw new ProtocolError(-32603,'invalid_request');}
        return actual;
      }
    });
    this.server.onerror=()=>{};
    this.server.onclose=()=>{this.#closed=true;this.#controller?.abort();this.#stop?.();this.#finished?.();};
  }
  #checkOutput(actual:CallToolResult):void{
    let serialized:unknown;
    try{serialized=this.#serializer(actual);}catch(error){if(error instanceof CragkitError)throw error;throw new InvalidRequest();}
    if(typeof serialized!=='string'||/[\uD800-\uDFFF]/u.test(serialized))throw new InvalidRequest();
    const size=Buffer.byteLength(serialized);
    if(size>MAX_OUTPUT)throw new ContextBudgetTooSmall();
    const profile=this.#template.output_profile;
    const tokens=profile.counting_mode==='strict'?Cl100kCounter.prototype.count.call(this.#counter,serialized):Math.ceil(size/4);
    if(tokens+profile.envelope_reserve_tokens>this.#template.limits.max_context_tokens)throw new ContextBudgetTooSmall();
  }
  async retrieve(input:unknown,external?:AbortSignal):Promise<CallToolResult>{
    if(this.#closed||this.#active!==null)throw new ProviderUnavailable();
    external?.throwIfAborted();
    let request:RetrievalRequest,scope:TrustedScope;
    try{
      const args=parse_tool_request(input);
      if(args.collection!==this.#template.collection)throw new InvalidRequest();
      request=parse_request({...this.#template,...args});scope=parse_scope(this.#scope);
    }catch{throw new InvalidRequest();}
    const deadline=performance.now()/1000+request.limits.deadline_ms/1000;
    const controller=new AbortController();this.#controller=controller;
    let timer:ReturnType<typeof setTimeout>|undefined;
    let abort:(()=>void)|undefined;
    const check=()=>{if(this.#closed||external?.aborted)throw new ProviderUnavailable();if(performance.now()/1000>=deadline)throw new DeadlineExceeded();};
    const boundary=new Promise<never>((_,reject)=>{
      timer=setTimeout(()=>{controller.abort();reject(new DeadlineExceeded());},request.limits.deadline_ms);
      abort=()=>{controller.abort();reject(new ProviderUnavailable());};external?.addEventListener('abort',abort,{once:true});
      this.#stop=()=>{controller.abort();reject(new ProviderUnavailable());};
    });
    const work=Promise.resolve().then(()=>{check();return this.#engine.retrieve(request,{scope,deadline,signal:controller.signal});});
    this.#active=work;
    const drained=()=>{if(this.#active===work){this.#active=null;this.#controller=null;}};
    void work.then(drained,drained);
    try{
      let raw:unknown;
      try{raw=await Promise.race([work,boundary]);check();}
      catch(error){if(error instanceof CragkitError)throw error;throw new ProviderUnavailable();}
      let content:string;
      try{
        let value=raw;
        if(raw!==null&&typeof raw==='object'){
          const field=Object.getOwnPropertyDescriptor(raw,'result');
          if(field){if(!('value'in field))throw new IntegrityViolation();value=field.value;}
        }
        const result=parse_result(value);
        if(result.request_id!==request.request_id)throw new IntegrityViolation();
        content=JSON.stringify(result);
        if(Buffer.byteLength(content)>MAX_OUTPUT)throw new ContextBudgetTooSmall();
      }catch(error){if(error instanceof ContextBudgetTooSmall)throw error;throw new IntegrityViolation();}
      const actual:CallToolResult={content:[{type:'text',text:content}],isError:false};
      this.#checkOutput(actual);
      check();return actual;
    }finally{
      if(timer!==undefined)clearTimeout(timer);if(abort)external?.removeEventListener('abort',abort);
      this.#stop=null;controller.abort();
    }
  }
  async run_stdio({input=process.stdin,output=process.stdout}:{input?:Readable;output?:Writable}={}):Promise<void>{
    if(this.#closed||this.#serving)throw new ProviderUnavailable();
    this.#serving=true;
    const done=new Promise<void>(resolve=>{this.#finished=resolve;});
    try{await this.server.connect(new BoundedStdioTransport(input,output));await done;}
    finally{await this.close();}
  }
  async close():Promise<void>{
    if(this.#closed)return;
    this.#closed=true;this.#controller?.abort();this.#stop?.();
    await this.server.close();this.#finished?.();
  }
}

export function create_server(value:CreateServerOptions):RetrievalHost{
  const o=options(value,['engine','template','scope','final_serializer','counter']);
  const engine=o.engine as RetrievalEngine;
  if(!engine||typeof engine.retrieve!=='function'||typeof o.final_serializer!=='function'
    ||Object.prototype.toString.call(o.final_serializer)==='[object AsyncFunction]')throw new InvalidRequest();
  const template=options(o.template,['collection','required_filters','limits','output_profile']);
  if(!Object.hasOwn(template,'collection'))throw new InvalidRequest();
  const bound=parse_request({...template,query:'validation',request_id:'template-validation'}),scope=parse_scope(o.scope);
  const counter=(o.counter as Cl100kCounter|null)??null,profile=bound.output_profile;
  if(profile.counting_mode==='strict'){
    if(!(counter instanceof Cl100kCounter)||Object.getPrototypeOf(counter)!==Cl100kCounter.prototype||profile.tokenizer!=='cl100k_base')throw new UnsupportedCapability();
  }
  count_context([],{max_tokens:bound.limits.max_context_tokens,reserve:profile.envelope_reserve_tokens,
    counter,counting_mode:profile.counting_mode});
  return new RetrievalHost(engine,bound,scope,o.final_serializer as (actual:CallToolResult)=>string,counter);
}
