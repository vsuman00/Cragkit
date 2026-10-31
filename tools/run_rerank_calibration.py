"""Explicit bounded public-development Cohere run; never used by routine tests."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'evaluation/runners'))


def private_write(path, value):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as stream:json.dump(value,stream,ensure_ascii=True,allow_nan=False)


def validate_payload(value):
    body=json.dumps(value,ensure_ascii=True,allow_nan=False).encode()
    if (len(body)>65536 or set(value)!={'model','query','documents','top_n','max_tokens_per_doc'}
            or value['model']!='rerank-v5.0-fast' or type(value['documents']) is not list or not 1<=len(value['documents'])<=2
            or type(value['top_n']) is not int or value['top_n']!=len(value['documents']) or value['max_tokens_per_doc']!=4096
            or type(value['query']) is not str or len(value['query'].encode())>8192
            or any(type(text) is not str or not text or len(text.encode())>16384 for text in value['documents'])):
        raise ValueError()
    return body


def dispatch(request_path, response_path):
    from check_cohere_reranking import read_key, request, ProbeFailure
    observation={'provider_calls':0}
    outcome=dict(state='failed',code='dispatch_failed',observation=observation)
    try:
        with Path(request_path).open('rb') as stream:body=stream.read(65537)
        if len(body)>65536:raise ValueError()
        body=validate_payload(json.loads(body))
        raw=request(body,read_key(),10,observation)
        outcome.update(state='passed',code='ok',raw=raw.decode('utf-8'))
    except ProbeFailure as error:
        outcome['code']=error.code
    except Exception:
        pass
    finally:
        private_write(Path(response_path),outcome)
    return outcome['state']=='passed'


def normalize(raw, candidates):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError()
            result[key]=value
        return result
    def constant(value):raise ValueError()
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    rows=value['results']
    if type(rows) is not list or len(rows)!=len(candidates):raise ValueError()
    scores={}
    for row in rows:
        index,score=row['index'],row['relevance_score']
        if (type(index) is not int or not 0<=index<len(candidates) or index in scores
                or type(score) not in (int,float) or not math.isfinite(score)):raise ValueError()
        scores[index]=score
    billed=value.get('meta',{}).get('billed_units',{}).get('input_tokens')
    if billed is not None and (type(billed) is not int or billed<0):raise ValueError()
    return [dict(candidate_id=item['evidence_id'],raw_score=scores[i]) for i,item in enumerate(candidates)],billed


async def run(baseline_path, output_path):
    from rerank_calibration import prepare,replay,evaluate
    baseline_bytes=baseline_path.read_bytes()
    baseline=json.loads(baseline_bytes.decode().splitlines()[-1])
    prepared=prepare(baseline)
    cases=prepared['cases']
    limits=json.loads((ROOT/'evaluation/policies/V3-reviewed-span-v1.json').read_text())['live_limits']
    if (len(cases)!=6 or any(len(case['evidence'])>2 for case in cases)
            or limits['max_calls']!=6 or limits['max_documents']!=12 or limits['budget_usd']!=0.01
            or limits['admission_tokens_per_document']!=32768 or limits['dated_usd_per_million_tokens']!=0.02):raise ValueError()
    documents=sum(len(case['evidence']) for case in cases)
    calls=sum(bool(case['evidence']) for case in cases)
    admission=documents*limits['admission_tokens_per_document']*limits['dated_usd_per_million_tokens']/1e6
    if calls>limits['max_calls'] or documents>limits['max_documents'] or admission>limits['budget_usd']:raise ValueError()
    payloads={case['question_id']:dict(model='rerank-v5.0-fast',query=case['query'],documents=[e['text'] for e in case['evidence']],
              top_n=len(case['evidence']),max_tokens_per_doc=4096) for case in cases if case['evidence']}
    for payload in payloads.values():validate_payload(payload)
    # Exercise both optional tokenizers and complete replay before spending.
    synthetic={case['question_id']:[dict(candidate_id=e['evidence_id'],raw_score=len(case['evidence'])-i)
               for i,e in enumerate(case['evidence'])] for case in cases}
    preflight_results=await replay(cases,synthetic)
    await node_parity(cases,synthetic,preflight_results)
    # Freeze every public input before reading the key or dispatching the first call.
    inputs=[dict(question_id=case['question_id'],query_sha256=sha256(case['query'].encode()).hexdigest(),
        evidence_sha256=[item['text_sha256'] for item in case['evidence']]) for case in cases]
    report=dict(state='in_progress',protocol_sha256=prepared['protocol_sha256'],
        baseline_sha256=sha256(baseline_bytes).hexdigest(),inputs=inputs,
        admission_estimate_usd=admission,budget_usd=limits['budget_usd'],provider_calls=0,dispatch_attempts=0,
        model='rerank-v5.0-fast',model_revision='mutable_alias:rerank-v5.0-fast',
        actual_billing='unknown',provider_truncation='independently_unknown',attempts=[])
    recordings={}
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-v3-calibration-') as directory:
            work=Path(directory)
            for index,case in enumerate(cases):
                if not case['evidence']:
                    recordings[case['question_id']]=[]
                    continue
                payload=payloads[case['question_id']]
                request_path,response_path=work/f'request-{index}.json',work/f'response-{index}.json'
                private_write(request_path,payload)
                report['dispatch_attempts']+=1
                attempt=dict(question_id=case['question_id'],provider_calls=None,http_status=None,state='dispatch_uncertain')
                report['attempts'].append(attempt)
                started=time.perf_counter()
                try:
                    child=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--dispatch-request',str(request_path),
                        '--response-file',str(response_path),'--allow-live'],cwd=ROOT,timeout=20,
                        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=False)
                finally:
                    attempt['latency_ms']=(time.perf_counter()-started)*1000
                if not response_path.exists():raise ValueError()
                response=json.loads(response_path.read_text())
                attempt.update(state=response['state'],provider_calls=response['observation']['provider_calls'],
                    http_status=response['observation'].get('http_status'),code=response.get('code'))
                if child.returncode or response['state']!='passed':raise ValueError()
                scores,billed=normalize(response['raw'],case['evidence'])
                recordings[case['question_id']]=scores
                attempt.update(billed_input_tokens=billed,scores=scores)
        results=await replay(cases,recordings)
        await node_parity(cases,recordings,results)
        report.update(state='passed',evaluation=evaluate(prepared,results),results=results,
                      runtime_parity='recorded_response_replay_not_independent_inference')
        billed=[attempt['billed_input_tokens'] for attempt in report['attempts']]
        report['reported_billed_input_tokens']=sum(billed) if all(value is not None for value in billed) else None
        report['reported_token_cost_estimate_usd']=report['reported_billed_input_tokens']*limits['dated_usd_per_million_tokens']/1e6 if report['reported_billed_input_tokens'] is not None else None
    except Exception:
        report.update(state='failed',code='calibration_failed_no_retry')
    observed=[attempt['provider_calls'] for attempt in report['attempts']]
    report['provider_calls']=sum(observed) if all(value is not None for value in observed) else None
    report['provider_calls_minimum']=sum(value for value in observed if value is not None)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+'\n')
    return report['state']=='passed'


async def node_parity(cases,recordings,results):
    with tempfile.TemporaryDirectory(prefix='cragkit-v3-replay-') as directory:
        payload=Path(directory)/'public.json'
        private_write(payload,dict(cases=cases,recordings=recordings))
        node=subprocess.run(['node','tools/check_typescript_rerank_calibration.mjs','--replay',str(payload)],
            cwd=ROOT,timeout=30,capture_output=True,text=True,check=False)
        if node.returncode or json.loads(node.stdout)!=results:raise ValueError()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live',action='store_true')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--dispatch-request',type=Path)
    parser.add_argument('--response-file',type=Path)
    args=parser.parse_args()
    if not args.allow_live:
        print(json.dumps(dict(state='refused',code='explicit_live_opt_in_required')));return 2
    try:
        if args.dispatch_request:
            if args.response_file is None:raise ValueError()
            return 0 if dispatch(args.dispatch_request,args.response_file) else 1
        if args.baseline is None or args.output is None:raise ValueError()
        passed=asyncio.run(run(args.baseline,args.output))
        print(json.dumps(dict(state='passed' if passed else 'failed',code='calibration_completed' if passed else 'calibration_failed_no_retry')))
        return 0 if passed else 1
    except Exception:
        print(json.dumps(dict(state='failed',code='calibration_preflight_or_dispatch_failed')));return 1


if __name__=='__main__':raise SystemExit(main())
