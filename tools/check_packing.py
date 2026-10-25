"""PK-r1 deterministic source/budget conformance in both native runtimes."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


async def check():
    from cragkit.context import Cl100kCounter, count_context
    from cragkit.errors import CragkitError
    from cragkit.packing import pack_evidence
    fixture = json.loads((ROOT / 'contracts/fixtures/packing.json').read_text())
    counter = Cl100kCounter.from_file(ROOT / 'artifacts/tokenizers/cl100k_base.tiktoken')
    results = []
    for case in fixture['cases']:
        options = dict(case['options'])
        if options.get('counting_mode') == 'strict':
            options['counter'] = counter
        try:
            result = await pack_evidence(case['evidence'], case['sources'],
                                         deadline=time.monotonic() + 10, **options)
            assert 'expected_error' not in case
            assert [item['text'] for item in result['evidence']] == case['expected_texts']
            assert result['total_tokens'] <= options['max_tokens']
            assert json.loads(result['context']) == result['evidence']
            assert result['omitted_count'] == len(case['evidence']) - sum(map(len, result['aliases'].values()))
            for item in result['evidence']:
                source = next(s for s in case['sources'] if all(s[k] == item[k] for k in ('collection','document_id','revision_id')))
                data = source['text'].encode()
                assert data[item['start_byte']:item['end_byte']].decode() == item['text']
                assert hashlib.sha256(data).hexdigest() == item['source_sha256']
                assert hashlib.sha256(item['text'].encode()).hexdigest() == item['text_sha256']
            counted = count_context(result['evidence'], **{k:v for k,v in options.items() if k in ('max_tokens','reserve','counting_mode','counter')})
            assert all(result[k] == v for k,v in counted.items())
            results.append(result)
        except CragkitError as error:
            assert error.code == case['expected_error'], case['id']
            results.append({'error': error.code})
    node = subprocess.run(['node','tools/check_typescript_packing.mjs'], cwd=ROOT,
                          timeout=30, check=False, capture_output=True, text=True)
    if node.returncode or json.loads(node.stdout) != results:
        raise ValueError('packing_parity')
    return {'state':'passed','revision':'PK-r1','cases':len(results)}


def main():
    try:
        result = asyncio.run(check())
    except Exception:
        print(json.dumps({'state':'failed','code':'packing_contract_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
