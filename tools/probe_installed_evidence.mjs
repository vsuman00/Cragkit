/** Installed-package conformance over explicit public fixtures and local fake SQL. */
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';
import dns from 'node:dns';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {resolve,relative,isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const denied=()=>{throw new Error('external_io_denied');};
globalThis.fetch=denied;
for(const [module,names]of [[net,['connect','createConnection','createServer']],[tls,['connect','createServer']],[http,['request','get','createServer']],[https,['request','get','createServer']],[dgram,['createSocket']],[dns,['lookup','resolve','resolve4','resolve6','resolveAny','reverse']],[childProcess,['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']]])for(const name of names)module[name]=denied;
net.Socket.prototype.connect=denied;net.Server.prototype.listen=denied;
for(const name of ['lookup','resolve','resolve4','resolve6','resolveAny','reverse'])dns.promises[name]=denied;
syncBuiltinESMExports();
const args=process.argv.slice(2),options={};
for(let index=0;index<args.length;index+=2){assert.ok(['--fixtures','--tokenizer','--prefix'].includes(args[index])&&args[index+1]&&!Object.hasOwn(options,args[index]));options[args[index]]=args[index+1];}
assert.equal(Object.keys(options).length,3);
const prefix=fs.realpathSync(options['--prefix']);
const within=path=>{const part=relative(prefix,fs.realpathSync(path));assert.ok(!isAbsolute(part)&&part!=='..'&&!part.startsWith('../'));};
const installed=import.meta.resolve('cragkit');within(fileURLToPath(installed));
const load=async name=>{const url=new URL(name+'.js',installed);within(fileURLToPath(url));return import(url.href);};
const [context,packing,assessment,pipeline,session,contracts]=await Promise.all(['context','packing','assessment','evidence','postgres-session','contracts'].map(load));
const fixture=name=>JSON.parse(fs.readFileSync(resolve(options['--fixtures'],name),'utf8'));
const sources=fixture('retrieval.json'),contexts=fixture('context.json'),packs=fixture('packing.json'),assessments=fixture('assessment.json'),pipelines=fixture('evidence-pipeline.json');
assert.deepEqual([sources.source_cases.length,contexts.cases.length,contexts.token_cases.length,packs.cases.length,assessments.cases.length,pipelines.cases.length],[23,8,127,17,35,6]);
class Client{
  status='I';calls=[];
  constructor(rows){this.rows=rows;}
  getTransactionStatus(){return this.status;}
  release(){}
  async query(query){
    this.calls.push(query);
    if(query.text.startsWith('BEGIN'))this.status='T';if(query.text==='ROLLBACK')this.status='I';
    if(query.text===session._ROLE_SQL||query.text===session._CATALOG_SQL)return {rows:[[true]]};
    if(query.text===session._HISTORY_SQL)return {rows:session.EXPECTED_HISTORY.map(row=>[...row])};
    if(query.text===session._COLLECTION_SQL)return {rows:[['0.1','native_fts.v1']]};
    if(query.text===session._SCOPE_SQL)return {rows:[]};
    if(query.text.includes('r.canonical_sha256'))return {rows:structuredClone(this.rows)};
    return {rows:[]};
  }
}
class Resource{
  config={release_timeout:0.05};
  constructor(rows){this.client=new Client(rows);}
  async withLease(options,body){return body(this.client,options.signal??new AbortController().signal);}
}
const output={revision:'INST-r1',source_cases:[],context:{cases:[],token_counts:[]},packing:[],assessment:[],pipeline:[]};
for(const item of sources.source_cases){
  const resource=new Resource(item.rows);
  try{
    const result=await new session.PostgresSession(resource).transaction(contracts.parse_request(item.request),{scope:contracts.parse_scope(item.scope),deadline:performance.now()/1000+5},handle=>handle.fetch_evidence(item.candidate,{max_source_bytes:item.max_source_bytes}));
    assert.ok(!Object.hasOwn(item,'error'));assert.deepEqual(result,item.expected);output.source_cases.push(result);
  }catch(error){assert.equal(error.code,item.error);assert.ok(item.error);if(error.code==='unauthorized_scope')assert.ok(!resource.client.calls.some(query=>query.text.includes('r.canonical_sha256')));output.source_cases.push({error:error.code});}
}
const counter=await context.Cl100kCounter.create(options['--tokenizer']);
try{
  for(const item of contexts.cases){
    try{
      const result=context.count_context(item.evidence,{max_tokens:item.max_tokens,reserve:item.reserve,counting_mode:item.counting_mode,...(item.counting_mode==='strict'?{counter}:{})});
      assert.ok(!Object.hasOwn(item,'expected_error'));assert.equal(result.context,item.expected_context);assert.equal(result.context_tokens,item.expected_context_tokens);assert.ok(result.total_tokens<=item.max_tokens);output.context.cases.push(result);
    }catch(error){assert.equal(error.code,item.expected_error);assert.ok(item.expected_error);output.context.cases.push({error:error.code});}
  }
  for(const item of contexts.token_cases){const tokens=counter.count(item.text);assert.equal(tokens,item.expected_tokens);output.context.token_counts.push({id:item.id,tokens});}
  for(const item of packs.cases){
    try{
      const result=await packing.pack_evidence(item.evidence,item.sources,{...item.options,deadline:performance.now()/1000+5,...(item.options.counting_mode==='strict'?{counter}:{})});
      assert.ok(!Object.hasOwn(item,'expected_error'));assert.deepEqual(result.evidence.map(value=>value.text),item.expected_texts);assert.ok(result.total_tokens<=item.options.max_tokens);assert.deepEqual(JSON.parse(result.context),result.evidence);
      for(const value of result.evidence){const source=item.sources.find(source=>['collection','document_id','revision_id'].every(key=>source[key]===value[key]));assert.ok(source);const raw=Buffer.from(source.text);assert.equal(raw.subarray(value.start_byte,value.end_byte).toString(),value.text);assert.equal(createHash('sha256').update(raw).digest('hex'),value.source_sha256);assert.equal(createHash('sha256').update(value.text).digest('hex'),value.text_sha256);}
      assert.equal(result.omitted_count,item.evidence.length-Object.values(result.aliases).reduce((sum,ids)=>sum+ids.length,0));
      const countOptions=Object.fromEntries(Object.entries(item.options).filter(([key])=>['max_tokens','reserve','counting_mode'].includes(key)));
      const counted=context.count_context(result.evidence,{...countOptions,...(item.options.counting_mode==='strict'?{counter}:{})});
      for(const [key,value]of Object.entries(counted))assert.deepEqual(result[key],value);
      output.packing.push(result);
    }catch(error){assert.equal(error.code,item.expected_error);assert.ok(item.expected_error);output.packing.push({error:error.code});}
  }
  for(const item of assessments.cases){
    try{const result=assessment.assess_evidence(item.query,item.evidence,item.policy);assert.ok(!Object.hasOwn(item,'expected_error'));assert.equal(result.status,item.expected_status);assert.deepEqual(result.facets.map(value=>value.state),item.expected_states);assessment.validate_assessment(item.evidence,result.facets);output.assessment.push(result);}
    catch(error){assert.equal(error.code,item.expected_error);assert.ok(item.expected_error);output.assessment.push({error:error.code});}
  }
  for(const item of pipelines.cases){
    try{const result=await pipeline.pack_and_assess(item.query,item.evidence,item.sources,{...item.options,policy:item.policy,deadline:performance.now()/1000+5,...(item.options.counting_mode==='strict'?{counter}:{})});assert.ok(!Object.hasOwn(item,'expected_error'));assert.equal(result.status,item.expected_status);assert.deepEqual(result.facets.map(value=>value.state),item.expected_states);assert.equal(result.rebalance_count,item.expected_rebalance_count);assert.ok(result.rebalance_count<=1&&result.total_tokens<=item.options.max_tokens);assert.deepEqual(JSON.parse(result.context),result.evidence);assessment.validate_assessment(result.evidence,result.facets);output.pipeline.push(result);}
    catch(error){assert.equal(error.code,item.expected_error);assert.ok(item.expected_error);output.pipeline.push({error:error.code});}
  }
}finally{counter.close();}
console.log(JSON.stringify(output));
