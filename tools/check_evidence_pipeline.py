"""EP-r1 exact emitted coverage and bounded rebalance parity."""
import asyncio
import json
from pathlib import Path
import subprocess
import time
ROOT=Path(__file__).resolve().parents[1]


async def check():
    from cragkit.evidence import pack_and_assess
    from cragkit.errors import CragkitError
    fixture=json.loads((ROOT/'contracts/fixtures/evidence-pipeline.json').read_text())
    results=[]
    for case in fixture['cases']:
        try:
            result=await pack_and_assess(case['query'],case['evidence'],case['sources'],policy=case['policy'],deadline=time.monotonic()+10,**case['options'])
            assert 'expected_error' not in case
            assert result['status']==case['expected_status'],case['id']
            assert [f['state'] for f in result['facets']]==case['expected_states'],case['id']
            assert result['rebalance_count']==case['expected_rebalance_count'],case['id']
            assert result['rebalance_count']<=1 and result['total_tokens']<=case['options']['max_tokens']
            assert json.loads(result['context'])==result['evidence']
            ids={e['evidence_id'] for e in result['evidence']}
            assert all(set(f['evidence_ids'])<=ids for f in result['facets'])
            results.append(result)
        except CragkitError as error:
            assert error.code==case['expected_error'],case['id'];results.append({'error':error.code})
    node=subprocess.run(['node','tools/check_typescript_evidence_pipeline.mjs'],cwd=ROOT,timeout=30,check=False,capture_output=True,text=True)
    if node.returncode or json.loads(node.stdout)!=results:raise ValueError('evidence_pipeline_parity')
    return dict(state='passed',revision='EP-r1',cases=len(results))


def main():
    try:result=asyncio.run(check())
    except Exception:
        print(json.dumps(dict(state='failed',code='evidence_pipeline_contract_failed')));return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
