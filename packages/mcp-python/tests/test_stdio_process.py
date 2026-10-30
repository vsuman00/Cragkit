"""Installed MCP host subprocess checks with synthetic retrieval and no providers."""

import asyncio
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest


QUERY = 'synthetic café 🙂'
SCOPE = dict(tenant_id='tenant', principal_id='principal', authorization_revision='1', grant_ids=['grant'])
FILTERS = [dict(field='document_id', op='eq', value='document')]

# -I deliberately excludes cwd and PYTHONPATH: the subprocess must resolve the
# package from its interpreter's installation, rather than a test sys.path edit.
CHILD = r'''
import asyncio
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys

from cragkit.contracts import RetrievalResult
from cragkit_mcp import create_server

audit = {"calls": [], "closed": False, "package_version": version("cragkit-mcp")}
destination = Path(sys.argv[1])
scope = dict(tenant_id='tenant', principal_id='principal', authorization_revision='1', grant_ids=['grant'])
filters = [dict(field='document_id', op='eq', value='document')]

class Engine:
    async def retrieve(self, request, *, scope, deadline):
        assert deadline > asyncio.get_running_loop().time()
        audit['calls'].append(dict(request=request.model_dump(mode='json'), scope=scope.model_dump(mode='json')))
        text = request.query
        digest = sha256(text.encode()).hexdigest()
        result = RetrievalResult.model_validate(dict(
            request_id=request.request_id, status='partial', execution='complete',
            evidence=[dict(evidence_id='evidence', collection='collection', document_id='document',
                revision_id='revision', chunk_id='chunk', source_locator='synthetic:source',
                start_byte=0, end_byte=len(text.encode()), text=text, source_sha256=digest, text_sha256=digest)],
            limitations=[], context='[]', usage=dict(attempt_count=1, provider_calls=0,
                provider_input_tokens=0, provider_output_tokens=0, cost_usd=0, cost_kind='known',
                context_tokens=1, context_counting='estimated')))
        return dict(result=result, diagnostics={'secret': 'private-diagnostic-canary'})

host = create_server(Engine(), scope=scope, template=dict(collection='collection',
    required_filters=filters, limits=dict(deadline_ms=1000, max_candidates=12,
        max_attempts=3, max_subqueries=3, max_provider_calls=8, max_context_tokens=20000),
    output_profile=dict(renderer='cragkit.context.v2', counting_mode='estimated',
        tokenizer=None, envelope_reserve_tokens=17)),
    final_serializer=lambda value: value.model_dump_json(by_alias=True, exclude_unset=True))

async def main():
    try:
        await host.run_stdio()
    finally:
        await host.close()
        await host.close()
        audit['closed'] = True
        destination.write_text(json.dumps(audit), encoding='utf-8')

asyncio.run(main())
'''


def test_installed_host_official_sdk_stdio_roundtrip(tmp_path: Path) -> None:
    audit_path = tmp_path / 'audit.json'
    log_path = tmp_path / 'stderr.txt'
    args = dict(request_id='process-request', query=QUERY, collection='collection')

    async def scenario() -> None:
        parameters = StdioServerParameters(command=sys.executable,
            args=['-I', '-c', CHILD, str(audit_path)], cwd=tmp_path)
        # The SDK owns, closes and reaps the child even if a client assertion or
        # timeout fails. Its own shutdown waits are bounded in the pinned SDK.
        with anyio.fail_after(15), log_path.open('w', encoding='utf-8') as log:
            async with stdio_client(parameters, errlog=log) as streams:
                async with ClientSession(*streams, read_timeout_seconds=3) as client:
                    await client.initialize()
                    listing = await client.list_tools()
                    assert [tool.name for tool in listing.tools] == ['cragkit_retrieve']
                    assert listing.tools[0].input_schema['additionalProperties'] is False
                    for forbidden in (
                        dict(scope=dict(tenant_id='forged-tenant')),
                        dict(required_filters=[]),
                        dict(limits=dict(max_candidates=1000)),
                    ):
                        rejected = await client.call_tool('cragkit_retrieve', args | forbidden)
                        assert rejected.is_error is True
                        assert [item.text for item in rejected.content] == ['invalid_request']
                    rejected = await client.call_tool('cragkit_retrieve', args | dict(collection='other'))
                    assert rejected.is_error is True
                    assert [item.text for item in rejected.content] == ['invalid_request']
                    answer = await client.call_tool('cragkit_retrieve', args)
                    assert answer.is_error is False
                    assert len(answer.content) == 1
                    value = json.loads(answer.content[0].text)
                    assert value['request_id'] == args['request_id']
                    assert (value['status'], value['execution']) == ('partial', 'complete')
                    assert len(value['evidence']) == 1
                    evidence = value['evidence'][0]
                    assert evidence['text'] == QUERY
                    assert evidence['source_locator'] == 'synthetic:source'
                    assert (evidence['start_byte'], evidence['end_byte']) == (0, len(QUERY.encode()))
                    assert evidence['text_sha256'] == evidence['source_sha256'] == sha256(QUERY.encode()).hexdigest()
                    assert value['usage']['provider_calls'] == 0
                    assert 'private-diagnostic-canary' not in answer.model_dump_json()

    asyncio.run(scenario())
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['closed'] is True
    assert audit['package_version'] == '0.0.0'
    assert len(audit['calls']) == 1
    assert audit['calls'][0]['scope'] == SCOPE
    request = audit['calls'][0]['request']
    assert request['required_filters'] == FILTERS
    assert request['limits']['max_candidates'] == 12
    assert request['query'] == QUERY
    assert 'private-diagnostic-canary' not in log_path.read_text(encoding='utf-8')


@pytest.mark.parametrize('frame', [b'', b'{"private-malformed-canary":\n', b'\xffprivate-malformed-canary\n'])
def test_installed_stdio_eof_and_malformed_frames_close_without_retrieval(tmp_path: Path, frame: bytes) -> None:
    audit_path = tmp_path / 'audit.json'
    # communicate closes stdin, waits at most eight seconds, and run kills/reaps
    # the owned child on timeout. No listener or persistent process is created.
    completed = subprocess.run([sys.executable, '-I', '-c', CHILD, str(audit_path)],
        cwd=tmp_path, input=frame, capture_output=True, timeout=8, check=False)
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['closed'] is True
    assert audit['calls'] == []
    assert completed.stdout == b''
    assert b'private-malformed-canary' not in completed.stderr
    if not frame:
        assert completed.returncode == 0
