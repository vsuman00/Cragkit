"""Run HY-r1 public retrieval and synthetic-vector parity without a database."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evaluation/runners'))
from synthetic_vectors import encode
from check_identifier_fusion import compare

TEXTS = ['ERR_CONN-42 Café🙂', 'ordinary words', '', 'x1 x1']


async def probe(entry):
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
    from cragkit.errors import CragkitError, ProviderUnavailable
    from cragkit.retrieval import PostgresRetriever

    calls = []
    class Counter:
        name = 'fake-byte-v1'
        def count(self, text): return len(text.encode('utf-8'))
    async def transport(body, *, deadline, max_response_bytes):
        calls.append(['embedding'])
        if entry.get('fail_embedding'): raise RuntimeError('synthetic failure')
        data = json.loads(body)
        count = sum(len(text.encode('utf-8')) for text in data['input'])
        return json.dumps(dict(model=FAKE_PROFILE.model,
            data=[dict(index=index, embedding=encode(text)) for index,text in enumerate(data['input'])],
            usage=dict(prompt_tokens=count,total_tokens=count))).encode()
    class Session:
        @asynccontextmanager
        async def transaction(self, request, **options):
            calls.append(['transaction',request.model_dump(mode='json')['required_filters']])
            class Handle:
                async def candidate_branch(self, operation): return await operation()
                async def dense_candidates(self, batch, *, limit): return self.run('dense',limit)
                async def lexical_candidates(self, *, limit): return self.run('lexical',limit)
                async def identifier_candidates(self, token, *, limit): return self.run('identifier',limit)
                def run(self, family, limit):
                    calls.append([family,limit])
                    if entry.get('fail_family') == family: raise ProviderUnavailable()
                    return ()
            yield Handle()
    retriever = PostgresRetriever(None, mode=entry['mode'], embedder=EmbeddingAdapter(transport,Counter()),
                                   allow_degraded=entry.get('allow_degraded',False))
    retriever._session = Session()
    request = parse_request(dict(request_id='hybrid-parity',query='ERR_CONN-42',collection='manuals',
        required_filters=[dict(field='document_id',op='eq',value='wanted')],
        limits=dict(max_candidates=entry['max_candidates'],max_provider_calls=entry.get('max_provider_calls',16))))
    try:
        result = (await retriever.retrieve(request,scope=parse_scope(dict(tenant_id='tenant',principal_id='person',authorization_revision='auth')),
            deadline=asyncio.get_running_loop().time()+2)).model_dump(mode='json')
        for stage in result['usage']['stage_durations']: stage['duration_ms']=0
        return dict(result=result,calls=calls)
    except CragkitError as error:
        return dict(error=error.code,calls=calls)


async def check():
    fixture=json.loads((ROOT/'contracts/fixtures/hybrid.json').read_text())
    python=[await probe(entry) for entry in fixture['boundary_cases']]
    process=subprocess.run(['node','tools/check_typescript_hybrid_contract.mjs'],input=json.dumps(dict(cases=fixture['boundary_cases'],texts=TEXTS)),
                           text=True,capture_output=True,cwd=ROOT,timeout=30,check=False)
    if process.returncode: raise ValueError('hybrid_node_probe')
    node=json.loads(process.stdout)
    compare(python,node['cases'])
    compare([encode(text) for text in TEXTS],node['vectors'])
    # Independent assertions prevent two matching implementations from passing a shared error.
    assert python[0]['calls']==[['embedding'],['transaction',[dict(field='document_id',op='eq',value='wanted')]],['dense',3],['lexical',3],['identifier',2]]
    assert python[0]['result']['execution']=='complete'
    assert python[3]['result']['execution']=='degraded'
    assert python[3]['result']['usage']['provider_input_tokens'] is None
    assert python[6]==dict(error='invalid_request',calls=[])
    assert python[7]==dict(error='invalid_request',calls=[])
    return dict(state='passed',revision='HY-r1',public_boundary_cases=len(python),synthetic_encoder_cases=len(TEXTS),evidence_kind='fake_no_database')


def main():
    try: result=asyncio.run(check())
    except Exception:
        print(json.dumps(dict(state='failed',code='hybrid_contract_failed')))
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__': raise SystemExit(main())
