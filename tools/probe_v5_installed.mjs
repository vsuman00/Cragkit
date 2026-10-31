import assert from 'node:assert/strict';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { realpathSync } from 'node:fs';
import http from 'node:http'; import https from 'node:https'; import net from 'node:net';
import tls from 'node:tls'; import dns from 'node:dns'; import dgram from 'node:dgram'; import cp from 'node:child_process';
const profile=process.argv[2];
assert.ok(['core','postgres','qdrant','qdrant-authoritative','tokenizers','mcp'].includes(profile));
const require=createRequire(import.meta.url);
for(const [name,present] of [['pg',['postgres','qdrant-authoritative'].includes(profile)],['tiktoken',['tokenizers','mcp'].includes(profile)],['@modelcontextprotocol/server',profile==='mcp']]) {
  if(present) require.resolve(name); else assert.throws(()=>require.resolve(name));
}
for(const name of ['@qdrant/js-client-rest','@langchain/core','onnxruntime-node']) assert.throws(()=>require.resolve(name));
const deny=()=>{throw Error('Import attempted external I/O');};
globalThis.fetch=deny; globalThis.WebSocket=deny;
for(const [object,names] of [[http,['request','get','createServer']],[https,['request','get','createServer']],
 [net,['connect','createConnection','createServer']],[net.Socket.prototype,['connect']],[tls,['connect','createServer']],
 [dns,['lookup','resolve']],[dns.promises,['lookup','resolve']],[dgram,['createSocket']],
 [cp,['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']]]) for(const name of names) object[name]=deny;
syncBuiltinESMExports();
const modules={};
for(const name of ['cragkit','cragkit/qdrant','cragkit/qdrant-source','cragkit/qdrant-publication','cragkit/qdrant-corrective','cragkit/postgres',...(profile==='mcp'?['cragkit-mcp']:[])]) {
 const path=realpathSync(new URL(import.meta.resolve(name)));
 assert.ok(path.startsWith(process.cwd()+'/node_modules/'),name);
 await import(name); modules[name]=path;
}
assert.equal(typeof (await import('cragkit/qdrant-corrective')).QdrantCorrectiveBackend,'function');
assert.equal((await import('cragkit')).version,'0.0.0');
console.log(JSON.stringify({state:'passed',profile,modules}));
