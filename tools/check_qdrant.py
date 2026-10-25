"""Serial native Python/Node QC-r1 acceptance on an explicitly supplied local server."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from qdrant_native import QdrantFixture, ROOT


async def python_cases(value: dict[str, Any]) -> list[dict[str, Any]]:
    from cragkit.errors import CragkitError
    from cragkit.execution import ExecutionLedger
    from cragkit.qdrant import HttpxQdrantTransport, QdrantSearchStore
    transport = HttpxQdrantTransport(value['endpoint'], api_key=value['api_key'], allow_loopback_http=True)
    store = QdrantSearchStore(value['config'], transport)
    output = []
    try:
        await store.initialize(deadline=asyncio.get_running_loop().time() + 5)
        for case in value['cases']:
            deadline = asyncio.get_running_loop().time() + 5
            filters = [{'op': 'eq', 'field': 'document_id', 'value': case['document']}]
            if 'tag' in case:
                filters.append({'op': 'eq', 'field': 'tag', 'value': case['tag']})
            request = {'request_id': 'native-' + case['id'], 'query': 'synthetic fixture query',
                       'collection': 'docs', 'required_filters': filters,
                       'limits': {'max_candidates': 4, 'max_provider_calls': 0}}
            scope = dict(value['scope'])
            if case.get('empty_grants'):
                scope['grant_ids'] = []
            ledger = ExecutionLedger(request['limits'], deadline=deadline)
            try:
                nominations = await store.search_candidates(request, scope=scope, dense=value['dense'],
                    sparse=value['sparse'], branch_limits={'dense': 2, 'sparse': 2},
                    ledger=ledger, deadline=deadline)
                if 'error' in case or len(nominations) != case['count']:
                    raise AssertionError('native_candidate_count')
                record = {'id': case['id'], 'nominations': [n.model_dump(mode='json') for n in nominations]}
            except CragkitError as exc:
                if exc.code != case.get('error'):
                    raise AssertionError('native_error_semantics') from None
                record = {'id': case['id'], 'error': exc.code}
            snapshot = ledger.snapshot()
            if snapshot['provider_calls'] != 0 or snapshot['pending'] != 0 or snapshot['candidates'] != 4:
                raise AssertionError('native_ledger_semantics')
            record['ledger'] = snapshot
            output.append(record)
    finally:
        await store.close()
        await transport.close()
    return output


def compare(expected: Any, actual: Any) -> bool:
    if type(expected) in (int, float) and type(actual) in (int, float):
        return abs(expected - actual) <= 1e-6
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(compare(expected[k], actual[k]) for k in expected)
    if isinstance(expected, (tuple, list)) and isinstance(actual, (tuple, list)):
        return len(expected) == len(actual) and all(compare(a, b) for a, b in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--artifacts-dir', type=Path, default=ROOT / 'artifacts/V5/native-candidates')
    args = parser.parse_args()
    with QdrantFixture(args.server_binary, args.artifacts_dir, args.binary_sha256) as fixture:
        data = fixture.child_input()
        py = asyncio.run(python_cases(data))
        env = {k: v for k, v in os.environ.items()
               if k not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_USE_ENV_PROXY')}
        child = subprocess.run(['node', str(ROOT / 'tools/check_typescript_qdrant.mjs')],
            input=json.dumps(data), capture_output=True, text=True, timeout=30, cwd=ROOT, env=env)
        if child.returncode != 0 or child.stderr:
            raise RuntimeError('native_node_failed_private_input_suppressed')
        node = json.loads(child.stdout)
        if not compare(py, node):
            raise AssertionError('native_runtime_parity')
    report = {'task': 'V5-02D', 'contract_revision': 'QC-r1', 'server_version': '1.20.0',
              'native_runtime_cases_each': len(py), 'full_nomination_and_ledger_parity': True,
              'server_checks': fixture.checks, 'source_authorization_tested': False,
              'python': py, 'node': node}
    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    (args.artifacts_dir / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('python', 'node')}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('Qdrant native acceptance failed; private input and raw errors suppressed.', file=sys.stderr)
        raise SystemExit(1) from None
