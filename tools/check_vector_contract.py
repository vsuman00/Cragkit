"""Check VG-r1 SQL, setup identity and native preparation parity without providers."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SQL_NAMES = (
    '_VECTOR_CAPABILITY_SQL', '_SETUP_HISTORY_SQL', '_PROFILE_SQL', '_VECTOR_JOB_SQL',
    '_VECTOR_GENERATION_SQL', '_VECTOR_REVISION_SQL', '_MANIFEST_SQL', '_MISSING_SQL',
    '_VECTOR_COUNTS_SQL', '_GRANTS_SQL', '_VECTOR_INSERT_SQL',
)
NODE_PROBE = """
import * as vector from './packages/typescript/dist/vector-ingestion.js';
import * as lifecycle from './packages/typescript/dist/lifecycle.js';
import {EmbeddingAdapter} from './packages/typescript/dist/embeddings.js';
import {now} from './packages/typescript/dist/postgres-pool.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const cases = JSON.parse(input);
const adapter = new EmbeddingAdapter(
  async () => { throw Error('provider_must_not_run'); },
  {name: 'fake-byte-v1', count: text => Buffer.byteLength(text)},
);
const indexer = new vector.PostgresVectorIndexer({}, async () => true, adapter);
const receipts = [];
for (const entry of cases) {
  const {source, ...options} = entry;
  receipts.push((await indexer.prepare(source, {...options, deadline: now() + 10})).receipt);
}
console.log(JSON.stringify({
  sql: Object.fromEntries(Object.entries(vector).filter(([name]) => name.endsWith('_SQL'))),
  history: vector.EXPECTED_VECTOR_HISTORY,
  purge: lifecycle._PURGE_CATALOG_SQL,
  receipts,
}));
"""


def normalize_sql(source: str) -> str:
    """Normalize driver placeholders without erasing parameter order or scope."""
    position = 0

    def placeholder(match: re.Match[str]) -> str:
        nonlocal position
        position += 1
        return f'${position}'

    # Preserve quoted values and identifiers: their case/spacing can change SQL meaning.
    pieces = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", source)
    normalized = []
    for index, piece in enumerate(pieces):
        if index % 2:
            normalized.append(piece)
            continue
        outside = re.sub('%s', placeholder, piece).lower()
        # Node requests int counts; VG-r1 bounds counts far below the int4 ceiling.
        outside = outside.replace('count(*)::int', 'count(*)')
        normalized.extend(outside.split())
    return ' '.join(normalized)


async def check() -> dict:
    from cragkit import vector_ingestion as python
    from cragkit.contracts import parse_scope
    from cragkit.embeddings import EmbeddingAdapter
    from cragkit.lifecycle import _PURGE_CATALOG_SQL

    class Counter:
        name = 'fake-byte-v1'

        def count(self, text: str) -> int:
            return len(text.encode('utf-8'))

    async def unused(*args, **kwargs):
        raise AssertionError('provider_must_not_run')

    async def allowed(*args):
        return True

    shared = json.loads((ROOT / 'contracts/fixtures/vector_generations.json').read_text())
    scope = dict(
        tenant_id='fixture-tenant', principal_id='fixture-principal',
        authorization_revision='fixture-revision', grant_ids=[],
    )
    sources = (shared['baseline_source'], shared['replacement_source'], 'Café🙂\n\nalpha fixture')
    cases = [
        dict(
            source=source, collection='fixture-collection', document_id='same-document',
            intent_id=f'intent-{index}', source_locator='synthetic:vector-fixture',
            scope={**scope, 'grant_ids': [] if index % 2 == 0 else ['b', 'a', 'a']},
            metadata=shared['metadata'], canonical_options=shared['canonical_options'],
            expected_generation_id=None if index == 0 else 'prior-generation',
        )
        for index, source in enumerate(sources)
    ]
    adapter = EmbeddingAdapter(unused, Counter())
    indexer = python.PostgresVectorIndexer(None, authorize_write=allowed, embedder=adapter)
    receipts = []
    for case in cases:
        options = {key: value for key, value in case.items() if key not in ('source', 'scope')}
        prepared = await indexer._prepare(
            case['source'], **options, scope=parse_scope(case['scope']),
            deadline=asyncio.get_running_loop().time() + 10, format='text/plain',
        )
        receipts.append(prepared.receipt.model_dump(mode='json'))

    result = subprocess.run(
        ['node', '--input-type=module', '-e', NODE_PROBE], input=json.dumps(cases),
        text=True, capture_output=True, cwd=ROOT, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise ValueError('node_vector_contract_failed')
    node = json.loads(result.stdout)
    for name in SQL_NAMES:
        if normalize_sql(getattr(python, name)) != normalize_sql(node['sql'][name]):
            raise ValueError('vector_sql_parity_' + name)
    if normalize_sql(_PURGE_CATALOG_SQL) != normalize_sql(node['purge']):
        raise ValueError('vector_lifecycle_catalog_parity')
    canonical = (ROOT / 'storage/postgres/queries/vector_capability.sql').read_text()
    if normalize_sql(canonical) != normalize_sql(python._VECTOR_CAPABILITY_SQL):
        raise ValueError('canonical_vector_capability_drift')
    history = [list(row) for row in python.EXPECTED_VECTOR_HISTORY]
    if node['history'] != history:
        raise ValueError('vector_history_parity')
    for version, checksum in history:
        artifact = ROOT / 'storage/postgres/setup' / f'{version}.sql'
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != checksum:
            raise ValueError('vector_setup_checksum_drift')
    if receipts != node['receipts']:
        raise ValueError('vector_identity_parity')
    ids = [case['id'] for case in shared['cases']]
    if len(ids) != 12 or len(set(ids)) != 12:
        raise ValueError('vector_fixture_identity')
    return dict(
        state='passed', revision=shared['revision'], sql_queries=len(SQL_NAMES),
        identity_cases=len(cases), fixture_case_definitions=len(ids), lifecycle_queries=1,
    )


def main() -> int:
    try:
        result = asyncio.run(check())
    except Exception as error:
        # Never expose child-process output, provider text or database details.
        code = (
            str(error) if type(error) is ValueError and re.fullmatch('[A-Za-z_]+', str(error))
            else 'vector_contract_failed'
        )
        print(json.dumps(dict(state='failed', code=code)))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
