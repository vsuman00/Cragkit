/** Native source acceptance consumer. Administrative actions stay in the parent. */
import {createRequire} from 'node:module';
import {constants} from 'node:fs';
import {open,readFile,stat} from 'node:fs/promises';
import {PoolResource,parse_pool_config,bounded,verified_tls_options} from '../packages/typescript/dist/postgres-pool.js';
import {FetchQdrantTransport,QdrantSearchStore} from '../packages/typescript/dist/qdrant.js';
import {PostgresQdrantSourceStore} from '../packages/typescript/dist/qdrant-source.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {CragkitError} from '../packages/typescript/dist/errors.js';

const ACTIONS=new Set(['reset_active','reset_staging','reset_invalid_utf8','revoke','metadata','tombstone','supersede','source_outage']);
const CASE_IDS=['active','budget','revoke_before_provider','revoke_after_provider','metadata','tombstone','staging','superseded','retained','invalid_utf8','malformed','forged_binding','foreign_scope','source_outage'];
const EXPECTED_ERRORS=new Set(['IntegrityViolation','InvalidRequest','UnauthorizedScope','ProviderUnavailable']);
const DIAGNOSTIC_ERRORS=new Set(['InvalidRequest','UnauthorizedScope','UnsupportedCapability','IndexNotReady','EmbeddingProfileMismatch','ProviderUnavailable','DeadlineExceeded','ContextBudgetTooSmall','IntegrityViolation']);
const PREFLIGHT_ERRORS=new Set(['ERR_TLS_CERT_ALTNAME_INVALID','SELF_SIGNED_CERT_IN_CHAIN','DEPTH_ZERO_SELF_SIGNED_CERT','CERT_HAS_EXPIRED','UNABLE_TO_VERIFY_LEAF_SIGNATURE','INVALID_PURPOSE','UNABLE_TO_GET_ISSUER_CERT_LOCALLY','UNABLE_TO_GET_ISSUER_CERT','CERT_UNTRUSTED','CERT_REJECTED','CERT_NOT_YET_VALID','CERT_SIGNATURE_FAILURE','ECONNREFUSED','ECONNRESET','EPERM','EACCES','ENETUNREACH','EHOSTUNREACH','ENOTFOUND','EAI_AGAIN','53300','28P01','ETIMEDOUT']);
const LIMIT=16777216;
const now=()=>performance.now()/1000;
let STEP='input';
let FAILURE;

function diagnostic(error){
  return {
    stage:STEP,
    outcome:error instanceof CragkitError&&DIAGNOSTIC_ERRORS.has(error.name)?error.name:'internal',
  };
}

