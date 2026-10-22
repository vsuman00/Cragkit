"""Compare normalized Python/Node embedding results on synthetic E-r1 fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from check_contracts import run_runtime

ROOT = Path(__file__).resolve().parents[1]

PYTHON_RUNNER = r'''
import asyncio,json,sys,time
from cragkit.embeddings import EmbeddingAdapter,EmbeddingLimits,EmbeddingPolicy,FAKE_PROFILE,OPENAI_PROFILE
from cragkit.errors import CragkitError
async def main():
 records=[]
 for case in json.load(sys.stdin)['cases']:
  profile=FAKE_PROFILE if case['profile']=='fake' else OPENAI_PROFILE
  calls=0
  class Counter:
   name=case.get('counter_name',profile.tokenizer)
   def count(self,text):return case.get('tokens',len(text.encode('utf-8')))
  async def transport(body,*,deadline,max_response_bytes):
   nonlocal calls
   calls+=1
   payload=json.loads(body)
   assert payload=={'model':profile.model,'dimensions':1536,'encoding_format':'float','input':case['inputs']}
   if case.get('transport_error'):raise RuntimeError('synthetic transport failure')
   return bytes.fromhex(case['response_hex']) if 'response_hex' in case else case['response'].encode('utf-8')
  try:
   adapter=EmbeddingAdapter(transport,Counter(),profile=profile,limits=EmbeddingLimits(**case.get('limits',{})),policy=EmbeddingPolicy(**case.get('policy',{})))
   if case.get('operation')=='query':value=await adapter.embed_query(case['inputs'][0],deadline=time.monotonic()+5)
   else:value=await adapter.embed_batch(case['inputs'],deadline=time.monotonic()+5)
   record={'id':case['id'],'value':value.model_dump(mode='json')}
  except CragkitError as error:record={'id':case['id'],'error':error.to_dict()}
  record['calls']=calls;records.append(record)
 json.dump(records,sys.stdout,allow_nan=False)
asyncio.run(main())
'''


def main() -> None:
    path = ROOT / 'contracts/fixtures/embeddings.json'
    fixture = path.read_text()
    cases = json.loads(fixture)['cases']
    entry = (ROOT / 'packages/typescript/dist/embeddings.js').as_uri()
    node_runner = '''
import fs from 'node:fs';
import {EmbeddingAdapter,FAKE_PROFILE,OPENAI_PROFILE} from ENTRY;
const records=[];
for(const item of JSON.parse(fs.readFileSync(0,'utf8')).cases){
 const profile=item.profile==='fake'?FAKE_PROFILE:OPENAI_PROFILE;let calls=0;
 const counter={name:Object.hasOwn(item,'counter_name')?item.counter_name:profile.tokenizer,count:text=>Object.hasOwn(item,'tokens')?item.tokens:Buffer.byteLength(text,'utf8')};
 const transport=async(body,options)=>{
  calls++;const actual=JSON.parse(new TextDecoder().decode(body));
  if(JSON.stringify(actual)!==JSON.stringify({model:profile.model,dimensions:1536,encoding_format:'float',input:item.inputs}))throw Error('fixture request mismatch');
  if(item.transport_error)throw Error('synthetic transport failure');
  return item.response_hex?Buffer.from(item.response_hex,'hex'):Buffer.from(item.response,'utf8');
 };
 let record;
 try{
  const adapter=new EmbeddingAdapter(transport,counter,{profile,limits:item.limits,policy:item.policy});
  const options={deadline:performance.now()/1000+5};
  const value=item.operation==='query'?await adapter.embed_query(item.inputs[0],options):await adapter.embed_batch(item.inputs,options);
  record={id:item.id,value};
 }catch(error){if(typeof error.to_dict!=='function')throw error;record={id:item.id,error:error.to_dict()};}
 record.calls=calls;records.push(record);
}
process.stdout.write(JSON.stringify(records));
'''.replace('ENTRY', json.dumps(entry))
    python = run_runtime([sys.executable, '-c', PYTHON_RUNNER], fixture)
    node = run_runtime(['node', '--input-type=module', '-e', node_runner], fixture)
    if len(python) != len(cases) or len(node) != len(cases):
        raise SystemExit('Embedding fixture outcomes omitted')
    for case, first, second in zip(cases, python, node, strict=True):
        if first != second:
            raise SystemExit(f"Embedding native parity mismatch: {case['id']}")
        if first['id'] != case['id'] or first['calls'] != case['expected_calls']:
            raise SystemExit(f"Embedding dispatch mismatch: {case['id']}")
        if 'expected_error' in case:
            if first.get('error', {}).get('code') != case['expected_error']:
                raise SystemExit(f"Embedding error mismatch: {case['id']}")
        elif first.get('value') != case['expected']:
            raise SystemExit(f"Embedding normalized value mismatch: {case['id']}")
    print(json.dumps({'state':'passed','cases':len(cases),'fixture_sha256':hashlib.sha256(fixture.encode()).hexdigest(),'evidence_kind':'synthetic_only'}))


if __name__ == '__main__':
    main()
