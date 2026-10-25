/** Show partial reviewed coverage and an exact one-token evidence budget. */
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import {relative,isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Cl100kCounter} from 'cragkit/context';
import {pack_and_assess} from 'cragkit/evidence';
const digest=text=>createHash('sha256').update(text).digest('hex');
const anchor=(document,text)=>({claim_id:'reviewed',collection:'public-example',document_id:document,revision_id:'r1',source_sha256:digest(text),start_byte:0,end_byte:Buffer.byteLength(text),text});

export async function demo(tokenizer){
  const query='What are the retry limit and delay?';
  const retry=anchor('retry','Retry at most three times.'),delay=anchor('delay','Wait ten seconds.');
  const evidence={evidence_id:'retry',collection:retry.collection,document_id:retry.document_id,revision_id:'r1',chunk_id:'retry',source_locator:'synthetic:example',start_byte:0,end_byte:retry.end_byte,text:retry.text,source_sha256:retry.source_sha256,text_sha256:digest(retry.text)};
  const source=Object.fromEntries(['collection','document_id','revision_id','source_sha256','text'].map(key=>[key,retry[key]]));
  const policy={policy_id:'public-example',version:'1',query_sha256:digest(query),facets:[
    {facet_id:'retry',question:'Retry limit?',required:true,absence:'missing',anchors:[retry]},
    {facet_id:'delay',question:'Retry delay?',required:true,absence:'missing',anchors:[delay]},
  ]};
  const counter=await Cl100kCounter.create(tokenizer);
  try{
    const common={counter,counting_mode:'strict',policy,surrounding_bytes:0};
    const partial=await pack_and_assess(query,[evidence],[source],{...common,deadline:performance.now()/1000+5,max_tokens:20000,reserve:256});
    const strict_budget=await pack_and_assess(query,[evidence],[source],{...common,deadline:performance.now()/1000+5,max_tokens:1,reserve:0});
    if(partial.status!=='partial'||partial.facets.map(facet=>facet.state).join(',')!=='supported,missing'||strict_budget.status!=='insufficient'||strict_budget.context!=='[]'||strict_budget.context_tokens!==1)throw new Error('example_contract_failed');
    return {partial,strict_budget};
  }finally{counter.close();}
}

async function main(){
  const args=process.argv.slice(2),options={};
  for(let index=0;index<args.length;index+=2){if(!['--tokenizer','--prefix'].includes(args[index])||!args[index+1]||Object.hasOwn(options,args[index]))throw new Error('invalid_options');options[args[index]]=args[index+1];}
  if(!options['--tokenizer'])throw new Error('tokenizer_required');
  if(options['--prefix']){
    const prefix=fs.realpathSync(options['--prefix']);
    for(const specifier of ['cragkit','cragkit/context','cragkit/evidence']){const path=fs.realpathSync(fileURLToPath(import.meta.resolve(specifier))),part=relative(prefix,path);if(isAbsolute(part)||part==='..'||part.startsWith('../'))throw new Error('installed_prefix_mismatch');}
  }
  console.log(JSON.stringify(await demo(options['--tokenizer'])));
}
if(process.argv[1]&&fs.realpathSync(process.argv[1])===fs.realpathSync(fileURLToPath(import.meta.url)))await main();
