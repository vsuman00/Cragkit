import fs from 'node:fs';
import {pack_and_assess} from '../packages/typescript/dist/evidence.js';
const fixture=JSON.parse(fs.readFileSync('contracts/fixtures/evidence-pipeline.json','utf8')),results=[];
for(const item of fixture.cases){
 try{results.push(await pack_and_assess(item.query,item.evidence,item.sources,{...item.options,policy:item.policy,deadline:performance.now()/1000+10}));}
 catch(error){if(error.code!==item.expected_error)throw error;results.push({error:error.code});}
}
console.log(JSON.stringify(results));
