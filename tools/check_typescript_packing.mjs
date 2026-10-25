import fs from 'node:fs';
import {Cl100kCounter} from '../packages/typescript/dist/context.js';
import {pack_evidence} from '../packages/typescript/dist/packing.js';
const fixture=JSON.parse(fs.readFileSync('contracts/fixtures/packing.json','utf8'));
const counter=await Cl100kCounter.create('artifacts/tokenizers/cl100k_base.tiktoken');
const results=[];
try {
  for(const item of fixture.cases){
    try {results.push(await pack_evidence(item.evidence,item.sources,{...item.options,deadline:performance.now()/1000+10,...(item.options.counting_mode==='strict'?{counter}:{})}));}
    catch(error){if(error.code!==item.expected_error)throw error;results.push({error:error.code});}
  }
} finally {counter.close();}
console.log(JSON.stringify(results));
