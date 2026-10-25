import { DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';

export type QdrantTransportOptions={body?:Uint8Array;deadline:number;max_response_bytes?:number;signal?:AbortSignal};
export interface QdrantTransport {readonly bounded_responses:true;readonly cancellation_safe:true;request(method:string,path:string,options:QdrantTransportOptions):Promise<Uint8Array>}
export function abort_error():Error {const e=new Error('Operation aborted.');e.name='AbortError';return e;}
export function check_deadline(deadline:number,signal?:AbortSignal):void {
  if(typeof deadline!=='number'||!Number.isFinite(deadline)||Math.abs(deadline)>Number.MAX_SAFE_INTEGER)throw new InvalidRequest();
  if(signal?.aborted)throw abort_error();
  if(performance.now()/1000>=deadline)throw new DeadlineExceeded();
}
export async function drain(promise:Promise<unknown>,milliseconds=1000):Promise<boolean> {
  let timer:ReturnType<typeof setTimeout>|undefined;
  try {return await Promise.race([promise.then(()=>true,()=>true),new Promise<boolean>(resolve=>{timer=setTimeout(()=>resolve(false),milliseconds);})]);}
  finally{if(timer!==undefined)clearTimeout(timer);}
}
export async function abortable<T>(work:Promise<T>,signal:AbortSignal):Promise<T> {
  if(signal.aborted){void work.catch(()=>undefined);throw abort_error();}
  let rejectAbort:()=>void=()=>undefined;
  const aborted=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(abort_error());signal.addEventListener('abort',rejectAbort,{once:true});});
  try{return await Promise.race([work,aborted]);}finally{signal.removeEventListener('abort',rejectAbort);}
}

