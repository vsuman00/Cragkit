/** Read private fixture configuration from stdin; never emit credentials or raw failures. */
import { readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { FetchQdrantTransport, QdrantSearchStore } from '../packages/typescript/dist/qdrant.js';
import { ExecutionLedger } from '../packages/typescript/dist/execution.js';
import {retrieve_candidates} from '../examples/qdrant_dense.mjs';

try {
  const input=readFileSync(0);
  if(input.byteLength>262144)throw new Error();
  const value=JSON.parse(input.toString('utf8'));
  const transport=new FetchQdrantTransport(value.endpoint,{api_key:value.api_key,allow_loopback_http:true});
  const store=new QdrantSearchStore(value.config,transport);
  const output=[],dense_only=value.dense_only===true;
  const token_counter={name:'fake-byte-v1',count:text=>Buffer.byteLength(text)};
  const fake_embedding=async body=>{
    const request=JSON.parse(Buffer.from(body)),tokens=Buffer.byteLength(request.input[0]);
    return Buffer.from(JSON.stringify({model:request.model,data:[{index:0,embedding:value.dense}],usage:{prompt_tokens:tokens,total_tokens:tokens}}));
  };
  try{
    await store.initialize({deadline:performance.now()/1000+5});
    for(const sample of value.cases){
      const deadline=performance.now()/1000+5;
      const filters=[{op:'eq',field:'document_id',value:sample.document}];
      if(Object.hasOwn(sample,'tag'))filters.push({op:'eq',field:'tag',value:sample.tag});
      const request={request_id:'native-'+sample.id,query:'synthetic fixture query',collection:'docs',required_filters:filters,limits:{max_candidates:4,max_provider_calls:dense_only?1:0}};
      const scope={...value.scope,...(sample.empty_grants?{grant_ids:[]}: {})};
      const ledger=new ExecutionLedger({limits:request.limits,deadline});
      let record;
      try{
        const nominations=dense_only?(await retrieve_candidates(store,request,{scope,transport:fake_embedding,token_counter,ledger,deadline})).nominations:await store.search_candidates(request,{scope,dense:value.dense,sparse:value.sparse,branch_limits:{dense:2,sparse:2},ledger,deadline});
        if(sample.error||nominations.length!==sample.count)throw new Error();
        record={id:sample.id,nominations};
      }catch(error){
        if(error?.code!==sample.error||!sample.error)throw new Error();
        record={id:sample.id,error:error.code};
      }
      const snapshot=ledger.snapshot();
      if(snapshot.provider_calls!==(dense_only?1:0)||snapshot.pending!==0||snapshot.candidates!==(dense_only?2:4))throw new Error();
      output.push({...record,ledger:snapshot});
    }
  }finally{await store.close();await transport.close();}
  console.log(JSON.stringify(output));
}catch{console.error('Node Qdrant native acceptance failed; private inputs suppressed.');process.exitCode=1;}
