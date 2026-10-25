"""Full verified sources are opt-in and absent from serialized fetch results."""
import hashlib

import pytest

from cragkit._postgres_session import LexicalCandidate
from cragkit._postgres_source import verify_source
from cragkit.errors import IntegrityViolation, InvalidRequest, UnsupportedCapability


def data():
    text='Café🙂'
    canonical=text+' parent marker'
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    candidate=LexicalCandidate(tenant_id='t',collection='c',document_id='d',revision_id='r',
        generation_id='g',chunk_id='chunk',start_byte=0,end_byte=len(text.encode()),text_sha256=digest(text),score=1)
    row=('t','c','d','r','g','chunk',digest(canonical),len(canonical.encode()),canonical,
         0,len(text.encode()),len(text.encode()),text,digest(text),'fixture','native_fts.v1',True)
    return candidate,row,canonical


def test_opt_in_source_is_verified_and_not_serialized():
    candidate,row,canonical=data()
    default=verify_source(candidate,[row],100)
    with pytest.raises(UnsupportedCapability):default.source_snapshot()
    fetched=verify_source(candidate,[row],100,include_source=True)
    assert fetched.source_snapshot()['text']==canonical
    assert 'parent marker' not in fetched.model_dump_json()
    assert 'parent marker' not in repr(fetched)
    assert fetched.model_dump()==default.model_dump()


def test_source_integrity_and_budget_failure_cannot_return_snapshot():
    candidate,row,_=data()
    corrupt=list(row);corrupt[8]='modified'
    with pytest.raises(IntegrityViolation):verify_source(candidate,[tuple(corrupt)],100,include_source=True)
    unloaded=list(row);unloaded[8]=None
    fetched=verify_source(candidate,[tuple(unloaded)],0,include_source=True)
    with pytest.raises(UnsupportedCapability):fetched.source_snapshot()
    with pytest.raises(InvalidRequest):verify_source(candidate,[],100,include_source=1)