/** Native fetch transport; close drains cooperative work for at most one second. */
export class FetchQdrantTransport implements QdrantTransport {
  readonly bounded_responses=true as const;
  readonly cancellation_safe=true as const;
  readonly #endpoint:URL;
  readonly #key:string|undefined;
  readonly #fetch:typeof fetch;
  #closed=false;
  #controller:AbortController|undefined;
  #pending:Promise<unknown>|undefined;
  constructor(endpoint:unknown,options:{api_key?:string;allow_loopback_http?:boolean;fetch?:typeof fetch}={}) {
    try {
      if(typeof endpoint!=='string'||/[\x00-\x20\x7f\\]/.test(endpoint)||!options||typeof options!=='object'||Object.keys(options).some(k=>!['api_key','allow_loopback_http','fetch'].includes(k)))throw new Error();
      const url=new URL(endpoint);
      if(url.username||url.password||url.search||url.hash||url.pathname!=='/'||!['https:','http:'].includes(url.protocol))throw new Error();
      if(options.allow_loopback_http!==undefined&&typeof options.allow_loopback_http!=='boolean')throw new Error();
      if(url.protocol==='http:'&&(!options.allow_loopback_http||!['127.0.0.1','[::1]'].includes(url.hostname)))throw new UnsupportedCapability();
      if(options.api_key!==undefined&&(typeof options.api_key!=='string'||!options.api_key.length||options.api_key.length>4096||/[^\x21-\x7e]/.test(options.api_key)))throw new Error();
      if(options.fetch!==undefined&&typeof options.fetch!=='function')throw new Error();
      this.#endpoint=url;this.#key=options.api_key;this.#fetch=options.fetch??globalThis.fetch;
    }catch(e){if(e instanceof UnsupportedCapability)throw e;throw new InvalidRequest();}
  }
  async request(method:string,path:string,options:QdrantTransportOptions):Promise<Uint8Array> {
    if(this.#closed)throw new InvalidRequest();
    if(this.#controller)throw new ProviderUnavailable();
    if(!options||typeof options!=='object'||Object.keys(options).some(k=>!['body','deadline','max_response_bytes','signal'].includes(k)))throw new InvalidRequest();
    const cap=options.max_response_bytes??1048576;
    if(!Number.isSafeInteger(cap)||cap<1||cap>1048576||!['GET','POST'].includes(method)||typeof path!=='string'||!/^\/(?:collections\/[A-Za-z][A-Za-z0-9_-]{0,63}(?:\/points\/query)?|cluster)?$/.test(path))throw new InvalidRequest();
    if((method==='GET'&&options.body!==undefined)||(method==='POST'&&(!path.endsWith('/points/query')||!(options.body instanceof Uint8Array)))||(options.body!==undefined&&options.body.byteLength>262144))throw new InvalidRequest();
    if(options.signal!==undefined&&!(options.signal instanceof AbortSignal))throw new InvalidRequest();
    check_deadline(options.deadline,options.signal);
    // NODE_OPTIONS flags are not included in execArgv. Reject conservatively,
    // including quoted/escaped spellings, without exposing either option string.
    const startupOptions=[process.env.NODE_OPTIONS??'',...process.execArgv].join(' ').replace(/["'\\\s]/g,'');
    if(process.env.NODE_USE_ENV_PROXY==='1'||/--use[-_]env[-_]proxy/i.test(startupOptions)||process.env.NODE_TLS_REJECT_UNAUTHORIZED==='0')throw new UnsupportedCapability();
    const controller=new AbortController();this.#controller=controller;
    const external=()=>controller.abort();options.signal?.addEventListener('abort',external,{once:true});
    let expired=false;
    const timer=setTimeout(()=>{expired=true;controller.abort();},Math.min(2147483647,Math.max(1,Math.ceil((options.deadline-performance.now()/1000)*1000))));
    const body=options.body===undefined?undefined:new Uint8Array(options.body);
    let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
    const work=(async()=>{
      const headers:Record<string,string>={'accept':'application/json','accept-encoding':'identity'};
      if(body!==undefined)headers['content-type']='application/json';if(this.#key!==undefined)headers['api-key']=this.#key;
      const response=await this.#fetch(new URL(path,this.#endpoint),{method,headers,body,redirect:'error',credentials:'omit',signal:controller.signal});
      if(controller.signal.aborted){if(response.body)await drain(response.body.cancel());throw abort_error();}
      if(response.body)reader=response.body.getReader();
      if(!response.ok||response.redirected)throw new ProviderUnavailable();
      const encoding=response.headers.get('content-encoding');if(encoding!==null&&encoding.toLowerCase()!=='identity')throw new ProviderUnavailable();
      const length=response.headers.get('content-length');
      if(length!==null&&(!/^\d+$/.test(length)||Number(length)>cap))throw new ProviderUnavailable();
      if(!reader)throw new ProviderUnavailable();
      let size=0;const chunks:Uint8Array[]=[];
      for(;;){check_deadline(options.deadline,controller.signal);const part=await reader.read();if(part.done)break;if(!(part.value instanceof Uint8Array)||part.value.byteLength>cap-size)throw new ProviderUnavailable();size+=part.value.byteLength;chunks.push(new Uint8Array(part.value));}
      check_deadline(options.deadline,controller.signal);
      const result=new Uint8Array(size);let offset=0;for(const chunk of chunks){result.set(chunk,offset);offset+=chunk.byteLength;}return result;
    })();this.#pending=work;
    try {return await abortable(work,controller.signal);}
    catch(error) {
      controller.abort();
      if(expired||performance.now()/1000>=options.deadline)throw new DeadlineExceeded();
      if(options.signal?.aborted||this.#closed)throw abort_error();
      throw new ProviderUnavailable();
    }finally{
      controller.abort();clearTimeout(timer);options.signal?.removeEventListener('abort',external);
      if(reader){try{await drain(reader.cancel());}catch{}try{reader.releaseLock();}catch{}}
      if(!await drain(work))this.#closed=true;
      if(this.#controller===controller){this.#controller=undefined;this.#pending=undefined;}
    }
  }
  async close():Promise<void>{this.#closed=true;this.#controller?.abort();if(this.#pending)await drain(this.#pending);}
}