class Frames {
  #buffer=Buffer.alloc(0);
  #queue=[];
  #waiting;
  #failure;
  #ended=false;
  #data;
  #end;
  #error;
  constructor(){
    this.#data=chunk=>{
      try{
        if(this.#buffer.byteLength+chunk.byteLength>262144)throw new Error();
        this.#buffer=Buffer.concat([this.#buffer,chunk]);
        for(;;){
          const end=this.#buffer.indexOf(10);
          if(end<0)break;
          const line=this.#buffer.subarray(0,end);
          this.#buffer=this.#buffer.subarray(end+1);
          const text=new TextDecoder('utf-8',{fatal:true}).decode(line);
          const frame=JSON.parse(text);
          if(this.#waiting){
            const waiting=this.#waiting;
            this.#waiting=undefined;
            waiting.resolve(frame);
          }else{
            if(this.#queue.length>=2)throw new Error();
            this.#queue.push(frame);
          }
        }
      }catch{
        this.#fail();
      }
    };
    this.#end=()=>{
      this.#ended=true;
      if(this.#waiting)this.#fail();
    };
    this.#error=()=>this.#fail();
    process.stdin.on('data',this.#data);
    process.stdin.on('end',this.#end);
    process.stdin.on('error',this.#error);
  }
  #fail(){
    this.#failure=new Error('Native source protocol failed.');
    this.#waiting?.reject(this.#failure);
    this.#waiting=undefined;
    process.stdin.pause();
  }
  next(){
    if(this.#failure)return Promise.reject(this.#failure);
    if(this.#queue.length)return Promise.resolve(this.#queue.shift());
    if(this.#ended||this.#waiting)return Promise.reject(new Error('Native source protocol failed.'));
    return new Promise((resolve,reject)=>{this.#waiting={resolve,reject};});
  }
  close(){
    process.stdin.pause();
    process.stdin.removeListener('data',this.#data);
    process.stdin.removeListener('end',this.#end);
    process.stdin.removeListener('error',this.#error);
    process.stdin.destroy();
  }
}

async function emit(value){
  const line=JSON.stringify(value)+'\n';
  await new Promise((resolve,reject)=>{
    process.stdout.write(line,error=>error?reject(new Error('Native source output failed.')):resolve());
  });
}

function publicFetch(result){
  const value=result.toJSON();
  if(Object.hasOwn(value,'binding')||Object.hasOwn(value,'private_source')||Object.hasOwn(value,'canonical_text'))throw new Error();
  if(value.state==='verified'&&value.evidence?.text!=='café 雪')throw new Error();
  return value;
}

function verifyLedger(ledger){
  const snapshot=ledger.snapshot();
  if(snapshot.candidates!==1||snapshot.provider_calls!==0||snapshot.pending!==0)throw new Error();
  return snapshot;
}

async function readerLoginPreflight(config){
  STEP='reader_preflight_inputs';
  let client;
  let phase='created';
  try{
    const require=createRequire(new URL('../packages/typescript/package.json',import.meta.url));
    if(require('pg/package.json').version!=='8.23.1')throw new Error();
    const {Client}=require('pg');
    const credentials=await bounded((async()=>{
      const file=await open(config.passfile,constants.O_RDONLY|constants.O_NOFOLLOW);
      let contents;
      try{
        const info=await file.stat();
        if(!info.isFile()||info.size>65536||info.uid!==process.getuid?.()||(info.mode&0o077))throw new Error();
        contents=await file.readFile('utf8');
      }finally{
        await file.close();
      }
      const lines=contents.split(/\r?\n/).filter(Boolean);
      if(lines.length!==1||lines[0].includes('\\'))throw new Error();
      const fields=lines[0].split(':');
      if(fields.length!==5||fields.slice(0,4).join(':')!==[config.host,String(config.port),config.dbname,config.user].join(':')
          ||!/^[A-Za-z0-9._~-]+$/.test(fields[4]))throw new Error();
      const caInfo=await stat(config.sslrootcert);
      if(!caInfo.isFile()||caInfo.size>1048576)throw new Error();
      return {password:fields[4],ca:await readFile(config.sslrootcert,'utf8')};
    })(),{deadline:now()+2});
    client=new Client({
      host:config.host,
      port:config.port,
      database:config.dbname,
      user:config.user,
      password:credentials.password,
      ssl:verified_tls_options(config.host,credentials.ca),
      connectionTimeoutMillis:2000,
    });
    client.on('error',()=>{});
    const connection=client.connection;
    connection.on('connect',()=>{phase='tcp_connected';});
    connection.on('sslconnect',()=>{
      connection.stream.once('secureConnect',()=>{phase='tls_connected';});
    });
    connection.on('authenticationSASL',()=>{phase='sasl_initial';});
    connection.on('authenticationSASLContinue',()=>{phase='sasl_continue';});
    connection.on('authenticationSASLFinal',()=>{phase='sasl_final';});
    connection.on('readyForQuery',()=>{phase='ready';});
    STEP='reader_preflight_connect';
    await bounded(client.connect(),{deadline:now()+2});
    STEP='reader_preflight_query';
    const result=await bounded(client.query({
      text:'SELECT current_user=session_user, r.rolcanlogin, s.ssl FROM pg_catalog.pg_roles r JOIN pg_catalog.pg_stat_ssl s ON s.pid=pg_backend_pid() WHERE r.rolname=current_user AND current_user=$1',
      values:[config.user],
      rowMode:'array',
    }),{deadline:now()+2});
    STEP='reader_preflight_assert';
    if(JSON.stringify(result.rows)!=='[[true,true,true]]')throw new Error();
    await bounded(client.end(),{deadline:now()+2});
    client=undefined;

    STEP='reader_preflight_negative';
    const negativeProfiles=[
      {
        ssl:{...verified_tls_options(config.host,credentials.ca),servername:'wrong.example.invalid'},
        expected:new Set(['ERR_TLS_CERT_ALTNAME_INVALID']),
      },
      {
        ssl:{...verified_tls_options(config.host,credentials.ca),ca:[]},
        expected:new Set(['DEPTH_ZERO_SELF_SIGNED_CERT','SELF_SIGNED_CERT_IN_CHAIN','UNABLE_TO_VERIFY_LEAF_SIGNATURE','UNABLE_TO_GET_ISSUER_CERT_LOCALLY']),
      },
    ];
    for(const profile of negativeProfiles){
      phase='created';
      client=new Client({
        host:config.host,
        port:config.port,
        database:config.dbname,
        user:config.user,
        password:credentials.password,
        ssl:profile.ssl,
        connectionTimeoutMillis:2000,
      });
      client.on('error',()=>{});
      let accepted=false;
      let rejection;
      try{
        await bounded(client.connect(),{deadline:now()+2});
        accepted=true;
      }catch(error){
        rejection=error;
      }finally{
        await bounded(client.end(),{deadline:now()+2});
        client=undefined;
      }
      if(accepted)throw new Error();
      let code;
      try{code=rejection?.code;}catch{}
      if(!profile.expected.has(code))throw rejection??new Error();
    }
  }catch(error){
    let code;
    try{code=error?.code;}catch{}
    let outcome='internal';
    if(error instanceof CragkitError){
      outcome=diagnostic(error).outcome;
    }else if(typeof code==='string'){
      if(PREFLIGHT_ERRORS.has(code)||/^[A-Z0-9]{5}$/.test(code))outcome=code;
      else if(code.startsWith('ERR_SSL_')||code.startsWith('ERR_TLS_'))outcome='tls_error';
    }
    if(outcome==='internal'){
      let message;
      try{message=error?.message;}catch{}
      if(message==='timeout expired')outcome='ETIMEDOUT';
      else if(message==='The server does not support SSL connections'||message==='There was an error establishing an SSL connection')outcome='tls_error';
      else if(message==='Connection terminated unexpectedly')outcome='ECONNRESET';
    }
    let error_class='unknown';
    if(error instanceof CragkitError)error_class='CragkitError';
    else if(error instanceof DOMException)error_class='DOMException';
    else if(error instanceof TypeError)error_class='TypeError';
    else if(error instanceof RangeError)error_class='RangeError';
    else if(error instanceof Error)error_class='Error';
    FAILURE={stage:STEP,outcome,phase,error_class};
    throw new Error();
  }finally{
    if(client){
      try{
        await bounded(client.end(),{deadline:now()+2});
      }catch{
        FAILURE??={stage:STEP,outcome:'internal',phase,error_class:'unknown'};
        throw new Error();
      }
    }
  }
}

async function runCases(value,mutate){
  if(!value||!Array.isArray(value.cases)||value.cases.length!==CASE_IDS.length
      ||value.cases.some((c,index)=>c.id!==CASE_IDS[index]))throw new Error();
  const resource=new PoolResource(parse_pool_config(value.postgres_config));
  const qdrant=value.qdrant;
  const transport=new FetchQdrantTransport(qdrant.endpoint,{api_key:qdrant.api_key,allow_loopback_http:true});
  const candidates=new QdrantSearchStore(qdrant.config,transport);
  const records=[];
  try{
    await readerLoginPreflight(resource.config);
    STEP='reader_pool_open';
    await resource.open();
    STEP='candidate_initialize';
    await candidates.initialize({deadline:now()+10});
    for(const sample of value.cases){
      STEP='reset_'+sample.id;
      await mutate('reset_'+sample.setup);
      const deadline=now()+10;
      const request={...structuredClone(value.request),request_id:'source-native-'+sample.id,limits:{max_candidates:1,max_provider_calls:0}};
      const scope=structuredClone(value.scope);
      const ledger=new ExecutionLedger({limits:request.limits,deadline});
      STEP='candidate_search_'+sample.id;
      const nominations=await candidates.search_candidates(request,{
        scope,
        dense:qdrant.dense,
        branch_limits:{dense:1},
        ledger,
        deadline,
      });
      if(nominations.length!==1)throw new Error();
      let nomination=nominations[0];
      const beforeSource=JSON.stringify(verifyLedger(ledger));
      const store=new PostgresQdrantSourceStore(resource,qdrant.config);
      let handle;
      const record={id:sample.id,provider_spy_calls:0};
      try{
        STEP='source_initialize_'+sample.id;
        await store.initialize({deadline});
        STEP='source_flow_'+sample.id;
        if(sample.id==='metadata'){
          await mutate('metadata');
          scope.authorization_revision='auth-2';
        }else if(sample.id==='tombstone'){
          await mutate('tombstone');
          scope.authorization_revision='auth-2';
        }else if(sample.id==='superseded'){
          await mutate('supersede');
        }else if(sample.id==='foreign_scope'){
          scope.tenant_id='foreign';
        }
        handle=store.open_request(request,{scope,deadline});
        if(sample.id==='forged_binding'){
          await handle.release({},{purpose:'final',max_source_bytes:LIMIT});
          throw new Error();
        }
        if(sample.id==='malformed'){
          nomination=structuredClone(nomination);
          nomination.payload.source_locator='injected';
        }
        const fetched=await handle.fetch_candidate(nomination,{
          max_source_bytes:sample.id==='budget'?12:LIMIT,
          include_source:sample.id==='active'||sample.id==='retained',
        });
        record.fetch=publicFetch(fetched);
        record.outcome=fetched.state;
        if(fetched.state==='verified'){
          if(!fetched.evidence||fetched.evidence.text!=='café 雪'
              ||Buffer.byteLength(fetched.evidence.text,'utf8')!==9)throw new Error();
          if((sample.id==='active'||sample.id==='retained')
              &&fetched.private_source?.canonical_text!=='A café 雪.\n')throw new Error();
          if(['revoke_before_provider','revoke_after_provider','retained','active','source_outage'].includes(sample.id)){
            if(sample.id==='revoke_before_provider')await mutate('revoke');
            if(sample.id==='retained')await mutate('supersede');
            if(sample.id==='source_outage'){
              await mutate('source_outage');
            }else{
              const released=await handle.release(fetched.binding,{purpose:'provider',max_source_bytes:LIMIT});
              record.provider=publicFetch(released);
              if(released.state==='verified'){
                if(released.evidence?.text!=='café 雪')throw new Error();
                // This spy receives source text only after current authorization.
                record.provider_spy_calls++;
              }
              if(sample.id==='revoke_after_provider')await mutate('revoke');
            }
            const final=await handle.release(fetched.binding,{purpose:'final',max_source_bytes:LIMIT});
            record.final=publicFetch(final);
            record.outcome=final.state;
          }
        }
      }catch(error){
        if(error instanceof CragkitError&&error.name!==sample.outcome)FAILURE=diagnostic(error);
        if(!(error instanceof CragkitError)||!EXPECTED_ERRORS.has(error.name))throw new Error();
        record.outcome=error.name;
      }finally{
        try{
          await handle?.close();
        }finally{
          await store.close();
        }
      }
      STEP='source_assert_'+sample.id;
      record.ledger=verifyLedger(ledger);
      if(JSON.stringify(record.ledger)!==beforeSource||record.outcome!==sample.outcome
          ||record.provider_spy_calls!==sample.provider_spy_calls)throw new Error();
      if(sample.id==='retained'&&(!record.provider?.stale||!record.final?.stale))throw new Error();
      records.push(record);
    }
  }catch(error){
    FAILURE??=diagnostic(error);
    throw error;
  }finally{
    let failed=false;
    for(const resourceToClose of [candidates,transport,resource]){
      try{
        await resourceToClose.close();
      }catch{
        failed=true;
      }
    }
    if(failed)throw new Error();
  }
  return records;
}

const frames=new Frames();
try{
  const initial=await frames.next();
  if(initial?.type!=='init'||!initial.data)throw new Error();
  const mutate=async action=>{
    if(!ACTIONS.has(action))throw new Error();
    await emit({type:'mutation',action});
    const response=await frames.next();
    if(response?.type!=='mutation_result'||response.action!==action||response.ok!==true)throw new Error();
  };
  const cases=await runCases(initial.data,mutate);
  await emit({type:'result',cases});
}catch(error){
  const {stage,outcome,phase,error_class}=FAILURE??diagnostic(error);
  // Only fixed labels leave this boundary, never error messages or private inputs.
  try{
    await emit({type:'failure',stage,outcome,phase,error_class});
  }catch{
    // A broken output pipe cannot safely carry another diagnostic.
  }
  process.exitCode=1;
}finally{
  frames.close();
}
