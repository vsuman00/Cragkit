"""Pure fake-transport coverage; these observations grant no physical authority."""
import asyncio
import copy
from dataclasses import replace
import json
from types import MappingProxyType

import pytest

from cragkit._qdrant_contract import CandidatePayload, QdrantConfig, parse_model
from cragkit._qdrant_manifest import encode_manifest
from cragkit._qdrant_reconciliation import ExpectedPoint
from cragkit._qdrant_security_readback import (SecurityReadbackBudget, security_readback_budget,
    inspect_security_readback, verify_security_readback)
from cragkit._qdrant_writer_contract import context, prepare_stage, stage_data
from cragkit.embeddings import OPENAI_PROFILE
from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from test_qdrant_manifest import reidentify
from test_qdrant_reconciliation import Handle
from test_qdrant_writer import config, ctx, run_async, stage_input


def deadline():return asyncio.get_running_loop().time()+5


def fixture(*,empty=False,tombstoned=False):
    points = []
    for index in range(2):
        raw = stage_input();manifest = raw['manifest']
        manifest.update(revision_id=f'revision-{index}',generation_id=f'generation-{index}')
        for member in manifest['members']:reidentify(manifest,member)
        raw['intent']['manifest_sha256'] = encode_manifest(manifest,raw['canonical_text']).sha256
        graph = stage_data(prepare_stage(raw))
        for member,dense,sparse in zip(graph.manifest.members,graph.dense,graph.sparse,strict=True):
            payload = {key:manifest[key] for key in ('backend_namespace','physical_collection','collection_incarnation',
                'tenant_id','collection','document_id','revision_id','generation_id','source_sha256','dense_profile','sparse_profile')}
            payload.update(chunk_id=member.chunk_id,start_byte=member.start_byte,end_byte=member.end_byte,
                text_sha256=member.text_sha256,dense_profile_id=manifest['dense_profile']['profile_id'],
                sparse_profile_id=manifest['sparse_profile']['profile_id'],authorization_revision='auth-1',
                principal_ids=['reader-a'],grant_ids=['grant-a'],language='en',kind='guide',tag='reference')
            points.append(ExpectedPoint(member.point_id,parse_model(CandidatePayload,payload),dense.encoded,sparse.encoded))
    points = tuple(sorted(points,key=lambda point:point.point_id)) if not empty else ()
    expected = MappingProxyType(dict(context=ctx(),point_ids=tuple(point.point_id for point in points),points=points,tombstoned=tombstoned))
    observed = [dict(id=point.point_id,payload=point.payload.model_dump(mode='json'),
        vector=dict(dense=list(point.dense.values),sparse=dict(indices=list(point.sparse.indices),values=list(point.sparse.values))))
        for point in points]
    return expected,observed


@run_async
async def test_multigeneration_missing_and_stale_diagnostics_are_frozen_without_authority():
    expected,observed = fixture()
    missing = observed.pop()['id'];stale = observed[0]['id']
    observed[0]['payload'].update(authorization_revision='old-auth',principal_ids=['old-reader'],grant_ids=['old-grant'],
        language='fr',kind='old-kind',tag='old-tag')
    handle = Handle(observed)
    result = await inspect_security_readback(handle,config(),expected,deadline=deadline())
    assert dict(result) == dict(present_ids=tuple(sorted(point['id'] for point in observed)),
        missing_ids=(missing,),stale_ids=(stale,))
    with pytest.raises(TypeError):result['missing_ids'] = ()
    assert handle.close_count == 0
    with pytest.raises(IntegrityViolation):
        await verify_security_readback(Handle(observed),config(),expected,deadline=deadline())
    scroll = [body for _,path,body in handle.calls if path.endswith('/scroll')]
    assert {item['key'] for item in scroll[0]['filter']['must']} == {
        'backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id'}


