"""TK-r1 exact serialization and tokenizer parity using pinned local assets."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check():
    from cragkit.context import Cl100kCounter, count_context
    from cragkit.errors import CragkitError
    fixture = json.loads((ROOT/'contracts/fixtures/context.json').read_text())
    counter = Cl100kCounter.from_file(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')
    results = []
    for item in fixture['cases']:
        try:
            result = count_context(item['evidence'], max_tokens=item['max_tokens'], reserve=item['reserve'],
                counting_mode=item['counting_mode'], counter=counter if item['counting_mode']=='strict' else None)
            assert 'expected_error' not in item
            assert result['context'] == item.get('expected_context',result['context'])
            assert result['context_tokens'] == item.get('expected_context_tokens',result['context_tokens'])
            assert result['total_tokens'] <= item['max_tokens']
            results.append(result)
        except CragkitError as error:
            assert error.code == item['expected_error']
            results.append({'error':error.code})
    token_counts = []
    for item in fixture['token_cases']:
        tokens = counter.count(item['text'])
        assert tokens == item['expected_tokens'], item['id']
        token_counts.append({'id': item['id'], 'tokens': tokens})
    expected = {'cases': results, 'token_counts': token_counts}
    process = subprocess.run(['node','tools/check_typescript_context.mjs'],cwd=ROOT,
        capture_output=True,text=True,timeout=30,check=False)
    if process.returncode or json.loads(process.stdout)!=expected:
        raise ValueError('context_parity')
    return {'state':'passed','revision':'TK-r1','cases':len(results),
            'token_cases':len(token_counts),'tokenizer':'cl100k_base'}


def main():
    try: result=check()
    except Exception:
        print(json.dumps({'state':'failed','code':'context_contract_failed'}))
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__': raise SystemExit(main())
