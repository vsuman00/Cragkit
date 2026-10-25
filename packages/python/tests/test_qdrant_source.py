import asyncio
import copy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._qdrant_source import MAX_SOURCE_BYTES, verify_source
from cragkit.errors import CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable
from cragkit.qdrant_source import PostgresQdrantSourceStore

FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/qdrant_sources.json').read_text())


def expand(value):
    if isinstance(value, str) and value.startswith('$ref:'):
        target = FIXTURE
        for part in value[5:].split('.'):
            target = target[part]
        return expand(target)
    if isinstance(value, dict):
        if value.get('encoding') == 'utf8': return value['value'].encode('utf-8')
        if value.get('encoding') == 'hex': return bytes.fromhex(value['value'])
        return {key: expand(item) for key, item in value.items()}
    if isinstance(value, list): return [expand(item) for item in value]
    return value


CONFIG = {key: expand(FIXTURE['base_row'][key]) for key in
    ('backend_namespace','physical_collection','collection_incarnation','dense_profile','sparse_profile')}


class FakeAuthority:
    def __init__(self):
        self.row = expand(FIXTURE['base_row'])
        self.calls = 0
        self.failure = None
        self.block = None
        self.entered = asyncio.Event()
        self.settled = asyncio.Event()
    async def initialize(self, *, deadline): pass
    async def read(self, *args, max_source_bytes, **kwargs):
        self.calls += 1
        self.entered.set()
        try:
            if self.block is not None: await self.block.wait()
            if self.failure is not None: raise self.failure
            if self.row is None: return []
            row = copy.deepcopy(self.row)
            if row['source_bytes'] > max_source_bytes:
                row['canonical_utf8'] = row['excerpt_utf8'] = None
            return [row]
        finally:
            self.settled.set()


async def ready():
    resource = PoolResource(PoolConfig(host='example.invalid',dbname='test',user='reader',
        sslrootcert=Path('/tmp/cert'),passfile=Path('/tmp/pass')),pool=object())
    store = PostgresQdrantSourceStore(resource, CONFIG)
    authority = FakeAuthority()
    store._authority = authority
    deadline = asyncio.get_running_loop().time() + 5
    await store.initialize(deadline=deadline)
    handle = store.open_request(expand(FIXTURE['request']),scope=expand(FIXTURE['scope']),deadline=deadline)
    return store,handle,authority,deadline


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda item:item['id'])
def test_shared_source_scenarios(case):
    async def scenario():
        store,handle,authority,deadline = await ready()
        nom = expand(FIXTURE['nomination'])
        binding = None
        condition = case.get('precondition','')
        if case['operation'] == 'release' and case.get('binding') not in ('serialized_identity_copy','issued_by_other_request'):
            binding = (await handle.fetch_candidate(nom,max_source_bytes=MAX_SOURCE_BYTES)).binding
            if condition == 'provider_received_while_authorized':
                await handle.release(binding,purpose='provider',max_source_bytes=MAX_SOURCE_BYTES)
            if condition == 'provider_and_final_release_already_attempted':
                await handle.release(binding,purpose='provider',max_source_bytes=MAX_SOURCE_BYTES)
                await handle.release(binding,purpose='final',max_source_bytes=MAX_SOURCE_BYTES)
            if condition == 'binding_request_closed': await handle.close()
        elif case['operation'] == 'release': binding = {} if case.get('binding') == 'serialized_identity_copy' else object()
        objects = {'base_row': authority.row, 'nomination': nom}
        for path,value in case.get('set',{}).items():
            parts = path.split('.')
            target = objects
            for part in parts[:-1]: target = target[part]
            target[parts[-1]] = expand(value)
        if case.get('authority') == 'no_row': authority.row = None
        if case.get('authority') == 'connection_failure': authority.failure = RuntimeError('PRIVATE_URI_QUERY')
        if case.get('authority') == 'deadline_expired': handle._deadline = asyncio.get_running_loop().time() - 1
        if 'remaining_source_bytes' in case: handle._source_bytes = MAX_SOURCE_BYTES-case['remaining_source_bytes']
        if 'prior_fetch_attempts' in case: handle._fetches = case['prior_fetch_attempts']
        before = authority.calls
        options = dict(max_source_bytes=case.get('max_source_bytes',MAX_SOURCE_BYTES),include_source=case.get('include_source',False))
        async def run():
            if case['operation'] == 'release': return await handle.release(binding,purpose='final',**options)
            return await handle.fetch_candidate(nom,**options)
        expected = case['expected']
        try:
            if 'error' in expected:
                with pytest.raises(CragkitError) as caught: await run()
                assert type(caught.value).__name__ == expected['error']
                assert 'PRIVATE' not in str(caught.value)
            else:
                result = await run()
                assert result.state == expected['state']
                if 'text' in expected: assert result.evidence.text == expected['text']
                if 'source_bytes' in expected: assert result.source_bytes == expected['source_bytes']
                if 'stale' in expected: assert result.stale is expected['stale']
                if 'binding_issued' in expected: assert (result.binding is not None) is expected['binding_issued']
                if 'private_canonical_source' in expected: assert result.private_source.canonical_text == expected['private_canonical_source']
                serialized = result.model_dump(mode='json')
                assert 'binding' not in serialized and 'private_source' not in serialized and 'canonical_utf8' not in serialized
            if 'sql_calls' in expected: assert authority.calls-before == expected['sql_calls']
        finally:
            await store.close()
    asyncio.run(scenario())


