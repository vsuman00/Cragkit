/** Native PGO-r1 mechanics child. The parent provisions and removes its database fixture. */
import { pathToFileURL } from 'node:url';
import { PoolResource, parse_pool_config, now } from '../packages/typescript/dist/postgres-pool.js';
import { EmbeddingAdapter, FAKE_PROFILE, OPENAI_PROFILE } from '../packages/typescript/dist/embeddings.js';
import { PostgresVectorIndexer } from '../packages/typescript/dist/vector-ingestion.js';
import { PostgresRetriever } from '../packages/typescript/dist/retrieval.js';
import { PostgresCorrectiveBackend } from '../packages/typescript/dist/postgres-corrective.js';
import { ExecutionLedger } from '../packages/typescript/dist/execution.js';
import { parse_request, parse_scope } from '../packages/typescript/dist/contracts.js';

class CheckFailure extends Error {}
function check(value) { if (!value) throw new CheckFailure(); }
const source='Profile mechanics preserve exact source evidence.';
const scope=parse_scope({tenant_id:'profile-tenant',principal_id:'profile-reader',grant_ids:['profile-grant'],authorization_revision:'1'});
const collection='profile-checks';
const bound=()=>({scope,deadline:now()+10});
const ingestInput=(openai=false)=>({...bound(),collection,document_id:openai?'profile-openai-document':'profile-document',
  intent_id:openai?'profile-openai-intent':'profile-intent',source_locator:'fixture:profile'});
function evidenceObservation(result) {
  return {evidence:result.evidence.map(({document_id,revision_id,source_sha256,text_sha256,start_byte,end_byte})=>
    ({document_id,revision_id,source_sha256,text_sha256,start_byte,end_byte})),provider_calls:result.usage.provider_calls,
  cost_kind:result.usage.cost_kind,cost_usd:result.usage.cost_usd};
}
async function refusal(operation, expected) {
  try { await operation(); } catch(error) { check(error?.code===expected);return expected; }
  throw new CheckFailure();
}

