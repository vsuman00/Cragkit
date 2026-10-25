import {readFileSync} from 'node:fs';
import {validate_plan} from '../packages/typescript/dist/planning.js';
const fixture=JSON.parse(readFileSync(new URL('../contracts/fixtures/planning.json',import.meta.url),'utf8'));
process.stdout.write(JSON.stringify(fixture.cases.map(example=>{
 try{return {queries:validate_plan(example.value,example.config)};}
 catch(error){return {error:error.code??error.name};}
})));
