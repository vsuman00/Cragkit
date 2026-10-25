"""Compare actual native EL-r1 transitions on deterministic fake work."""
import asyncio
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

async def check():
    from cragkit.execution import ExecutionLedger
    fixture = json.loads((ROOT/'contracts/fixtures/execution.json').read_text())
    results=[]
    for case in fixture['cases']:
        ledger=ExecutionLedger(case['limits'],deadline=asyncio.get_running_loop().time()+10)
        tokens={}; errors=[]
        for op in case['operations']:
            try:
                method,name,*args=op
                if method=='reserve': tokens[name]=ledger.reserve(**args[0])
                elif method=='reconcile': ledger.reconcile(tokens[name],**args[0])
                else: getattr(ledger,method)(tokens[name])
            except Exception as error: errors.append(getattr(error,'code',type(error).__name__))
        results.append(dict(id=case['id'],errors=errors,snapshot=ledger.snapshot()))
    node=subprocess.run(['node','tools/check_typescript_execution.mjs'],cwd=ROOT,capture_output=True,text=True,timeout=20,check=False)
    if node.returncode or json.loads(node.stdout)!=results:raise ValueError('execution_parity')
    assert results[0]['snapshot']['provider_calls']==1 and results[0]['snapshot']['input_tokens']==3
    assert results[1]['snapshot']['provider_calls']==0
    assert results[2]['snapshot']['cost_kind']=='unknown'
    assert results[3]['errors']==['BudgetExhausted']
    assert results[4]['errors']==['unsupported_capability']
    assert results[5]['errors']==['BudgetExhausted']
    assert results[6]['errors']==['integrity_violation','integrity_violation']
    assert results[7]['errors']==['BudgetExhausted']
    assert results[8]['snapshot']['input_tokens'] is None
    return dict(state='passed',revision='EL-r1',cases=len(results))

if __name__=='__main__':print(json.dumps(asyncio.run(check()),sort_keys=True))
