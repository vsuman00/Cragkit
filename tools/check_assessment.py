"""AS-r1 shared reviewed development and synthetic failure conformance."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check():
    from cragkit.assessment import assess_evidence
    from cragkit.errors import CragkitError
    fixture = json.loads((ROOT/'contracts/fixtures/assessment.json').read_text())
    results=[]
    for case in fixture['cases']:
        try:
            result=assess_evidence(case['query'],case['evidence'],case['policy'])
            assert 'expected_error' not in case
            assert result['status']==case['expected_status'],case['id']
            assert [f['state'] for f in result['facets']]==case['expected_states'],case['id']
            assert all(set(f['evidence_ids']) <= {e['evidence_id'] for e in case['evidence']} for f in result['facets'])
            if result['status']=='sufficient':
                assert all(f['state']=='supported' for f in result['facets'] if f['required'])
            results.append(result)
        except CragkitError as error:
            assert error.code==case['expected_error'],case['id']
            results.append({'error':error.code})
    node=subprocess.run(['node','tools/check_typescript_assessment.mjs'],cwd=ROOT,
                        timeout=30,check=False,capture_output=True,text=True)
    if node.returncode or json.loads(node.stdout)!=results:
        raise ValueError('assessment_parity')
    return {'state':'passed','revision':'AS-r1','cases':len(results),'method':'reviewed-span.v1','evaluation_kind':'in_sample_lookup_and_synthetic_failures'}


def main():
    try: result=check()
    except Exception:
        print(json.dumps({'state':'failed','code':'assessment_contract_failed'}));return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
