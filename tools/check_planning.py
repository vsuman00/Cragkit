"""QP-r1 trusted-selection validation parity, without provider calls."""
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]

def check():
    from cragkit.planning import validate_plan
    from cragkit.errors import InvalidRequest
    fixture=json.loads((ROOT/'contracts/fixtures/planning.json').read_text());results=[]
    for case in fixture['cases']:
        try:
            result=validate_plan(case['value'],**case['config'])
            assert case['valid'],case['id'];results.append({'queries':result})
        except InvalidRequest:
            assert not case['valid'],case['id'];results.append({'error':'invalid_request'})
    node=subprocess.run(['node','tools/check_typescript_planning.mjs'],cwd=ROOT,capture_output=True,text=True,timeout=20,check=False)
    assert node.returncode==0 and json.loads(node.stdout)==results,'planning_parity'
    return dict(state='passed',revision='QP-r1',cases=len(results))
if __name__=='__main__':print(json.dumps(check(),sort_keys=True))
