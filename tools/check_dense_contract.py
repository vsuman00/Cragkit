"""Compare native dense SQL and hand-calculated synthetic fixture ordering."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
import re
import subprocess

from check_vector_contract import normalize_sql

ROOT = Path(__file__).resolve().parents[1]
NODE_PROBE = """
import {_DENSE_SQL} from './packages/typescript/dist/postgres-session.js';
let data='';for await(const part of process.stdin)data+=part;
const fixture=JSON.parse(data);
function distance(a,b){return 1-a.reduce((sum,x,i)=>sum+x*b[i],0)/Math.sqrt(a.reduce((sum,x)=>sum+x*x,0)*b.reduce((sum,x)=>sum+x*x,0));}
const orders=fixture.cases.map(entry=>fixture.documents
  .filter(doc=>entry.filters.every(filter=>doc.document_id===filter.value))
  .map(doc=>[doc.document_id,distance(entry.coordinates,doc.coordinates)])
  .sort((a,b)=>a[1]-b[1]||(a[0]<b[0]?-1:a[0]>b[0]?1:0)).slice(0,entry.limit));
console.log(JSON.stringify({sql:_DENSE_SQL.replace('{predicate}','TRUE').replace('{limit}','$9'),orders}));
"""


def distance(left: list[float], right: list[float]) -> float:
    return 1 - sum(a * b for a, b in zip(left, right, strict=True)) / math.sqrt(
        sum(a * a for a in left) * sum(b * b for b in right)
    )


async def check() -> dict:
    from cragkit._postgres_session import _DENSE_SQL

    fixture = json.loads((ROOT / 'contracts/fixtures/dense.json').read_text())
    canonical = (ROOT / 'storage/postgres/queries/dense_candidates.sql').read_text()
    expected_sql = normalize_sql(canonical.replace('{predicate}', 'TRUE'))
    if normalize_sql(_DENSE_SQL.replace('{predicate}', 'TRUE')) != expected_sql:
        raise ValueError('dense_python_sql_drift')
    process = subprocess.run(
        ['node', '--input-type=module', '-e', NODE_PROBE], input=json.dumps(fixture),
        text=True, capture_output=True, cwd=ROOT, timeout=30, check=False,
    )
    if process.returncode:
        raise ValueError('dense_node_contract_failed')
    node = json.loads(process.stdout)
    if normalize_sql(node['sql']) != expected_sql:
        raise ValueError('dense_node_sql_drift')
    if len(node['orders']) != len(fixture['cases']):
        raise ValueError('dense_fixture_count')
    for entry, native in zip(fixture['cases'], node['orders'], strict=True):
        rows = [(doc['document_id'], distance(entry['coordinates'], doc['coordinates']))
                for doc in fixture['documents']
                if all(doc['document_id'] == condition['value'] for condition in entry['filters'])]
        rows = sorted(rows, key=lambda row: (row[1], row[0]))[:entry['limit']]
        for actual in (rows, native):
            if len(actual) != len(entry['expected']):
                raise ValueError('dense_reference_count')
            for row, expected in zip(actual, entry['expected'], strict=True):
                if row[0] != expected[0] or abs(row[1] - expected[1]) > fixture['tolerance']:
                    raise ValueError('dense_reference_order')
    return dict(state='passed', revision=fixture['revision'], reference_cases=len(fixture['cases']),
                sql_queries=1, evidence_kind='synthetic_math_and_sql_only')


def main() -> int:
    try:
        result = asyncio.run(check())
    except Exception as error:
        code = str(error) if type(error) is ValueError and re.fullmatch('dense_[a-z_]+', str(error)) else 'dense_contract_failed'
        print(json.dumps(dict(state='failed', code=code)))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
