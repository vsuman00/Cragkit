/** Replay explicit development recordings through native adapters; never dispatch HTTP. */
import {open} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {RerankingAdapter,RerankProfileSchema} from '../packages/typescript/dist/reranking.js';
import {Cl100kCounter,render_context} from '../packages/typescript/dist/context.js';
import {pack_and_assess} from '../packages/typescript/dist/evidence.js';
import {assess_evidence} from '../packages/typescript/dist/assessment.js';
import {InvalidRequest} from '../packages/typescript/dist/errors.js';
import {deep_freeze,identity,text,valid_native_json} from '../packages/typescript/dist/shared.js';

export const PROFILE=RerankProfileSchema.parse({profile_id:'cohere_v5fast_development_v1',provider:'cohere',model:'rerank-v5.0-fast',
  model_revision:'mutable_alias:rerank-v5.0-fast',score_kind:'relevance_score',score_direction:'higher_is_better',preprocessing_revision:'utf8-development-r1',truncation_policy:'reject'});
const fields=(value,keys)=>value!==null&&typeof value==='object'&&!Array.isArray(value)
  &&[Object.prototype,null].includes(Object.getPrototypeOf(value))&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
function normalize(cases,recordings){
  if(!Array.isArray(cases)||Object.getPrototypeOf(cases)!==Array.prototype||cases.length<1||cases.length>6||Object.keys(cases).length!==cases.length||Object.getOwnPropertySymbols(cases).length)throw new InvalidRequest();
  if(Object.entries(Object.getOwnPropertyDescriptors(cases)).some(([key,field])=>key!=='length'&&(!('value'in field)||!field.enumerable||!valid_native_json(field.value))))throw new InvalidRequest();
  // Scores may be any finite raw number; inspect descriptors before reading them.
  if(!recordings||typeof recordings!=='object'||Array.isArray(recordings)||![Object.prototype,null].includes(Object.getPrototypeOf(recordings))||Object.getOwnPropertySymbols(recordings).length)throw new InvalidRequest();
  const entries=Object.getOwnPropertyDescriptors(recordings);
  if(Object.values(entries).some(field=>!('value'in field)||!field.enumerable)||Object.keys(entries).length!==cases.length)throw new InvalidRequest();
  const seen=new Set(),result=[];
  for(const item of cases){
    if(!fields(item,['question_id','query','evidence','sources','policy']))throw new InvalidRequest();
    try{identity.parse(item.question_id);text(8192).parse(item.query);}catch{throw new InvalidRequest();}
    if(seen.has(item.question_id)||!Object.hasOwn(entries,item.question_id))throw new InvalidRequest();seen.add(item.question_id);
    render_context(item.evidence);assess_evidence(item.query,item.evidence,item.policy);
    if(!Array.isArray(item.sources)||item.sources.length>64)throw new InvalidRequest();
    const raw=entries[item.question_id].value;
    if(!Array.isArray(raw)||Object.getPrototypeOf(raw)!==Array.prototype||raw.length!==item.evidence.length||raw.length>40||Object.keys(raw).length!==raw.length||Object.getOwnPropertySymbols(raw).length)throw new InvalidRequest();
    const arrayFields=Object.getOwnPropertyDescriptors(raw);
    if(Object.entries(arrayFields).some(([key,field])=>key!=='length'&&(!('value'in field)||!field.enumerable)))throw new InvalidRequest();
    const scores=[],ids=new Set(item.evidence.map(value=>value.evidence_id));
    for(const field of Object.entries(arrayFields).filter(([key])=>key!=='length').map(([,field])=>field)){
      const score=field.value;
      if(!fields(score,['candidate_id','raw_score'])||Object.getOwnPropertySymbols(score).length)throw new InvalidRequest();
      const descriptors=Object.getOwnPropertyDescriptors(score);
      if(Object.values(descriptors).some(value=>!('value'in value)||!value.enumerable))throw new InvalidRequest();
      if(typeof score.candidate_id!=='string'||!ids.delete(score.candidate_id)||typeof score.raw_score!=='number'||!Number.isFinite(score.raw_score))throw new InvalidRequest();
      scores.push({candidate_id:score.candidate_id,raw_score:score.raw_score});
    }
    if(ids.size)throw new InvalidRequest();
    result.push({item:structuredClone(item),scores});
  }
  return result;
}

export async function replay(cases,recordings){
  let normalized;try{normalized=normalize(cases,recordings);}catch{throw new InvalidRequest();}
  const counter=await Cl100kCounter.create(new URL('../artifacts/tokenizers/cl100k_base.tiktoken',import.meta.url));
  try{
    const results=[];
    for(const {item,scores}of normalized){
      const deadline=performance.now()/1000+30;
      const options={deadline,max_tokens:20000,reserve:256,surrounding_bytes:256,rebalance:true,counting_mode:'strict',counter,policy:item.policy};
      const before=await pack_and_assess(item.query,item.evidence,item.sources,options);
      const adapter=new RerankingAdapter(async()=>new TextEncoder().encode(JSON.stringify(scores)),{profile:PROFILE,allow_live:true});
      const ranked=await adapter.rank(item.query,item.evidence.map(value=>({candidate_id:value.evidence_id,text:value.text})),{deadline,max_provider_calls:1,allow_fallback:false});
      const mapping=new Map(item.evidence.map(value=>[value.evidence_id,value]));
      const after=await pack_and_assess(item.query,ranked.order.map(id=>mapping.get(id)),item.sources,options);
      results.push({question_id:item.question_id,before,after,order:ranked.order,scores:ranked.scores});
    }
    return deep_freeze(results);
  }finally{counter.close();}
}

async function main(){
  if(process.argv.length!==4||process.argv[2]!=='--replay')throw new InvalidRequest();
  const file=await open(process.argv[3],'r');let payload;
  try{
    const info=await file.stat();if(!info.isFile()||info.size>16777216)throw new InvalidRequest();
    const buffer=Buffer.alloc(16777217);let size=0;
    while(size<buffer.length){const {bytesRead}=await file.read(buffer,size,buffer.length-size,size);if(!bytesRead)break;size+=bytesRead;}
    if(size>16777216)throw new InvalidRequest();
    payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,size)));
  }finally{await file.close();}
  if(!fields(payload,['cases','recordings']))throw new InvalidRequest();
  console.log(JSON.stringify(await replay(payload.cases,payload.recordings)));
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  main().catch(()=>{console.error(JSON.stringify({state:'failed',code:'calibration_replay_failed'}));process.exitCode=1;});
}
