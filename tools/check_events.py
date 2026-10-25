"""Compare bounded native event queues without exporters or raw retrieval data."""
import asyncio
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

async def check():
    from cragkit.events import EventSink
    fixture=json.loads((ROOT/'contracts/fixtures/events.json').read_text())
    results=[]
    for case in fixture['cases']:
        sink=EventSink(capacity=case['capacity']); outputs=[]
        for method,*args in case['operations']:
            try:
                if method=='emit': value=sink.emit(args[0],**args[1])
                elif method=='flush': value=await sink.flush(asyncio.get_running_loop().time()+1)
                else: value=getattr(sink,method)()
                outputs.append(value)
            except Exception as error:
                outputs.append({'error':getattr(error,'code','invalid_request')})
        results.append({'id':case['id'],'outputs':outputs,'snapshot':sink.snapshot()})
    node=subprocess.run(['node','tools/check_typescript_events.mjs'],cwd=ROOT,capture_output=True,text=True,timeout=20,check=False)
    if node.returncode or json.loads(node.stdout)!=results:raise ValueError('events_parity')
    assert results[0]['snapshot']=={'queued':1,'dropped':3,'exported':0}
    assert results[1]['outputs'][0]=={'error':'invalid_request'}
    assert results[2]['snapshot']['queued']==0 and results[3]['snapshot']['dropped']==1
    return {'state':'passed','revision':'EV-r1','cases':len(results)}

if __name__=='__main__':print(json.dumps(asyncio.run(check()),sort_keys=True))
