/** HY-r1 public boundary probe with fake store/provider, no database. */
import {EmbeddingAdapter,FAKE_PROFILE} from '../packages/typescript/dist/embeddings.js';
import {PostgresRetriever} from '../packages/typescript/dist/retrieval.js';
import {PostgresSession} from '../packages/typescript/dist/postgres-session.js';
import {parse_request,parse_scope} from '../packages/typescript/dist/contracts.js';
import {ProviderUnavailable} from '../packages/typescript/dist/errors.js';
import {now} from '../packages/typescript/dist/postgres-pool.js';
import {encode} from '../evaluation/runners/synthetic-vectors.mjs';
let input='';for await(const part of process.stdin)input+=part;
const fixture=JSON.parse(input),results=[];
const original=PostgresSession.prototype.transaction;
try{
  for(const entry of fixture.cases){
    const calls=[];
    const embedder=new EmbeddingAdapter(async body=>{
      calls.push(['embedding']);if(entry.fail_embedding)throw Error('synthetic failure');
      const value=JSON.parse(Buffer.from(body).toString('utf8'));
      const count=value.input.reduce((sum,text)=>sum+Buffer.byteLength(text),0);
      return Buffer.from(JSON.stringify({model:FAKE_PROFILE.model,data:value.input.map((text,index)=>({index,embedding:encode(text)})),usage:{prompt_tokens:count,total_tokens:count}}));
    },{name:'fake-byte-v1',count:text=>Buffer.byteLength(text)});
    PostgresSession.prototype.transaction=async function(request,options,body){
      calls.push(['transaction',request.required_filters]);
      const run=(family,limit)=>{calls.push([family,limit]);if(entry.fail_family===family)throw new ProviderUnavailable();return [];};
      return body({candidate_branch:operation=>operation(),dense_candidates:async(batch,options)=>run('dense',options.limit),
        lexical_candidates:async options=>run('lexical',options.limit),identifier_candidates:async(token,options)=>run('identifier',options.limit)});
    };
    try{
      const result=structuredClone(await new PostgresRetriever({},{mode:entry.mode,embedder,allow_degraded:entry.allow_degraded??false}).retrieve(
        parse_request({request_id:'hybrid-parity',query:'ERR_CONN-42',collection:'manuals',required_filters:[{field:'document_id',op:'eq',value:'wanted'}],limits:{max_candidates:entry.max_candidates,max_provider_calls:entry.max_provider_calls??16}}),
        {scope:parse_scope({tenant_id:'tenant',principal_id:'person',authorization_revision:'auth'}),deadline:now()+2}));
      for(const stage of result.usage.stage_durations)stage.duration_ms=0;
      results.push({result,calls});
    }catch(error){results.push({error:error.code??'unexpected_error',calls});}
  }
  console.log(JSON.stringify({cases:results,vectors:fixture.texts.map(encode)}));
}finally{PostgresSession.prototype.transaction=original;}
