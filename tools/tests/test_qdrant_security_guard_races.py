"""Race protocol and authority SQL wiring; doubles do not prove SQL atomicity."""
import asyncio
from copy import deepcopy
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import qdrant_security_guard_races as races
from qdrant_writer_cases import writer_input
from qdrant_publication_schema import seed_records


def dataset(document_id='guard-race-test'):
    inputs=writer_input()
    inputs['stage']['intent']['document_id']=document_id
    inputs['stage']['manifest']['document_id']=document_id
    records=seed_records()
    records['document']['document_id']=document_id
    records['intent']['document_id']=document_id
    arguments=('instance-fixture','namespace','storage','supervisor','recovery',2,
        inputs['scope']['tenant_id'],inputs['stage']['intent']['collection'],document_id,
        inputs['stage']['intent']['intent_id'],'00000000-0000-4000-8000-000000000001',
        'security-intent','a'*64,None,'auth-2',2,[],[],None,None,None,False)
    return dict(arguments=arguments,inputs=inputs,records=records,dispatch_id='guard-race-dispatch',
        scope=dict(inputs['scope'],authorization_revision='auth-2'))


def datasets():
    return {name:dataset('guard-race-'+name) for name in ('commit','post_wait','abort','lost')}


def test_race_checks_and_guard_signature_are_fixed_and_sql_only():
    assert type(races.RACE_CHECKS) is tuple and len(races.RACE_CHECKS)==len(set(races.RACE_CHECKS))==6
    assert all(re.fullmatch('[a-z][a-z0-9_]{0,127}',check) for check in races.RACE_CHECKS)
    assert races.GUARD_SQL=='SELECT cragkit_qdrant.lock_current_security('+','.join(['%s']*22)+')'
    assert all('receipt' not in check and 'purge' not in check for check in races.RACE_CHECKS)


def test_dataset_binding_refuses_wrong_targets_shared_docs_and_stale_scope():
    races._validate_datasets(datasets())
    wrong=datasets();wrong['abort']=deepcopy(wrong['commit'])
    with pytest.raises(ValueError):races._validate_datasets(wrong)
    wrong=datasets();wrong['abort']['scope']['authorization_revision']='auth-1'
    with pytest.raises(ValueError):races._validate_datasets(wrong)
    wrong=datasets();wrong['commit']['arguments']=tuple(range(21))
    with pytest.raises(ValueError):races._validate_datasets(wrong)
    wrong=datasets();wrong['commit']['inputs']['stage']['intent']['document_id']='foreign'
    with pytest.raises(ValueError):races._validate_datasets(wrong)


def test_invalid_dataset_fails_closed_before_any_database_access():
    class Forbidden:
        @property
        def admin(self):raise AssertionError('must validate before borrowing admin')
    async def run():
        with pytest.raises(races.NativeSecurityGuardRaceFailure) as caught:
            await races.run_guard_races(Forbidden(),{})
        assert caught.value.observation==dict(ok=False,step=0,error='InvalidRequest')
    asyncio.run(run())


def test_failure_observation_is_closed_copied_and_never_formats_source_errors():
    for label in races.ERRORS:
        if label=='cleanup_failed':continue
        original=dict(ok=False,step=0,error=label)
        failure=races.NativeSecurityGuardRaceFailure(original)
        original['error']='PRIVATE'
        assert failure.observation==dict(ok=False,step=0,error=label)
        assert str(failure)=='security_guard_native_race_failed'
    for primary in (None,'internal','DeadlineExceeded'):
        assert races.NativeSecurityGuardRaceFailure(dict(ok=False,step=6,error='cleanup_failed',primary=primary)).observation['primary']==primary
    for value in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=7,error='internal'),
            dict(ok=False,step=0,error='PRIVATE'),dict(ok=False,step=0,error='internal',message='PRIVATE'),
            dict(ok=False,step=0,error='cleanup_failed',primary='PRIVATE')):
        with pytest.raises(ValueError):races.NativeSecurityGuardRaceFailure(value)


def test_authority_record_uses_canonical_hash_and_monotonic_complete_security_tuple():
    from hashlib import sha256
    value=dataset()
    before=deepcopy(value)
    record,encoded=races._authority_record(value)
    assert record['action']=='update_authorization'
    assert record['expected_authorization_revision']=='auth-2' and record['expected_mutation_epoch']==2
    assert record['authorization']==dict(authorization_revision='auth-3',principal_ids=[],grant_ids=[],
        language=None,kind=None,tag='auth-3',tombstoned=False)
    assert encoded.sha256==sha256(encoded.encoded_bytes).hexdigest()
    assert value==before


def test_restricted_authority_sequence_binds_new_intent_and_locks_before_complete_update(monkeypatch):
    events=[]
    value=dataset()
    class Cursor:
        def __init__(self,rows):self.rows=rows
        async def fetchall(self):return self.rows
    class Connection:
        async def execute(self,sql,params=(),**options):
            events.append((sql,params))
            if sql.startswith('SELECT authorization_revision'):
                return Cursor([('auth-2',2,False)])
            if sql.startswith('UPDATE cragkit_qdrant.documents'):
                return Cursor([(value['arguments'][8],)])
            return Cursor([])
    async def bind(connection,records,**kwargs):events.append(('bind',kwargs))
    monkeypatch.setattr(races,'bind_scope',bind)
    asyncio.run(races._authority(Connection(),value))
    statements=[sql for sql,_ in events]
    lock=next(index for index,sql in enumerate(statements) if 'FOR UPDATE' in sql)
    update=next(index for index,sql in enumerate(statements) if sql.startswith('UPDATE cragkit_qdrant.documents'))
    assert lock<update<statements.index('COMMIT')
    bound=next(params for sql,params in events if sql=='bind')
    inserted=next(params for sql,params in events if sql.startswith('INSERT INTO cragkit_qdrant.publication_intents'))
    assert bound['intent_id']==inserted[3] and bound['authorization_revision']=='auth-2'
    document_params=events[update][1]
    assert document_params[:8]==('auth-3',3,[],[],None,None,'auth-3',False)
    assert document_params[-2:]==('auth-2',2)
    assert any("state='authority_committed',authority_committed=true" in sql for sql in statements)
    assert not any('replica_complete=true' in sql or 'purge_complete=true' in sql for sql in statements)


def test_authority_fence_failure_never_updates_or_commits(monkeypatch):
    statements=[]
    class Cursor:
        async def fetchall(self):return [('auth-3',3,False)]
    class Connection:
        async def execute(self,sql,params=(),**options):statements.append(sql);return Cursor()
    async def bind(*args,**kwargs):pass
    monkeypatch.setattr(races,'bind_scope',bind)
    with pytest.raises(RuntimeError):asyncio.run(races._authority(Connection(),dataset()))
    assert not any(sql.startswith('UPDATE ') or sql=='COMMIT' for sql in statements)
