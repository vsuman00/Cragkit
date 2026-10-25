/** Repository example: inject an initialized store, trusted transport and tokenizer.
 * No endpoint, credential or live provider is discovered. Source release remains
 * a separate V5-03 gate. Installed applications use the matching cragkit subpaths.
 */
import {parse_request,parse_scope} from '../packages/typescript/dist/requests.js';
import {EmbeddingAdapter,EmbeddingProfileSchema} from '../packages/typescript/dist/embeddings.js';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
import {DeadlineExceeded,InvalidRequest} from '../packages/typescript/dist/errors.js';
import {bind_embedding_batch,compile_filter} from '../packages/typescript/dist/qdrant.js';

export async function retrieve_candidates(store,input,{scope,transport,token_counter,ledger,deadline,limit=2,policy,signal}={}){
  const entered=performance.now()/1000;
  const request=parse_request(input),trusted=parse_scope(scope);
  compile_filter(request,trusted);
  if(!(ledger instanceof ExecutionLedger)||!Number.isFinite(deadline)||Math.abs(deadline)>Number.MAX_SAFE_INTEGER||!Number.isInteger(limit)||limit<1||limit>Math.min(64,request.limits.max_candidates)||(signal!==undefined&&!(signal instanceof AbortSignal)))throw new InvalidRequest();
  const end=Math.min(deadline,ledger.deadline,entered+request.limits.deadline_ms/1000);
  if(signal?.aborted){const error=new Error('Operation aborted.');error.name='AbortError';throw error;}
  if(end<=performance.now()/1000)throw new DeadlineExceeded();
  const profile=EmbeddingProfileSchema.parse(store.config.dense_profile);
  if(typeof transport!=='function')throw new InvalidRequest();
  let token,adapter,admission_error;
  const accounted_transport=async(body,options)=>{
    // E-r1 admission has completed; no provider slot is charged for preflight denial.
    try{
      token=ledger.reserve({provider_calls:1,cost_upper_usd:profile.provider==='fake'?0:adapter.policy.max_cost_usd});
      ledger.dispatch(token);
    }catch(error){admission_error=error;throw error;}
    return transport(body,options);
  };
  adapter=new EmbeddingAdapter(accounted_transport,token_counter,{profile,limits:{max_items:1},policy});
  let batch;
  try{
    batch=bind_embedding_batch(await adapter.embed_query(request.query,{deadline:end,signal}),profile,{expected_items:1});
    if(token===undefined)throw new InvalidRequest();
    const usage=batch.usage;
    ledger.reconcile(token,{input_tokens:usage.prompt_tokens,output_tokens:usage.total_tokens!==null&&usage.prompt_tokens!==null?usage.total_tokens-usage.prompt_tokens:null,cost_usd:usage.cost_kind==='known'?usage.cost_usd:null});
    token=undefined;
  }catch(error){if(admission_error!==undefined)throw admission_error;throw error;}
  finally{if(token!==undefined)ledger.abandon(token);}
  const nominations=await store.search_candidates(request,{scope:trusted,dense:batch,branch_limits:{dense:limit},ledger,deadline:end,signal});
  return {nominations,embedding_usage:batch.usage,ledger:ledger.snapshot()};
}