@run_async
async def test_exact_current_tombstone_and_empty_scope_require_full_document_enumeration():
    expected,observed = fixture()
    assert await verify_security_readback(Handle(observed),config(),expected,deadline=deadline()) is None
    tombstone = dict(expected,tombstoned=True)
    assert (await inspect_security_readback(Handle(observed),config(),tombstone,deadline=deadline()))['present_ids']
    with pytest.raises(IntegrityViolation):
        await verify_security_readback(Handle(observed),config(),tombstone,deadline=deadline())
    assert await verify_security_readback(Handle([]),config(),tombstone,deadline=deadline()) is None
    empty,_ = fixture(empty=True)
    handle = Handle([])
    assert await verify_security_readback(handle,config(),empty,deadline=deadline()) is None
    assert len(handle.calls) == 1 and handle.calls[0][1].endswith('/scroll')
    with pytest.raises(IntegrityViolation):
        await inspect_security_readback(Handle(observed),config(),empty,deadline=deadline())


@pytest.mark.parametrize('mode',['duplicates','order'])
@run_async
async def test_acl_order_and_duplicates_are_stale_and_get_scroll_representation_drift_fails(mode):
    expected,observed = fixture()
    if mode == 'order':
        expected = dict(expected,points=tuple(replace(point,payload=point.payload.model_copy(
            update=dict(grant_ids=('grant-a','grant-b')))) for point in expected['points']))
        for point in observed:point['payload']['grant_ids'] = ['grant-b','grant-a']
    else:
        for point in observed:point['payload']['grant_ids'] *= 2
    result = await inspect_security_readback(Handle(observed),config(),expected,deadline=deadline())
    assert result['stale_ids'] == expected['point_ids']
    with pytest.raises(IntegrityViolation):
        await verify_security_readback(Handle(observed),config(),expected,deadline=deadline())
    handle = Handle(observed)
    def get_patch(points):
        points[0]['payload']['grant_ids'] = ['grant-a','grant-b'] if mode == 'order' else ['grant-a']
        return points
    handle.get_patch = get_patch
    with pytest.raises(IntegrityViolation):
        await inspect_security_readback(handle,config(),expected,deadline=deadline())


@pytest.mark.parametrize('fault',['extra','unknown_payload','immutable','profile','dense','sparse','vector_name','shard','duplicate','get_membership'])
@run_async
async def test_corrupt_or_unexpected_points_are_never_repair_diagnostics(fault):
    expected,observed = fixture();handle = Handle(observed)
    if fault == 'extra':
        extra = copy.deepcopy(observed[0]);extra['id'] = '00000000-0000-4000-8000-000000000099';observed.append(extra)
    elif fault == 'unknown_payload':observed[0]['payload']['private_text'] = 'private'
    elif fault == 'immutable':observed[0]['payload']['source_sha256'] = '0'*64
    elif fault == 'profile':observed[0]['payload']['dense_profile']['model'] = 'different-model'
    elif fault == 'dense':observed[0]['vector']['dense'] = [-value for value in observed[0]['vector']['dense']]
    elif fault == 'sparse':observed[0]['vector']['sparse']['values'][0] += 1
    elif fault == 'vector_name':observed[0]['vector']['extra'] = []
    elif fault == 'shard':observed[0]['shard_key'] = 'foreign'
    elif fault == 'duplicate':handle.get_patch = lambda points:points+[copy.deepcopy(points[0])]
    else:
        wrong = copy.deepcopy(observed[0]);wrong['id'] = '00000000-0000-4000-8000-000000000099'
        handle.get_patch = lambda points:[wrong]
    with pytest.raises(IntegrityViolation):
        await inspect_security_readback(handle,config(),expected,deadline=deadline())


