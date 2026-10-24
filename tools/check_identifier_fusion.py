"""Check native identifier extraction, SQL and actual fusion against IF-r1 fixtures."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess

from check_vector_contract import normalize_sql

ROOT = Path(__file__).resolve().parents[1]
NODE_PROBE = """
import {extract_identifiers} from './packages/typescript/dist/identifiers.js';
import {_IDENTIFIER_SQL} from './packages/typescript/dist/postgres-session.js';
import {fuse} from './packages/typescript/dist/fusion.js';
let input='';for await(const part of process.stdin)input+=part;
const fixture=JSON.parse(input);
const run=entry=>{try{return {value:fuse(entry.lists,entry.options)}}catch(error){return {error:error.code??'unexpected_error'}}};
console.log(JSON.stringify({extraction:fixture.extraction.map(entry=>extract_identifiers(entry.text)),
 sql:_IDENTIFIER_SQL.replace('{predicate}','TRUE').replace('{identifier}','$7').replace('{limit}','$8'), results:[...fixture.cases,...fixture.invalid].map(run)}));
"""


def compare(actual, expected, tolerance=1e-12):
    """Compare complete provenance as well as mathematical scores."""
    if type(actual) is float or type(expected) is float:
        if type(actual) not in (int, float) or type(expected) not in (int, float):
            raise ValueError('fusion_number_type')
        if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual-expected) > tolerance:
            raise ValueError('fusion_number_value')
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise ValueError('fusion_object_shape')
        for key in expected:
            compare(actual[key], expected[key], tolerance)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError('fusion_array_shape')
        for left, right in zip(actual, expected, strict=True):
            compare(left, right, tolerance)
    elif actual != expected or type(actual) is not type(expected):
        raise ValueError('fusion_value')


def check():
    from cragkit._identifiers import extract_identifiers
    from cragkit._fusion import fuse
    from cragkit._postgres_session import _IDENTIFIER_SQL
    from cragkit.errors import CragkitError

    fixture = json.loads((ROOT / 'contracts/fixtures/identifier_fusion.json').read_text())
    process = subprocess.run(['node', '--input-type=module', '-e', NODE_PROBE], input=json.dumps(fixture),
                             text=True, capture_output=True, cwd=ROOT, timeout=30, check=False)
    if process.returncode:
        raise ValueError('fusion_node_probe')
    node = json.loads(process.stdout)
    canonical = (ROOT / 'storage/postgres/queries/identifier_candidates.sql').read_text().replace('{predicate}', 'TRUE')
    for sql in (_IDENTIFIER_SQL.replace('{predicate}', 'TRUE'), node['sql']):
        if normalize_sql(sql) != normalize_sql(canonical):
            raise ValueError('fusion_sql_drift')
    for entry, other in zip(fixture['extraction'], node['extraction'], strict=True):
        compare(list(extract_identifiers(entry['text'])), entry['expected'])
        compare(other, entry['expected'])
    results = []
    for entry in [*fixture['cases'], *fixture['invalid']]:
        try:
            results.append(dict(value=fuse(entry['lists'], **entry['options'])))
        except CragkitError as error:
            results.append(dict(error=error.code))
    compare(results, node['results'], fixture['tolerance'])
    for entry, result in zip([*fixture['cases'], *fixture['invalid']], results, strict=True):
        if 'error' in entry:
            compare(result, dict(error=entry['error']))
        else:
            rows = [[item['candidate']['document_id'], item['score']] for item in result['value']]
            compare(rows, entry['expected'], fixture['tolerance'])
    return dict(state='passed', revision='IF-r1', extraction_cases=len(fixture['extraction']),
                ranking_cases=len(fixture['cases']), rejected_cases=len(fixture['invalid']),
                sql_queries=1, evidence_kind='actual_native_functions_synthetic_inputs')


def main():
    try:
        result = check()
    except Exception:
        print(json.dumps(dict(state='failed', code='identifier_fusion_contract_failed')))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
