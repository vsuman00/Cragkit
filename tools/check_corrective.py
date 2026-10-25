"""CR-r1 deterministic full-loop parity; injected fakes, no database or models."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import argparse
ROOT=Path(__file__).resolve().parents[1]

async def check(*, show_results=False):
    from cragkit.corrective import CorrectiveRetriever
    from cragkit.planning import PlannerAdapter
    from cragkit.errors import CragkitError, ProviderUnavailable, UnauthorizedScope
    fixture=json.loads((ROOT/'contracts/fixtures/corrective.json').read_text());outputs=[]
    for case in fixture['cases']:
        rows=fixture['rows'];revoked=set();calls=[]
        class Backend:
            async def search(self, request, *, scope, deadline, limit, ledger):
                assert request.required_filters==original.required_filters and scope.tenant_id=='t'
                entry=case['searches'][min(len(calls),len(case['searches'])-1)];calls.append(request.query)
                if entry.get('reserve_call'):
                    token=ledger.reserve(provider_calls=1,cost_upper_usd=0);ledger.dispatch(token)
                    if entry.get('failure'):ledger.abandon(token)
                    else:ledger.reconcile(token,input_tokens=0,output_tokens=0,cost_usd=0)
                if entry.get('failure'):raise {'provider_unavailable':ProviderUnavailable,'unauthorized_scope':UnauthorizedScope}[entry['failure']]()
                return dict(candidates=[deepcopy(rows[k]['candidate']) for k in entry['ids']],degraded=False)
            async def capture(self,candidates,*,request,scope,deadline,max_source_bytes,ledger):
                if len(calls)>1:revoked.update(case.get('revoke_after_search',[]))
                keys=[c.document_id for c in candidates if c.document_id not in revoked]
                size=sum(len(rows[k]['source']['text'].encode()) for k in keys)
                exhausted=size>max_source_bytes
                if exhausted:keys=[];size=0
                return dict(evidence=[deepcopy(rows[k]['evidence']) for k in keys],sources=[deepcopy(rows[k]['source']) for k in keys],source_bytes=size,stale=bool(revoked),budget_exhausted=exhausted)
        async def plan(payload,*,deadline):
            revoked.update(case.get('revoke_on_plan',[]))
            if case['planner']=='fallback':raise ProviderUnavailable()
            selected=[] if case['planner']=='empty' else [dict(facet_id=v['facet_id'],variant_id=v['variant_id']) for v in payload['variants'] if v['facet_id'] in payload['missing_facets']]
            return dict(plan=dict(queries=selected),usage=dict(input_tokens=1,output_tokens=1,cost_usd=0))
        from cragkit.contracts import parse_request
        raw=deepcopy(fixture['request']);raw['limits']=case['limits'];original=parse_request(raw)
        planner=None if case['planner']=='none' else PlannerAdapter(plan,allow_fallback=case['planner']=='fallback',cost_upper_usd=0)
        variants=[dict(facet_id='second',variant_id='v'+str(i),query=query) for i,query in enumerate(case['queries'])]
        try:
            result=await CorrectiveRetriever(Backend(),policy=None if case.get('policy_none') else fixture['policy'],variants=variants,planner=planner,batch_size=2,**case['options']).retrieve(original,scope=fixture['scope'],deadline=asyncio.get_running_loop().time()+10)
            assert 'expected_error' not in case and result['result']['status']==case['expected_status'],case['id']
            outputs.append(result)
        except CragkitError as error:
            assert error.code==case.get('expected_error'),case['id'];outputs.append(dict(error=error.code))
    node=subprocess.run(['node','tools/check_typescript_corrective.mjs'],cwd=ROOT,capture_output=True,text=True,timeout=30,check=False)
    if node.returncode or json.loads(node.stdout)!=outputs:
        Path(ROOT/'artifacts/V4/corrective-python.json').write_text(json.dumps(outputs,indent=2))
        Path(ROOT/'artifacts/V4/corrective-node.json').write_text(node.stdout)
        raise ValueError('corrective_parity')
    summary = dict(state='passed',revision='CR-r1',cases=len(outputs))
    if show_results:
        summary['demonstration'] = [dict(id=case['id'], **output) for case,output in zip(fixture['cases'],outputs)]
    return summary
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--show-results',action='store_true')
    print(json.dumps(asyncio.run(check(show_results=parser.parse_args().show_results)),sort_keys=True))
