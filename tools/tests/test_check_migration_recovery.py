"""Bounded MRR upgrade control failures; no database, artifacts or child processes."""
import asyncio
import json
from pathlib import Path
import sys

import psycopg
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_migration_recovery as rehearsal


def test_diagnostics_exclude_exception_text_and_unbounded_sqlstate():
    class PrivateError(Exception):
        sqlstate='private connection details'
    value = rehearsal.safe_diagnostic(PrivateError('private source text'))
    assert value == dict(exception_type='OtherError',sqlstate=None,code_frame=None)
    assert 'private' not in json.dumps(value)
    error = psycopg.errors.UndefinedTable('private SQL')
    value = rehearsal.safe_diagnostic(error)
    assert value['exception_type'] == 'UndefinedTable' and value['sqlstate'] == '42P01'
    assert 'private' not in json.dumps(value)


@pytest.mark.parametrize('message,expected',[
    ('function tsvector_send(tsvector) does not exist',dict(function='tsvector_send',argument_types=['tsvector'])),
    ('function pg_catalog.encode(bytea, unknown) does not exist',dict(function='pg_catalog.encode',argument_types=['bytea','unknown'])),
    ('function private_source(text) does not exist',None),
    ('function encode(private_credential) does not exist',None),
    ('function private_schema.encode(text) does not exist',None),
    ('function encode(text) does not exist; private SQL',None),
])
def test_undefined_function_diagnostic_emits_only_fixed_function_and_type_names(message,expected):
    class UndefinedFunction(Exception):
        sqlstate='42883'
        class Diagnostic:
            message_primary=message
        diag=Diagnostic()
    error=UndefinedFunction('private source and connection text')
    assert rehearsal.safe_function_signature(error)==expected
    assert 'private' not in json.dumps(rehearsal.safe_diagnostic(error))


def test_observation_pause_is_after_pinned_writes_and_before_commit():
    original = rehearsal.profile_upgrade_script(apply=True)
    interrupted = rehearsal.pause_before_commit(original)
    assert interrupted.replace('\nSELECT pg_sleep(20);','') == original
    assert interrupted.index('END $cragkit_profile$;') < interrupted.index('SELECT pg_sleep(20);')
    assert interrupted.index('SELECT pg_sleep(20);') < interrupted.index('\nCOMMIT;')


@pytest.mark.parametrize('script',['BEGIN; SELECT 1;', 'BEGIN;\nCOMMIT;\nCOMMIT;',
    'BEGIN; SELECT pg_sleep(1);\nCOMMIT;'])
def test_ambiguous_transaction_or_existing_pause_is_refused(script):
    with pytest.raises(RuntimeError,match='^migration_recovery_invalid$'):
        rehearsal.pause_before_commit(script)


@pytest.mark.parametrize('upgraded',[False,True])
def test_historical_compatibility_requires_real_lexical_and_specific_vector_outcome(upgraded):
    value = dict(runtime='python',version='0.0.0',installed_bytes_verified=True,
        lexical='complete',identifier='complete',dense='unsupported_capability' if upgraded else 'complete')
    rehearsal.validate_old(value,'python',upgraded=upgraded)
    for field,invalid in [('version','1.0.0rc1'),('runtime','node'),('installed_bytes_verified',False),
            ('lexical','unsupported_capability'),('dense','provider_unavailable')]:
        with pytest.raises(RuntimeError):
            rehearsal.validate_old({**value,field:invalid},'python',upgraded=upgraded)
    if upgraded:
        with pytest.raises(RuntimeError):
            rehearsal.validate_old({**value,'dense':'complete'},'python',upgraded=True)


@pytest.mark.parametrize('runtime',['python','node'])
def test_unmodified_upgrade_keeps_typed_refusals_separate_from_repaired_acceptance(runtime):
    value=dict(runtime=runtime,version='0.0.0',installed_bytes_verified=True,
        lexical='unsupported_capability',identifier='unsupported_capability',dense='complete')
    rehearsal.validate_old(value,runtime,upgraded=False,unmodified=True)
    with pytest.raises(RuntimeError):
        rehearsal.validate_old(value,runtime,upgraded=False)
    with pytest.raises(RuntimeError):
        rehearsal.validate_old({**value,'lexical':'provider_unavailable'},runtime,upgraded=False,unmodified=True)


@pytest.mark.parametrize('runtime,version',[('python','1.0.0rc1'),('node','1.0.0-rc.1')])
def test_current_candidate_accepts_fake_dense_after_profile_upgrade(runtime,version):
    value=dict(runtime=runtime,version=version,installed_bytes_verified=True,
        lexical='complete',identifier='complete',dense='complete')
    rehearsal.validate_package(value,runtime,expected_version=version,upgraded=True)
    with pytest.raises(RuntimeError):
        rehearsal.validate_package({**value,'dense':'unsupported_capability'},runtime,
            expected_version=version,upgraded=True)
    with pytest.raises(RuntimeError):
        rehearsal.validate_package({**value,'version':'0.0.0'},runtime,
            expected_version=version,upgraded=True)


def test_termination_targets_only_owned_backend_after_observed_pause(monkeypatch):
    async def scenario():
        events, pending = [], asyncio.get_running_loop().create_future()
        class Worker:
            class Info:
                backend_pid = 31415
            info, closed = Info(), False
            async def execute(self,script):
                events.append('writes_started')
                await pending
            async def close(self):
                self.closed = True
                events.append('closed')
        worker = Worker()
        class Cursor:
            def __init__(self,value): self.value=value
            async def fetchone(self): return self.value
        class Observer:
            async def execute(self,statement,args):
                assert args == (31415,)
                if 'pg_stat_activity' in statement:
                    paused = 'writes_started' in events
                    if paused: events.append('pause_observed')
                    return Cursor(('active','PgSleep' if paused else None))
                assert statement == 'SELECT pg_terminate_backend(%s)'
                assert events[-1] == 'pause_observed'
                events.append('terminated_owned_pid')
                worker.closed = True
                pending.set_exception(psycopg.OperationalError('private synthetic diagnostic'))
                return Cursor((True,))
        async def connect(config): return worker
        monkeypatch.setattr(rehearsal,'connect',connect)
        outcome = await rehearsal.terminate_upgrade({},Observer())
        assert outcome == dict(observed_after_writes=True,wait_event='PgSleep',backend_terminated=True)
        assert events == ['writes_started','pause_observed','terminated_owned_pid','closed']
    asyncio.run(scenario())


def test_finished_upgrade_cannot_be_reported_as_interrupted(monkeypatch):
    async def scenario():
        class Worker:
            class Info:
                backend_pid=31415
            info,closed=Info(),False
            async def execute(self,script): return None
            async def close(self): self.closed=True
        worker=Worker()
        class Cursor:
            async def fetchone(self): return ('idle',None)
        class Observer:
            async def execute(self,statement,args):
                assert 'pg_stat_activity' in statement
                return Cursor()
        async def connect(config): return worker
        monkeypatch.setattr(rehearsal,'connect',connect)
        with pytest.raises(RuntimeError):
            await rehearsal.terminate_upgrade({},Observer())
        assert worker.closed
    asyncio.run(scenario())
