import test from 'node:test';
import assert from 'node:assert/strict';
import {FetchQdrantTransport} from '../dist/qdrant.js';
import {DeadlineExceeded,InvalidRequest,ProviderUnavailable,UnsupportedCapability} from '../dist/errors.js';
const deadline=()=>performance.now()/1000+2;
const options=extra=>({deadline:deadline(),...extra});
function stream(chunks,onCancel=()=>{}){return new ReadableStream({start(c){for(const part of chunks)c.enqueue(new Uint8Array(part));c.close();},cancel:onCancel});}

test('transport streams bounded bytes with private explicit auth and no redirect',async()=>{
  let seen;
  const t=new FetchQdrantTransport('https://example.invalid',{api_key:'synthetic-key',fetch:async(url,init)=>{seen={url,init};return new Response(stream([[123],[125]]));}});
  assert.deepEqual(await t.request('GET','/',options()),new Uint8Array([123,125]));
  assert.equal(seen.init.headers['api-key'],'synthetic-key');assert.equal(seen.init.headers['accept-encoding'],'identity');assert.equal(seen.init.redirect,'error');assert.equal(seen.init.credentials,'omit');
  assert.ok(!JSON.stringify(t).includes('synthetic-key'));await t.close();await t.close();await assert.rejects(t.request('GET','/',options()),InvalidRequest);
});
test('endpoint, auth and same-origin path validation rejects credentials and traversal',async()=>{
  for(const endpoint of ['https://user:pass@example.invalid','https://example.invalid/?x=1','https://example.invalid/#x','https://example.invalid/base'])assert.throws(()=>new FetchQdrantTransport(endpoint),InvalidRequest);
  for(const endpoint of [' https://example.invalid','https://example.invalid\n','https://exam\tple.invalid','https:\\example.invalid','https://example.invalid\u007f'])assert.throws(()=>new FetchQdrantTransport(endpoint),InvalidRequest,JSON.stringify(endpoint));
  for(const endpoint of ['http://localhost','http://example.invalid','http://127.0.0.2'])assert.throws(()=>new FetchQdrantTransport(endpoint,{allow_loopback_http:true}),UnsupportedCapability);
  assert.throws(()=>new FetchQdrantTransport('https://example.invalid',{api_key:'secret\r\nheader'}),InvalidRequest);
  let calls=0;const t=new FetchQdrantTransport('http://127.0.0.1:6333',{allow_loopback_http:true,fetch:async()=>{calls++;return new Response('{}');}});
  for(const path of ['//example.invalid/','https://example.invalid/','/collections/../cluster','/collections/%2e%2e','/cluster?x=1','/cluster#x'])await assert.rejects(t.request('GET',path,options()),InvalidRequest);
  assert.equal(calls,0);await t.close();
});
test('stream cap is enforced while reading and rejects misleading lengths/encoding',async()=>{
  for(const response of [()=>new Response(stream([[1,2],[3,4]])),()=>new Response(stream([[1]]),{headers:{'content-length':'5'}}),()=>new Response(stream([[1]]),{headers:{'content-encoding':'gzip'}}),()=>new Response('private',{status:503})]){
    const t=new FetchQdrantTransport('https://example.invalid',{fetch:async()=>response()});
    await assert.rejects(t.request('GET','/',options({max_response_bytes:3})),ProviderUnavailable);await t.close();
  }
});
test('midflight body abort cancels reader and permits later reuse',async()=>{
  let cancel=false,entered;const started=new Promise(r=>entered=r);let first=true;
  const t=new FetchQdrantTransport('https://example.invalid',{fetch:async()=>{
    if(!first)return new Response('{}');first=false;
    return new Response(new ReadableStream({pull(){entered();return new Promise(()=>{});},cancel(){cancel=true;}}));
  }});
  const controller=new AbortController();const pending=t.request('GET','/',options({signal:controller.signal}));const rejected=assert.rejects(pending,e=>e.name==='AbortError');
  await started;controller.abort();await rejected;assert.equal(cancel,true);
  assert.deepEqual(await t.request('GET','/',options()),new Uint8Array(Buffer.from('{}')));await t.close();
});
test('deadline during headers, body deadline and close abort cooperative fetch/reader',async()=>{
  for(const mode of ['headers','body','close']){
    let entered;const started=new Promise(r=>entered=r);let aborted=false;
    const t=new FetchQdrantTransport('https://example.invalid',{fetch:async(_url,init)=>{
      if(mode==='body')return new Response(new ReadableStream({pull(){entered();return new Promise(()=>{});},cancel(){aborted=true;}}));
      return new Promise((_,reject)=>{entered();init.signal.addEventListener('abort',()=>{aborted=true;reject(new Error('secret endpoint'));},{once:true});});
    }});
    const pending=t.request('GET','/',options({deadline:mode==='close'?deadline():performance.now()/1000+0.03}));
    const rejected=assert.rejects(pending,mode==='close'?e=>e.name==='AbortError':DeadlineExceeded);await started;
    if(mode==='close')await t.close();await rejected;assert.equal(aborted,true);await t.close();
  }
});
test('early abort/expired deadline make no fetch call; concurrent request has no queue',async()=>{
  let calls=0,entered;const started=new Promise(r=>entered=r);
  const t=new FetchQdrantTransport('https://example.invalid',{fetch:async(_url,init)=>{calls++;entered();return new Promise((_,reject)=>init.signal.addEventListener('abort',()=>reject(Error()),{once:true}));}});
  const aborted=new AbortController();aborted.abort();await assert.rejects(t.request('GET','/',options({signal:aborted.signal})),e=>e.name==='AbortError');
  await assert.rejects(t.request('GET','/',options({deadline:performance.now()/1000-1})),DeadlineExceeded);assert.equal(calls,0);
  const controller=new AbortController();const pending=t.request('GET','/',options({signal:controller.signal}));const rejected=assert.rejects(pending,e=>e.name==='AbortError');await started;
  await assert.rejects(t.request('GET','/',options()),ProviderUnavailable);assert.equal(calls,1);controller.abort();await rejected;await t.close();
});
test('network errors are redacted and body bytes are snapshotted',async()=>{
  const t=new FetchQdrantTransport('https://example.invalid',{fetch:async()=>{throw new Error('credential private query raw response');}});
  await assert.rejects(t.request('GET','/',options()),e=>e instanceof ProviderUnavailable&&!String(e).includes('credential'));await t.close();
  let captured;const body=Buffer.from('{}');const copy=new FetchQdrantTransport('https://example.invalid',{fetch:async(_u,init)=>{await Promise.resolve();captured=new Uint8Array(init.body);return new Response('{}');}});
  const pending=copy.request('POST','/collections/test/points/query',options({body}));body[0]=0;await pending;assert.equal(captured[0],123);await copy.close();
});
test('NODE_OPTIONS environment-proxy flags reject before fetch and redact startup options',async()=>{
  const previous=process.env.NODE_OPTIONS;let calls=0;
  const t=new FetchQdrantTransport('https://example.invalid',{fetch:async()=>{calls++;return new Response('{}');}});
  try {
    for(const flags of ['--use-env-proxy','"--use-env-proxy"','--trace-warnings "--use-env-proxy"','--use_env_proxy','--use"-env"-proxy','--use-env-proxy=true']){
      process.env.NODE_OPTIONS=`${flags} --require=private-startup-path`;
      await assert.rejects(t.request('GET','/',options()),e=>e instanceof UnsupportedCapability&&!String(e).includes('private-startup-path'),flags);
    }
    assert.equal(calls,0);
  }finally{if(previous===undefined)delete process.env.NODE_OPTIONS;else process.env.NODE_OPTIONS=previous;await t.close();}
});
test('unsafe deadlines reject before fetch; long valid deadlines avoid timer overflow',async()=>{
  let calls=0;
  const t=new FetchQdrantTransport('https://example.invalid',{fetch:async(_url,init)=>{calls++;await new Promise(resolve=>setTimeout(resolve,10));assert.equal(init.signal.aborted,false);return new Response('{}');}});
  try {
    for(const value of [NaN,Infinity,-Infinity,Number.MAX_SAFE_INTEGER+1,-Number.MAX_SAFE_INTEGER-1])await assert.rejects(t.request('GET','/',{deadline:value}),InvalidRequest);
    assert.equal(calls,0);
    assert.deepEqual(await t.request('GET','/',{deadline:performance.now()/1000+3000000}),new Uint8Array(Buffer.from('{}')));assert.equal(calls,1);
  }finally{await t.close();}
});
