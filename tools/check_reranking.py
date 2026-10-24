"""Compare RK-r2 native adapters against the recorded mapping specification."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


async def check():
    from cragkit.reranking import FAKE_RERANK_PROFILE, RerankingAdapter
    from cragkit.errors import CragkitError
    fixture = json.loads((ROOT / 'contracts/fixtures/reranking.json').read_text())
    results = []
    for entry in fixture['cases']:
        selected = fixture['sample']['candidates'] if 'candidate_ids' not in entry else []
        async def transport(body, *, deadline, max_response_bytes):
            return json.dumps(entry['response']).encode()
        profile = FAKE_RERANK_PROFILE.model_copy(update={
            'score_direction': entry.get('score_direction', 'higher_is_better')})
        try:
            result = await RerankingAdapter(transport, profile=profile).rank(
                fixture['sample']['query'], selected, deadline=asyncio.get_running_loop().time()+2)
            assert result['order'] == entry['expected_order']
            assert result['provider_calls'] == (1 if selected else 0)
            results.append(result)
        except CragkitError as error:
            assert 'expected_rejection' in entry
            assert error.code == 'integrity_violation'
            results.append({'error': error.code})
    process = subprocess.run(['node', 'tools/check_typescript_reranking.mjs'],
        cwd=ROOT, text=True, capture_output=True, timeout=30, check=False)
    if process.returncode or json.loads(process.stdout) != results:
        raise ValueError('native_reranking_parity')
    return {'state':'passed', 'revision':'RK-r2', 'cases':len(results), 'evidence_kind':'synthetic_no_inference'}


def main():
    try:
        result = asyncio.run(check())
    except Exception:
        print(json.dumps({'state':'failed','code':'reranking_contract_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