@pytest.mark.parametrize('fault',['empty_nonfinal','offset','repeated_offset','shape','missing_eof'])
@run_async
async def test_scroll_requires_bounded_valid_offsets_complete_membership_and_eof(fault):
    expected,observed = fixture();handle = Handle(observed)
    def patch(result,page):
        if fault == 'empty_nonfinal':return dict(points=[],next_page_offset=observed[0]['id'])
        if fault == 'offset':return dict(result,next_page_offset='not-a-uuid')
        if fault == 'shape':return dict(result,unknown='private')
        if fault == 'missing_eof':return dict(result,next_page_offset=observed[-1]['id'])
        selected = observed[:2] if page == 1 else observed[2:]
        return dict(points=copy.deepcopy(selected),next_page_offset=observed[1]['id'])
    handle.scroll_patch = patch
    with pytest.raises((IntegrityViolation,ProviderUnavailable)):
        await inspect_security_readback(handle,config(),expected,deadline=deadline())


@pytest.mark.parametrize('fault',['ids_order','duplicate','scope','profile','point_id','tombstone','config','forged_vector'])
@run_async
async def test_expected_validation_precedes_http(fault):
    expected,observed = fixture();data = dict(expected);configuration = config();handle = Handle(observed)
    if fault == 'ids_order':data['point_ids'] = tuple(reversed(data['point_ids']))
    elif fault == 'duplicate':data['point_ids'] = (data['point_ids'][0],)*4
    elif fault == 'scope':
        target = copy.deepcopy(ctx());target['document_id'] = 'foreign';data['context'] = target
    elif fault == 'profile':configuration['dense_profile'] = {**configuration['dense_profile'],'model':'different-model'}
    elif fault == 'point_id':data['points'] = (replace(data['points'][0],point_id='00000000-0000-4000-8000-000000000099'),*data['points'][1:])
    elif fault == 'tombstone':data['tombstoned'] = 1
    elif fault == 'config':configuration['unknown'] = 'private'
    else:data['points'] = (replace(data['points'][0],dense=replace(data['points'][0].dense)),*data['points'][1:])
    with pytest.raises(UnsupportedCapability if fault == 'profile' else InvalidRequest):
        await inspect_security_readback(handle,configuration,data,deadline=deadline())
    assert handle.calls == []


@run_async
async def test_typed_writer_config_and_private_projection_context_are_accepted():
    expected,observed = fixture()
    typed = parse_model(QdrantConfig,config())
    projection_subset = MappingProxyType(dict(expected,context=context(expected['context'])))
    assert await verify_security_readback(Handle(observed),typed,projection_subset,deadline=deadline()) is None


@pytest.mark.parametrize('profile',['fake','openai_dense','unknown_dense','unknown_sparse','openai_sparse'])
@run_async
async def test_supported_configuration_is_checked_even_for_empty_expected_inventory(profile):
    expected,_ = fixture(empty=True);configuration = config();handle = Handle([])
    if profile in ('openai_dense','openai_sparse'):
        configuration['dense_profile'] = OPENAI_PROFILE.model_dump()
        if profile == 'openai_dense':configuration['sparse_profile'] = None
    elif profile == 'unknown_dense':configuration['dense_profile'] = {**configuration['dense_profile'],'model':'unsupported'}
    elif profile == 'unknown_sparse':configuration['sparse_profile'] = {**configuration['sparse_profile'],'revision':'unsupported'}
    if profile in ('fake','openai_dense'):
        await verify_security_readback(handle,configuration,expected,deadline=deadline())
        assert len(handle.calls) == 1
    else:
        with pytest.raises(UnsupportedCapability):
            await inspect_security_readback(handle,configuration,expected,deadline=deadline())
        assert handle.calls == []


def test_budget_is_native_readonly_uncopyable_and_cannot_be_reset():
    budget = security_readback_budget()
    assert (budget.remaining_bytes,budget.remaining_calls) == (8388608,513)
    assert security_readback_budget(budget) is budget
    with pytest.raises(InvalidRequest):budget.__init__()
    with pytest.raises((TypeError,InvalidRequest)):copy.copy(budget)
    with pytest.raises(AttributeError):budget.remaining_calls = 513
    class Subclass(SecurityReadbackBudget):pass
    with pytest.raises(InvalidRequest):Subclass()
    for fake in (object(),SecurityReadbackBudget.__new__(SecurityReadbackBudget)):
        with pytest.raises(InvalidRequest):security_readback_budget(fake)


