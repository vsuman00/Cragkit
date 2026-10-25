import fs from 'node:fs';
import {Cl100kCounter,count_context} from '../packages/typescript/dist/context.js';
const fixture=JSON.parse(fs.readFileSync('contracts/fixtures/context.json','utf8'));
const counter=await Cl100kCounter.create('artifacts/tokenizers/cl100k_base.tiktoken'), results=[];
for(const item of fixture.cases){
  try{results.push(count_context(item.evidence,{max_tokens:item.max_tokens,reserve:item.reserve,counting_mode:item.counting_mode,...(item.counting_mode==='strict'?{counter}:{})}));}
  catch(error){if(error.code!==item.expected_error)throw error;results.push({error:error.code});}
}
const token_counts=fixture.token_cases.map(item=>({id:item.id,tokens:counter.count(item.text)}));
counter.close();
console.log(JSON.stringify({cases:results,token_counts}));