def test_opaque_bindings_private_serialization_and_replay():
    async def scenario():
        store,handle,authority,_ = await ready()
        result = await handle.fetch_candidate(expand(FIXTURE['nomination']),max_source_bytes=MAX_SOURCE_BYTES,include_source=True)
        with pytest.raises(TypeError): json.dumps(result.binding)
        assert 'canonical_text' not in result.model_dump_json()
        with pytest.raises(ValidationError): result.private_source.canonical_text='changed'
        before = authority.calls
        for forged in (object(),{},copy.copy(result.binding)):
            with pytest.raises(InvalidRequest): await handle.release(forged,purpose='final',max_source_bytes=MAX_SOURCE_BYTES)
        assert authority.calls == before
        await handle.release(result.binding,purpose='final',max_source_bytes=MAX_SOURCE_BYTES)
        with pytest.raises(InvalidRequest): await handle.release(result.binding,purpose='provider',max_source_bytes=MAX_SOURCE_BYTES)
        await store.close()
    asyncio.run(scenario())


def test_handle_concurrency_cancel_cleanup_and_resource_reuse():
    async def scenario():
        store,handle,authority,deadline = await ready()
        with pytest.raises(ProviderUnavailable): store.open_request(FIXTURE['request'],scope=FIXTURE['scope'],deadline=deadline)
        authority.block = asyncio.Event()
        task = asyncio.create_task(handle.fetch_candidate(expand(FIXTURE['nomination']),max_source_bytes=MAX_SOURCE_BYTES))
        await authority.entered.wait()
        with pytest.raises(ProviderUnavailable): await handle.fetch_candidate(expand(FIXTURE['nomination']),max_source_bytes=MAX_SOURCE_BYTES)
        await handle.close()
        with pytest.raises(asyncio.CancelledError): await task
        assert authority.settled.is_set()
        authority.block = None
        next_handle = store.open_request(FIXTURE['request'],scope=FIXTURE['scope'],deadline=deadline)
        assert (await next_handle.fetch_candidate(expand(FIXTURE['nomination']),max_source_bytes=MAX_SOURCE_BYTES)).state=='verified'
        await store.close()
        await store.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('source', ['\ufeffA café 雪.\r\n','A\x00café 雪.\n'])
def test_bom_crlf_nul_bytes_remain_exact(source):
    async def scenario():
        store,handle,authority,_=await ready()
        raw=source.encode(); excerpt=raw
        nom=expand(FIXTURE['nomination'])
        row=authority.row
        for target in (row,nom['payload']):
            target.update(start_byte=0,end_byte=len(raw),source_sha256=sha256(raw).hexdigest(),text_sha256=sha256(excerpt).hexdigest())
        row.update(canonical_utf8=raw,excerpt_utf8=excerpt,source_bytes=len(raw),excerpt_bytes=len(raw))
        result=await handle.fetch_candidate(nom,max_source_bytes=MAX_SOURCE_BYTES,include_source=True)
        assert result.evidence.text==source and result.private_source.canonical_text==source
        await store.close()
    asyncio.run(scenario())