@run_async
async def test_attempt_limit_is_shared_across_513_cheap_empty_passes():
    expected,_ = fixture(empty=True);handle = Handle([]);budget = SecurityReadbackBudget()
    for _ in range(513):
        assert not (await inspect_security_readback(handle,config(),expected,deadline=deadline(),budget=budget))['present_ids']
    assert budget.remaining_calls == 0 and len(handle.calls) == 513
    with pytest.raises(ProviderUnavailable):
        await verify_security_readback(handle,config(),expected,deadline=deadline(),budget=budget)
    assert len(handle.calls) == 513


@run_async
async def test_returned_malformed_bytes_charge_before_parsing_and_exhaustion_prevents_next_call():
    expected,_ = fixture(empty=True);budget = SecurityReadbackBudget()
    class Malformed:
        calls = 0
        async def request(self,*args,**options):
            self.calls += 1
            assert options['max_response_bytes'] == 1048576
            return b'!'+b' '*1048575
    handle = Malformed()
    for _ in range(8):
        with pytest.raises(IntegrityViolation):
            await inspect_security_readback(handle,config(),expected,deadline=deadline(),budget=budget)
    assert budget.remaining_bytes == 0 and budget.remaining_calls == 505
    with pytest.raises(ProviderUnavailable):
        await inspect_security_readback(handle,config(),expected,deadline=deadline(),budget=budget)
    assert handle.calls == 8


@pytest.mark.parametrize('mode',['failure','cancel','deadline','suppressed_cancel'])
@run_async
async def test_failed_cancelled_and_expired_attempts_are_charged_without_later_http(mode):
    expected,_ = fixture(empty=True);budget = SecurityReadbackBudget();entered = asyncio.Event()
    class Stalled:
        calls = 0
        async def request(self,*args,**options):
            self.calls += 1;entered.set()
            if mode == 'failure':raise RuntimeError('PRIVATE_TRANSPORT_TEXT')
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                if mode != 'suppressed_cancel':raise
                return b'{"status":"ok","result":{"points":[],"next_page_offset":null}}'
    handle = Stalled()
    task = asyncio.create_task(inspect_security_readback(handle,config(),expected,
        deadline=asyncio.get_running_loop().time()+(.01 if mode == 'deadline' else 5),budget=budget))
    await entered.wait()
    if mode in ('cancel','suppressed_cancel'):task.cancel()
    with pytest.raises(ProviderUnavailable if mode == 'failure' else DeadlineExceeded if mode == 'deadline' else asyncio.CancelledError) as error:
        await task
    assert 'PRIVATE' not in str(error.value) and budget.remaining_calls == 512 and handle.calls == 1


@run_async
async def test_storage_mutation_ack_shares_readback_call_and_byte_budget():
    from cragkit._qdrant_security_readback import security_storage_request
    class Storage:
        calls=0
        async def request(self,method,path,*,body,deadline,max_response_bytes):
            self.calls+=1
            assert method in ('POST','PUT') and body==b'{}' and max_response_bytes<=1048576
            return b'{}'
    transport=Storage();budget=SecurityReadbackBudget();limit=deadline()
    for _ in range(512):
        await security_storage_request(transport,'POST','/read',b'{}',deadline=limit,budget=budget)
    assert await security_storage_request(transport,'PUT','/write',b'{}',deadline=limit,budget=budget)==b'{}'
    assert budget.remaining_calls==0 and budget.remaining_bytes==8388608-1026
    with pytest.raises(ProviderUnavailable):
        await security_storage_request(transport,'POST','/read',b'{}',deadline=limit,budget=budget)
    assert transport.calls==513
