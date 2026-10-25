import {readFileSync} from 'node:fs';
import {EventSink} from '../packages/typescript/dist/events.js';
const fixture=JSON.parse(readFileSync(new URL('../contracts/fixtures/events.json',import.meta.url),'utf8'));
const results=[];
for(const example of fixture.cases){
 const sink=new EventSink({capacity:example.capacity}),outputs=[];
 for(const [method,...args] of example.operations){
  try{
   const value=method==='emit'?sink.emit(args[0],args[1]):method==='flush'?await sink.flush({deadline:performance.now()/1000+1}):sink[method]();
   outputs.push(value??null);
  }catch(error){outputs.push({error:error.code??'invalid_request'});}
 }
 results.push({id:example.id,outputs,snapshot:sink.snapshot()});
}
process.stdout.write(JSON.stringify(results));
