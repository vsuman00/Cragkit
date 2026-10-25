import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { z } from 'zod';
import { InvalidRequest } from './errors.js';
import { integer, safe_number, valid_native_json } from './shared.js';

const StageSchema=z.enum(['start','search','capture','planning','retry','stop','error','cancelled']);
const stops=['sufficient','repeated_query','repeated_candidates','no_progress','no_plan','coverage_unknown',
  'attempts_exhausted','subqueries_exhausted','plan_complete','budget_exhausted'] as const;
const errors=['invalid_request','unauthorized_scope','unsupported_capability','index_not_ready','embedding_profile_mismatch',
  'provider_unavailable','deadline_exceeded','context_budget_too_small','integrity_violation'] as const;
const FieldsSchema=z.strictObject({trace_id:z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/),
  attempt:integer(0,10),elapsed_ms:safe_number.min(0).max(300000),candidate_count:integer(0,Number.MAX_SAFE_INTEGER).default(0),
  provider_calls:integer(0,Number.MAX_SAFE_INTEGER).default(0),stop_reason:z.string().nullable().default(null)});
export type EventStage=z.infer<typeof StageSchema>;
export type EventFields=z.input<typeof FieldsSchema>;
export type ExecutionEvent=Readonly<z.infer<typeof FieldsSchema>&{stage:EventStage;event_id:string}>;
export type EventSnapshot=Readonly<{queued:number;dropped:number;exported:number}>;
export type EventExporter=(event:ExecutionEvent,options:{deadline:number;signal:AbortSignal})=>Promise<unknown>;
export function new_trace():string{return randomUUID();}
function checked<T>(schema:z.ZodType<T>,value:unknown):T{
  try{if(!valid_native_json(value))throw new InvalidRequest();return schema.parse(value);}catch{throw new InvalidRequest();}
}
function optionObject(value:unknown,keys:readonly string[]):Record<string,unknown>{
  try{
    if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype||Object.getOwnPropertySymbols(value).length)throw new InvalidRequest();
    if(Object.entries(Object.getOwnPropertyDescriptors(value)).some(([key,d])=>!keys.includes(key)||!('value'in d)||!d.enumerable))throw new InvalidRequest();
    return value as Record<string,unknown>;
  }catch{throw new InvalidRequest();}
}
type Active={controller:AbortController;settled:boolean};
/** Bounded caller-owned events; emit never runs the exporter. */
export class EventSink{
  readonly #exporter:EventExporter|null;
  readonly #capacity:number;
  readonly #timeout:number;
  #queue:ExecutionEvent[]=[];
  #dropped=0;#exported=0;#ordinal=0;
  #closed=false;#flushing=false;
  #active:Active|null=null;
  constructor(options:{exporter?:EventExporter|null;capacity?:number;timeout_ms?:number}={}){
    const o=optionObject(options,['exporter','capacity','timeout_ms']);
    if(o.exporter!=null&&typeof o.exporter!=='function')throw new InvalidRequest();
    const c=checked(z.strictObject({capacity:integer(1,128).default(32),timeout_ms:integer(1,100).default(25)}),
      Object.fromEntries(Object.entries(o).filter(([key])=>key!=='exporter')));
    this.#exporter=o.exporter as EventExporter??null;this.#capacity=c.capacity;this.#timeout=c.timeout_ms;
  }
  emit(stage:EventStage,options:EventFields):boolean{
    if(this.#closed)throw new InvalidRequest();
    const s=checked(StageSchema,stage),fields=checked(FieldsSchema,options);
    const reason=fields.stop_reason;
    if(s==='stop'?!stops.includes(reason as typeof stops[number]):s==='error'?!errors.includes(reason as typeof errors[number]):s==='cancelled'?reason!=='cancelled':reason!==null)throw new InvalidRequest();
    if(this.#ordinal>=Number.MAX_SAFE_INTEGER)throw new InvalidRequest();
    const ordinal=++this.#ordinal;
    if(this.#queue.length>=this.#capacity){this.#dropped++;return false;}
    this.#queue.push(Object.freeze({...fields,stage:s,event_id:`${fields.trace_id}:${ordinal}`}));return true;
  }
  snapshot():EventSnapshot{return Object.freeze({queued:this.#queue.length,dropped:this.#dropped,exported:this.#exported});}
  drain():readonly ExecutionEvent[]{
    const events=this.#queue.splice(0);this.#dropped+=events.length;
    return Object.freeze(events.map(event=>Object.freeze({...event})));
  }
  #drop():void{this.#dropped+=this.#queue.length;this.#queue=[];}
  close():void{if(this.#closed)return;this.#closed=true;this.#drop();this.#active?.controller.abort();}
  async flush(options:{deadline:number;signal?:AbortSignal}):Promise<EventSnapshot>{
    const o=optionObject(options,['deadline','signal']);
    if(!safe_number.safeParse(o.deadline).success||(o.signal!==undefined&&!(o.signal instanceof AbortSignal)))throw new InvalidRequest();
    const deadline=o.deadline as number,signal=o.signal as AbortSignal|undefined;
    if(signal?.aborted){this.#drop();signal.throwIfAborted();}
    if(this.#flushing)return this.snapshot();
    if(this.#active&&!this.#active.settled){this.#drop();return this.snapshot();}
    if(this.#closed||!this.#exporter){this.#drop();return this.snapshot();}
    this.#flushing=true;
    const count=this.#queue.length;
    try{
      for(let index=0;index<count&&this.#queue.length;index++){
        if(signal?.aborted){this.#drop();signal.throwIfAborted();}
        if(this.#closed||performance.now()/1000>=deadline){this.#drop();break;}
        const event=this.#queue.shift()!,controller=new AbortController();
        const active:Active={controller,settled:false};this.#active=active;
        const effective=Math.min(deadline,performance.now()/1000+this.#timeout/1000);
        let timer:ReturnType<typeof setTimeout>|undefined;
        let cancel:(()=>void)|undefined,childAbort:(()=>void)|undefined;
        try{
          const boundary=new Promise<'timeout'|'cancel'|'closed'>(resolve=>{
            childAbort=()=>resolve(signal?.aborted?'cancel':this.#closed?'closed':'timeout');
            controller.signal.addEventListener('abort',childAbort,{once:true});
            cancel=()=>controller.abort(signal!.reason);signal?.addEventListener('abort',cancel,{once:true});
            timer=setTimeout(()=>{resolve('timeout');controller.abort();},Math.max(0,(effective-performance.now()/1000)*1000));
          });
          const delivery=Promise.resolve().then(()=>{
            controller.signal.throwIfAborted();
            if(performance.now()/1000>=effective)throw new Error('Exporter deadline exceeded.');
            return this.#exporter!(Object.freeze({...event}),{deadline:effective,signal:controller.signal});
          }).then(()=>true,()=>false).finally(()=>{active.settled=true;if(this.#active===active)this.#active=null;});
          const outcome=await Promise.race([delivery,boundary]);
          const expired=performance.now()/1000>=effective;
          if(outcome===true&&!signal?.aborted&&!this.#closed&&!expired)this.#exported++;
          else this.#dropped++;
          if(signal?.aborted){this.#drop();signal.throwIfAborted();}
          if(typeof outcome==='string'||(!active.settled)||this.#closed||expired){this.#drop();break;}
        }finally{
          if(timer!==undefined)clearTimeout(timer);
          if(cancel)signal?.removeEventListener('abort',cancel);
          if(childAbort)controller.signal.removeEventListener('abort',childAbort);
        }
      }
      return this.snapshot();
    }finally{this.#flushing=false;}
  }
}
