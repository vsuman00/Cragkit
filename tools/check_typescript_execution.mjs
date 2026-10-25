import {readFileSync} from 'node:fs';
import {ExecutionLedger} from '../packages/typescript/dist/execution.js';
const fixture=JSON.parse(readFileSync(new URL('../contracts/fixtures/execution.json',import.meta.url),'utf8'));
const results=[];
for(const example of fixture.cases){
 const ledger=new ExecutionLedger({limits:example.limits,deadline:performance.now()/1000+10}),tokens={},errors=[];
 for(const [method,name,args] of example.operations){
  try{
   if(method==='reserve')tokens[name]=ledger.reserve(args);
   else if(method==='reconcile')ledger.reconcile(tokens[name],args);
   else ledger[method](tokens[name]);
  }catch(error){errors.push(error.code??error.name);}
 }
 results.push({id:example.id,errors,snapshot:ledger.snapshot()});
}
process.stdout.write(JSON.stringify(results));
