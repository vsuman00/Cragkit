"""The example must enforce provenance and caller-bound access before release."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import time

import pytest

from cragkit.contracts import RetrievalResult
from cragkit.errors import IntegrityViolation,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability

path=Path(__file__).resolve().parents[3]/'examples/existing_index.py'
spec=importlib.util.spec_from_file_location('existing_index_example',path)
example=importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def retrieve(adapter,query='retries'):
    return asyncio.run(adapter.retrieve(query,deadline=time.monotonic()+5))


def test_positive_maps_exact_multibyte_source_to_native_result_without_claiming_coverage():
    records,source,scope=example.demo_data()
    calls=[]
    def resolve(*key):calls.append(key);return deepcopy(source)
    adapter=example.ExistingIndexAdapter(records,resolve,scope=scope,collection='docs',
        required_filters=[dict(op='eq',field='tag',value='public')])
    result=retrieve(adapter)
    assert isinstance(result,RetrievalResult)
    assert result.status=='partial' and result.execution=='complete'
    assert result.evidence[0].text=='Café retries: at most three.'
    item=result.evidence[0];raw=source['text'].encode()
    assert raw[item.start_byte:item.end_byte].decode()==item.text
    assert item.source_sha256==sha256(raw).hexdigest()
    assert item.text_sha256==sha256(item.text.encode()).hexdigest()
    assert calls==[('tenant-a','docs','retry','r1')]*2
    assert result.usage.provider_calls==0 and result.usage.context_counting=='estimated'
    assert result.facets[0].state=='unknown' and result.limitations[0].code=='coverage_unknown'


def test_foreign_tenant_never_reaches_source_resolver_even_if_query_names_it():
    records,source,scope=example.demo_data();records[0]['tenant_id']='tenant-b';records[0]['search_text']+=' tenant-b'
    def forbidden(*args):pytest.fail('foreign source resolver called')
    result=retrieve(example.ExistingIndexAdapter(records,forbidden,scope=scope,collection='docs'),'tenant-b retries')
    assert result.status=='insufficient' and not result.evidence


def test_fresh_source_reauthorization_rejects_wrong_tenant_and_required_filter_change():
    for change in (dict(tenant_id='tenant-b'),dict(tag='private'),dict(principal_ids=[],grant_ids=[])):
        records,source,scope=example.demo_data();source.update(change)
        adapter=example.ExistingIndexAdapter(records,lambda *args:source,scope=scope,collection='docs',
            required_filters=[dict(op='eq',field='tag',value='public')])
        with pytest.raises(UnauthorizedScope):retrieve(adapter)


def test_packing_checkpoint_cannot_release_a_source_revoked_before_return():
    records,source,scope=example.demo_data();calls=[]
    def resolve(*args):
        calls.append(args)
        return deepcopy(source) if len(calls)==1 else dict(source,principal_ids=[],grant_ids=[])
    with pytest.raises(UnauthorizedScope):retrieve(example.ExistingIndexAdapter(records,resolve,scope=scope,collection='docs'))
    assert len(calls)==2


@pytest.mark.parametrize('missing',['revision_id','source_sha256','text_sha256'])
def test_missing_provenance_fails_before_source_resolution(missing):
    records,source,scope=example.demo_data();del records[0][missing]
    def forbidden(*args):pytest.fail('malformed provenance resolved')
    with pytest.raises(IntegrityViolation):retrieve(example.ExistingIndexAdapter(records,forbidden,scope=scope,collection='docs'))


def test_capability_refusals_happen_before_source_resolution():
    records,source,scope=example.demo_data()
    for options in (dict(mode='dense'),dict(required_filters=[dict(op='ne',field='tag',value='private')])):
        with pytest.raises(UnsupportedCapability):example.ExistingIndexAdapter(records,lambda *args:source,scope=scope,collection='docs',**options)
    with pytest.raises(UnsupportedCapability):example.ExistingIndexAdapter(records,None,scope=scope,collection='docs')
    with pytest.raises(ProviderUnavailable):retrieve(example.ExistingIndexAdapter(records,lambda *args:None,scope=scope,collection='docs'))
    def failed(*args):raise ConnectionError('PRIVATE source failure')
    with pytest.raises(ProviderUnavailable) as caught:retrieve(example.ExistingIndexAdapter(records,failed,scope=scope,collection='docs'))
    assert 'PRIVATE' not in str(caught.value)


def test_digest_and_utf8_boundary_corruption_never_release_text():
    records,source,scope=example.demo_data()
    altered=deepcopy(source);altered['text']='changed canonical bytes'
    with pytest.raises(IntegrityViolation):retrieve(example.ExistingIndexAdapter(records,lambda *args:altered,scope=scope,collection='docs'))
    records[0]['end_byte']=4
    records[0]['text_sha256']=sha256(source['text'].encode()[:4]).hexdigest()
    with pytest.raises(IntegrityViolation):retrieve(example.ExistingIndexAdapter(records,lambda *args:source,scope=scope,collection='docs'))


def test_caller_edits_to_index_and_filters_do_not_change_bound_snapshot():
    records,source,scope=example.demo_data();filters=[dict(op='eq',field='tag',value='public')]
    adapter=example.ExistingIndexAdapter(records,lambda *args:source,scope=scope,collection='docs',required_filters=filters)
    records[0]['tenant_id']='tenant-b';filters[0]['value']='private';scope['tenant_id']='tenant-b'
    assert retrieve(adapter).evidence[0].document_id=='retry'
