import fs from 'node:fs';
import {assess_evidence} from '../packages/typescript/dist/assessment.js';
const fixture=JSON.parse(fs.readFileSync('contracts/fixtures/assessment.json','utf8')),results=[];
for(const item of fixture.cases){
  try{results.push(assess_evidence(item.query,item.evidence,item.policy));}
  catch(error){if(error.code!==item.expected_error)throw error;results.push({error:error.code});}
}
console.log(JSON.stringify(results));
