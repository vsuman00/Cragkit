"""Pure QCC-r1 nomination handoff; no storage or model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cragkit.contracts import parse_request,parse_scope
from cragkit.corrective import CorrectiveRetriever,_candidate
from cragkit.errors import IntegrityViolation

FIXTURE=json.loads((Path(__file__).resolve().parents[3]/'contracts/fixtures/qdrant_sources.json').read_text())
FIXTURE['request']=dict(FIXTURE['request'],output_profile=dict(renderer='cragkit.context.v2'))


def expand(value):
    if isinstance(value,str) and value.startswith('$ref:'):
        target=FIXTURE
        for key in value[5:].split('.'):target=target[key]
        return expand(target)
    if isinstance(value,dict):return {key:expand(item) for key,item in value.items()}
    if isinstance(value,list):return [expand(item) for item in value]
    return value


def candidate(branch='dense',score=-.5):
    nomination=expand(FIXTURE['nomination'])
    nomination.update(branch=branch,score=score,score_kind='cosine_similarity' if branch=='dense' else 'dot_product')
    fields=('tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','text_sha256')
    return dict(**{key:nomination['payload'][key] for key in fields},backend='qdrant',score=score,nomination=nomination)


@pytest.mark.parametrize('branch,score',[('dense',-.5),('dense',1.),('sparse',-20.),('sparse',20.)])
def test_native_score_and_profiles_survive_without_source_authority(branch,score):
    class Backend:
        async def search(self,request,**options):return dict(candidates=[candidate(branch,score)],degraded=False)
        async def capture(self,items,**options):
            assert items[0].score==items[0].nomination.score==score
            assert items[0].nomination.payload.dense_profile.profile_id=='fake_embedding_1536_v1'
            return dict(evidence=[],sources=[],source_bytes=0,stale=False,budget_exhausted=False)
    async def scenario():
        result=await CorrectiveRetriever(Backend(),batch_size=1).retrieve(FIXTURE['request'],scope=FIXTURE['scope'],deadline=asyncio.get_running_loop().time()+2)
        assert result['result']['status']=='insufficient' and result['result']['evidence']==[]
        assert 'nomination' not in json.dumps(result['result'])
    asyncio.run(scenario())


@pytest.mark.parametrize('field',['document_id','text_sha256','start_byte','score','point_id','kind','dense_bound'])
def test_mismatched_nomination_handoff_fails_integrity(field):
    value=candidate()
    if field=='point_id':value['nomination']['point_id']='00000000-0000-5000-8000-000000000001'
    elif field=='kind':value['nomination']['score_kind']='dot_product'
    elif field=='dense_bound':value['score']=value['nomination']['score']=1.01
    elif field=='score':value['score']=.25
    elif field=='text_sha256':value[field]='0'*64
    elif field=='start_byte':value[field]+=1
    else:value[field]='different-document'
    with pytest.raises(IntegrityViolation):_candidate(value,parse_request(FIXTURE['request']),parse_scope(FIXTURE['scope']))


def test_handoff_snapshots_nested_nomination_and_refuses_foreign_scope():
    value=candidate();accepted=_candidate(value,parse_request(FIXTURE['request']),parse_scope(FIXTURE['scope']))
    assert _candidate(accepted,parse_request(FIXTURE['request']),parse_scope(FIXTURE['scope']))==accepted
    value['nomination']['payload']['principal_ids'].clear()
    assert accepted.nomination.payload.principal_ids==('reader-a',)
    scope=dict(FIXTURE['scope'],tenant_id='foreign')
    with pytest.raises(IntegrityViolation):_candidate(deepcopy(value),parse_request(FIXTURE['request']),parse_scope(scope))