export async function run(input) {
  check(input && Object.getPrototypeOf(input)===Object.prototype
    && Object.keys(input).sort().join(',')==='reader_config,storage,writer_config'
    && ['legacy','upgraded'].includes(input.storage));
  const reader=new PoolResource(parse_pool_config({...input.reader_config,max_size:1}));
  const writer=new PoolResource(parse_pool_config({...input.writer_config,max_size:1}));
  let activeLeases=0,transportCalls=0;
  for(const resource of [reader,writer]) {
    const lease=resource.withLease.bind(resource);
    resource.withLease=(options,operation)=>lease(options,async (...args)=>{
      activeLeases++;
      try{return await operation(...args);}finally{activeLeases--;}
    });
  }
  const fake=new EmbeddingAdapter(async body=>{
    check(activeLeases===0);
    const request=JSON.parse(new TextDecoder().decode(body));
    const tokens=request.input.reduce((total,text)=>total+Buffer.byteLength(text),0);
    return Buffer.from(JSON.stringify({model:FAKE_PROFILE.model,
      data:request.input.map((_,index)=>({index,embedding:[1,...Array(1535).fill(0)]})),
      usage:{prompt_tokens:tokens,total_tokens:tokens}}));
  },{name:FAKE_PROFILE.tokenizer,count:text=>Buffer.byteLength(text)});
  // Never return synthetic vectors under the live profile. This is dispatch mechanics only.
  const live=new EmbeddingAdapter(async()=>{
    check(activeLeases===0);transportCalls++;throw new Error('injected transport failure');
  },{name:OPENAI_PROFILE.tokenizer,count:()=>1},{profile:OPENAI_PROFILE,
    policy:{allow_live:true,max_cost_usd:.01,usd_per_million_tokens:.02}});
  const checks=[],observations=[];
  const request=parse_request({query:'Profile mechanics',collection});
  const expected=input.storage==='legacy'?'unsupported_capability':'provider_unavailable';
  const expectedCalls=input.storage==='legacy'?0:1;
  try {
    await reader.open();await writer.open();
    const indexer=new PostgresVectorIndexer(writer,async()=>true,fake);
    const staged=await indexer.stage(source,ingestInput());
    await indexer.publish(source,ingestInput());
    const replay=await indexer.stage(source,ingestInput());
    check(replay.replayed===true && replay.provider_calls===0 && replay.generation_id===staged.generation_id);
    checks.push('fake_stage_publish_replay');
    observations.push({case:'fake_identity',document_id:'profile-document',revision_id:replay.revision_id,
      generation_id:replay.generation_id,embedding_profile:FAKE_PROFILE.profile_id,replayed:true});
    for(const mode of ['dense','hybrid']) {
      const result=await new PostgresRetriever(reader,{mode,embedder:fake}).retrieve(request,bound());
      check(result.evidence.length===1 && result.evidence[0].text===source
        && result.evidence[0].document_id==='profile-document' && result.execution==='complete'
        && result.usage.provider_calls===1 && result.usage.cost_kind==='known' && result.usage.cost_usd===0);
      checks.push(`fake_${mode}_source`);observations.push({case:`fake_${mode}`,...evidenceObservation(result)});
    }
    const retriever=new PostgresRetriever(reader,{mode:'dense',embedder:fake});
    try {
      const negative=await retriever.retrieve(request,{...bound(),scope:parse_scope({...scope,tenant_id:'profile-other-tenant'})});
      check(negative.evidence.length===0);
    } catch(error) {check(['unsupported_capability','unauthorized_scope'].includes(error?.code));}
    checks.push('tenant_scope_negative');
    const principal=await retriever.retrieve(request,{...bound(),scope:parse_scope({...scope,principal_id:'profile-outsider',grant_ids:[]})});
    check(principal.evidence.length===0);checks.push('principal_scope_negative');
    const filtered=await retriever.retrieve(parse_request({...request,required_filters:[{op:'eq',field:'document_id',value:'absent-profile-document'}]}),bound());
    check(filtered.evidence.length===0);checks.push('required_filter_negative');
    await refusal(()=>new PostgresRetriever(reader,{mode:'dense',embedder:live}).retrieve(request,bound()),'embedding_profile_mismatch');
    check(transportCalls===0);checks.push('openai_default_refusal');
    let before=transportCalls;
    const retrieveCode=await refusal(()=>new PostgresRetriever(reader,{mode:'dense',embedder:live,embedding_profile:OPENAI_PROFILE}).retrieve(request,bound()),expected);
    check(transportCalls-before===expectedCalls);checks.push('openai_retrieval_dispatch_boundary');
    observations.push({case:'openai_retrieval',error_code:retrieveCode,transport_calls:transportCalls-before});
    before=transportCalls;
    const liveIndexer=new PostgresVectorIndexer(writer,async()=>true,live,{embedding_profile:OPENAI_PROFILE});
    const indexerCode=await refusal(()=>liveIndexer.stage(source,ingestInput(true)),expected);
    check(transportCalls-before===expectedCalls);checks.push('openai_indexer_dispatch_boundary');
    observations.push({case:'openai_indexer',error_code:indexerCode,transport_calls:transportCalls-before});
    before=transportCalls;
    const backend=new PostgresCorrectiveBackend({resource:reader,mode:'dense',embedder:live,embedding_profile:OPENAI_PROFILE});
    const options=bound(),ledger=new ExecutionLedger({limits:request.limits,deadline:options.deadline});
    const correctiveCode=await refusal(()=>backend.search(request,{...options,ledger,limit:4}),expected);
    const usage=ledger.snapshot();
    check(transportCalls-before===expectedCalls && usage.provider_calls===expectedCalls && usage.pending===0
      && usage.input_tokens===(expectedCalls?null:0) && usage.output_tokens===(expectedCalls?null:0)
      && usage.cost_usd===(expectedCalls?null:0) && usage.cost_kind===(expectedCalls?'unknown':'known'));
    checks.push('openai_corrective_accounting');
    observations.push({case:'openai_corrective',error_code:correctiveCode,transport_calls:transportCalls-before,
      provider_calls:usage.provider_calls,input_tokens:usage.input_tokens,output_tokens:usage.output_tokens,
      cost_usd:usage.cost_usd,cost_kind:usage.cost_kind});
  } finally {
    // Attempt both closes even when one fails. The parent owns fixture data cleanup.
    const closed=await Promise.allSettled([reader.close(),writer.close()]);
    check(closed.every(result=>result.status==='fulfilled') && activeLeases===0);
  }
  return {runtime:'typescript',storage:input.storage,checks,observations,cleanup_verified:true,live_inference:false};
}

async function main() {
  try {
    const chunks=[];let size=0;
    for await(const chunk of process.stdin) {
      size+=chunk.length;check(size<=1048576);chunks.push(chunk);
    }
    const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
    process.stdout.write(JSON.stringify(await run(input))+'\n');
  } catch {
    // Never expose provider, database, source, connection or credential details.
    process.stderr.write('postgres_profile_check_failed\n');process.exitCode=1;
  }
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) await main();
