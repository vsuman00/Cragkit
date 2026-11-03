"""MRR-r1 historical installed-wheel consumer; private configuration arrives on stdin."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys

import cragkit
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._postgres_session import PostgresSession
from cragkit.contracts import parse_request, parse_scope
from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
from cragkit.retrieval import PostgresRetriever


def require(condition):
    if not condition:
        raise RuntimeError('migration_package_probe_invalid')


def verify_installed_files(expected,expected_version):
    package = Path(cragkit.__file__).resolve().parent
    require(expected_version in ('0.0.0','1.0.0rc1') and cragkit.__version__ == expected_version
        and package.is_relative_to(Path(sys.prefix).resolve()))
    observed = {}
    for ordinal, path in enumerate(package.rglob('*')):
        require(ordinal < 2000 and not path.is_symlink())
        if path.is_file():
            require(path.stat().st_size <= 2 * 1024 * 1024)
            observed[path.relative_to(package).as_posix()] = sha256(path.read_bytes()).hexdigest()
    require(observed == expected)


class Counter:
    name = 'fake-byte-v1'

    def count(self, text):
        return len(text.encode())


async def fake_transport(body, *, deadline, max_response_bytes):
    request = json.loads(body)
    tokens = sum(len(text.encode()) for text in request['input'])
    return json.dumps(dict(model=FAKE_PROFILE.model,
        data=[dict(index=index, embedding=[1.] + [0.] * 1535)
            for index in range(len(request['input']))],
        usage=dict(prompt_tokens=tokens, total_tokens=tokens))).encode()


async def probe(value):
    require(sys.flags.isolated and sys.dont_write_bytecode)
    verify_installed_files(value['files'],value['expected_version'])
    configuration = dict(value['reader_config'])
    for field in ('sslrootcert', 'passfile'):
        configuration[field] = Path(configuration[field])
    resource = PoolResource(PoolConfig.model_validate(configuration))
    await resource.open()
    outcomes = {}
    cases = (('lexical', 'lexical', 'lexical-document', 'Migration recovery'),
             ('identifier', 'lexical', 'identifier-document', 'ERR_RECOVERY_42'),
             ('dense', 'dense', 'vector-document', 'Migration recovery'))
    try:
        for probe_name, mode, document, query in cases:
            expected = value['expected_sources'][document]
            options = {} if mode == 'lexical' else dict(embedder=EmbeddingAdapter(fake_transport, Counter()))
            try:
                request = parse_request(dict(query=query, collection=value['collection'],
                    required_filters=[dict(op='eq', field='document_id', value=document)]))
                scope = parse_scope(value['scope'])
                deadline = asyncio.get_running_loop().time()+15
                if probe_name == 'identifier':
                    async with PostgresSession(resource).transaction(request,scope=scope,deadline=deadline) as session:
                        candidates = await session.identifier_candidates(query,limit=5)
                        require(len(candidates)==1 and candidates[0].identifier_profile=='identifier_ascii_v1')
                        fetched = await session.fetch_evidence(candidates[0],max_source_bytes=4096)
                        require(fetched.state=='verified' and not fetched.stale and fetched.evidence is not None)
                        evidence = [fetched.evidence]
                else:
                    retriever = PostgresRetriever(resource, mode=mode, **options)
                    result = await retriever.retrieve(request,scope=scope,deadline=deadline)
                    require(result.execution=='complete')
                    evidence = result.evidence
                require(bool(evidence)
                    and all(item.document_id == document and item.source_sha256 == expected['sha256']
                        and item.revision_id == expected['revision_id'] and item.text == expected['text']
                        and item.start_byte == 0 and item.end_byte == len(expected['text'].encode())
                        and item.text_sha256 == sha256(item.text.encode()).hexdigest()
                        for item in evidence))
                outcomes[probe_name] = 'complete'
            except Exception as error:
                require(getattr(error, 'code', None) == 'unsupported_capability')
                outcomes[probe_name] = 'unsupported_capability'
    finally:
        await resource.close()
    return dict(runtime='python', version=cragkit.__version__, installed_bytes_verified=True, **outcomes)


def main():
    try:
        raw = sys.stdin.buffer.read(131073)
        require(len(raw) <= 131072)
        result = asyncio.run(probe(json.loads(raw)))
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps(dict(state='failed', code='migration_package_probe_invalid')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