def test_budget_row_cannot_smuggle_loaded_bytes_and_native_integer_strings():
    row=expand(FIXTURE['base_row']); nom=expand(FIXTURE['nomination'])
    with pytest.raises(IntegrityViolation): verify_source(nom,[row],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=12)
    for key in ('start_byte','end_byte','source_bytes','excerpt_bytes','mutation_epoch'): row[key]=str(row[key])
    assert verify_source(nom,[row],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=13).state=='verified'


def test_defensive_denied_driver_row_reports_loaded_bytes_without_text():
    row=expand(FIXTURE['base_row'])
    row['grant_ids']=[];row['principal_ids']=[]
    result=verify_source(expand(FIXTURE['nomination']),[row],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=13,include_source=True)
    assert result.state=='unavailable' and result.source_bytes==13
    assert result.evidence is None and result.binding is None and result.private_source is None


@pytest.mark.parametrize('change',[{'score_kind':'dot_product'},{'score':2},{'point_id':'malformed'}])
def test_malformed_nomination_semantics_reject_before_read(change):
    async def scenario():
        store,handle,authority,_=await ready()
        with pytest.raises(InvalidRequest):await handle.fetch_candidate(expand(FIXTURE['nomination'])|change,max_source_bytes=13)
        assert authority.calls==0
        await store.close()
    asyncio.run(scenario())


def test_close_cancels_initialization_and_preserves_borrowed_resource():
    async def scenario():
        store,handle,authority,deadline=await ready()
        await handle.close()
        entered=asyncio.Event();settled=asyncio.Event()
        async def blocked(*,deadline):
            entered.set()
            try:await asyncio.Event().wait()
            finally:settled.set()
        authority.initialize=blocked
        task=asyncio.create_task(store.initialize(deadline=deadline))
        await entered.wait()
        await store.close()
        with pytest.raises(asyncio.CancelledError):await task
        assert settled.is_set() and not store._ready
        with pytest.raises(InvalidRequest):store.open_request(FIXTURE['request'],scope=FIXTURE['scope'],deadline=deadline)
        await store.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('value',['x'*1025,'雪'*342])
def test_metadata_strings_are_bounded_before_encoding_or_copy(value):
    nom=expand(FIXTURE['nomination']);nom['payload']['document_id']=value
    with pytest.raises(InvalidRequest):verify_source(nom,[expand(FIXTURE['base_row'])],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=13)
    row=expand(FIXTURE['base_row']);row['source_locator']=value
    with pytest.raises(IntegrityViolation):verify_source(expand(FIXTURE['nomination']),[row],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=13)


def test_finite_sparse_scores_are_not_reinterpreted_as_safe_integer_counts():
    nomination=expand(FIXTURE['nomination'])
    nomination.update(branch='sparse',score_kind='dot_product',score=1e200)
    assert verify_source(nomination,[expand(FIXTURE['base_row'])],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=13).state=='verified'


@pytest.mark.parametrize('buffer',['bad',b'bad',memoryview(b'abcdefghijkl').cast('B',shape=(3,4)),memoryview(b'abcdefghijkl').cast('I')])
def test_denied_corrupt_driver_buffers_are_integrity_failures(buffer):
    row=expand(FIXTURE['base_row'])
    row['grant_ids']=[];row['principal_ids']=[]
    row['canonical_utf8']=buffer
    with pytest.raises(IntegrityViolation):verify_source(expand(FIXTURE['nomination']),[row],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=13)


def test_denied_null_case_row_retains_zero_loaded_bytes():
    row=expand(FIXTURE['base_row'])
    row['grant_ids']=[];row['principal_ids']=[]
    row['canonical_utf8']=row['excerpt_utf8']=None
    result=verify_source(expand(FIXTURE['nomination']),[row],FIXTURE['request'],FIXTURE['scope'],CONFIG,max_source_bytes=12)
    assert result.state=='unavailable' and result.source_bytes==0
