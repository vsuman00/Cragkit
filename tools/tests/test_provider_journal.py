"""Private offline recording and crash mechanics; no live quality evidence."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import provider_journal as journal
from provider_adapters import ProviderAdapterError, ProviderRequest, ReplaySend


def request():
    return ProviderRequest('openai','text-embedding-3-small',json.dumps(dict(
        model='text-embedding-3-small',dimensions=1536,encoding_format='float',input=['tiny public fixture'])).encode(),'a'*64)


def response():
    return json.dumps(dict(model='text-embedding-3-small',data=[dict(index=0,embedding=[1.]+[0.]*1535)],
        usage=dict(prompt_tokens=1,total_tokens=1))).encode()


def sealed(path, kind='mock'):
    with journal.EvaluationJournal(path,evidence_kind=kind) as tape:
        ticket=tape.begin(request(),10)
        assert tape.complete(ticket,response())==1
        tape.finish();tape.finish()
    return tape


def test_round_trip_private_files_duplicate_keys_and_explicit_mock(tmp_path):
    path=tmp_path/'tape'
    with journal.EvaluationJournal(path,evidence_kind='mock') as tape:
        for _ in range(2):
            ticket=tape.begin(request(),10)
            assert tape.complete(ticket,response())==1
        assert tape.snapshot()['completed']==2
        tape.finish()
        with pytest.raises(ProviderAdapterError):tape.begin(request(),10)
    assert path.stat().st_mode & 0o777 == 0o700
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in path.iterdir())
    rows=journal.load_recordings(path,require_live=False)
    assert len(rows)==2 and rows[0]==rows[1] and rows[0].response==response()
    with pytest.raises(ProviderAdapterError):journal.load_recordings(path)
    assert journal.load_recordings(sealed(tmp_path/'live','live')._directory)


@pytest.mark.parametrize('state',['pending','uncertain','failed','unsealed'])
def test_incomplete_states_never_replay(tmp_path,state):
    path=tmp_path/'tape'
    with journal.EvaluationJournal(path,evidence_kind='mock') as tape:
        ticket=tape.begin(request(),10)
        if state=='uncertain':tape.uncertain(ticket,'cancelled')
        if state in ('failed','unsealed'):tape.complete(ticket,response())
        if state=='failed':tape.fail('usage_overrun')
        if state!='unsealed':
            with pytest.raises(ProviderAdapterError):tape.finish()
    with pytest.raises(ProviderAdapterError):journal.load_recordings(path,require_live=False)


def test_ticket_identity_and_admission_limits(tmp_path):
    with journal.EvaluationJournal(tmp_path/'a',evidence_kind='mock') as a, journal.EvaluationJournal(tmp_path/'b',evidence_kind='mock') as b:
        ticket=a.begin(request(),10);other=b.begin(request(),10)
        for invalid in (object(),other,None):
            with pytest.raises(ProviderAdapterError):a.complete(invalid,response())
        with pytest.raises(ProviderAdapterError):a.begin(request(),10)
        a.complete(ticket,response())
        with pytest.raises(ProviderAdapterError):a.complete(ticket,response())
        for _ in range(59):a.complete(a.begin(request(),10),response())
        with pytest.raises(ProviderAdapterError):a.begin(request(),10)
        a.finish()
    assert len(journal.load_recordings(tmp_path/'a',require_live=False))==60


@pytest.mark.parametrize('value',[True,0,-1,2**31,float('inf'),10**1000])
def test_invalid_ceilings(tmp_path,value):
    with journal.EvaluationJournal(tmp_path/'tape',evidence_kind='mock') as tape:
        with pytest.raises(ProviderAdapterError):tape.begin(request(),value)
        assert tape.snapshot()['attempts']==0


@pytest.mark.parametrize('mutation',['extra','missing','response','metadata','mode','symlink','hardlink'])
def test_replay_rejects_corruption(tmp_path,mutation):
    path=tmp_path/'tape';sealed(path)
    if mutation=='extra':(path/'extra').write_text('x')
    if mutation=='missing':(path/'001.complete.json').unlink()
    if mutation=='response':(path/'001.response').write_bytes(b'{}')
    if mutation=='metadata':(path/'001.pending.json').write_text('{}')
    if mutation=='mode':(path/'001.response').chmod(0o644)
    if mutation=='symlink':
        raw=path/'001.response';raw.unlink();raw.symlink_to(tmp_path/'outside')
    if mutation=='hardlink':os.link(path/'001.response',tmp_path/'outside')
    with pytest.raises(ProviderAdapterError) as error:journal.load_recordings(path,require_live=False)
    assert error.value.__context__ is None


def test_directory_existing_symlink_and_modes(tmp_path):
    path=tmp_path/'tape';sealed(path)
    with pytest.raises(ProviderAdapterError):
        with journal.EvaluationJournal(path,evidence_kind='mock'):pass
    link=tmp_path/'link';link.symlink_to(path,target_is_directory=True)
    with pytest.raises(ProviderAdapterError):journal.load_recordings(link,require_live=False)
    path.chmod(0o755)
    with pytest.raises(ProviderAdapterError):journal.load_recordings(path,require_live=False)


@pytest.mark.parametrize('failure_point',['pending','response','complete','seal'])
def test_write_failure_never_seals_and_scrubs_context(tmp_path,monkeypatch,failure_point):
    original=journal._write
    def write(fd,name,value):
        if (failure_point=='pending' and name.endswith('.pending.json') or failure_point=='response' and name.endswith('.response')
                or failure_point=='complete' and name.endswith('.complete.json') or failure_point=='seal' and name=='seal.json'):
            raise OSError('private source key')
        return original(fd,name,value)
    path=tmp_path/'tape'
    with journal.EvaluationJournal(path,evidence_kind='mock') as tape:
        monkeypatch.setattr(journal,'_write',write)
        with pytest.raises(ProviderAdapterError,match='^provider_journal_failed$') as error:
            ticket=tape.begin(request(),10)
            tape.complete(ticket,response())
            tape.finish()
        assert error.value.__context__ is None and error.value.__cause__ is None
        assert tape.snapshot()['failed']
    with pytest.raises(ProviderAdapterError):journal.load_recordings(path,require_live=False)


def test_actual_process_crash_retains_durable_pending(tmp_path):
    path=tmp_path/'crashed'
    script="""import os,sys,json
sys.path.insert(0,sys.argv[1])
from provider_journal import EvaluationJournal
from provider_adapters import ProviderRequest
j=EvaluationJournal(sys.argv[2],evidence_kind='mock');j.__enter__()
r=ProviderRequest('openai','text-embedding-3-small',json.dumps(dict(model='text-embedding-3-small',dimensions=1536,encoding_format='float',input=['tiny public fixture'])).encode(),'a'*64)
j.begin(r,10)
os._exit(23)
"""
    child=subprocess.run([sys.executable,'-c',script,str(Path(journal.__file__).parent),str(path)],timeout=10,capture_output=True)
    assert child.returncode==23 and child.stderr==b''
    assert (path/'001.pending.json').is_file() and not (path/'seal.json').exists()
    with pytest.raises(ProviderAdapterError):journal.load_recordings(path,require_live=False)


@pytest.mark.parametrize('failure_point',['short_write','fsync'])
def test_partial_pending_write_or_sync_failure_is_unreplayable(tmp_path,monkeypatch,failure_point):
    path=tmp_path/'tape'
    with journal.EvaluationJournal(path,evidence_kind='mock') as tape:
        actual_write=journal.os.write
        actual_sync=journal.os.fsync
        writes=[]
        def write(fd,data):
            writes.append(len(data))
            if len(writes)==1:
                return actual_write(fd,data[:7])
            raise OSError('private disk diagnostic')
        def sync(fd):
            raise OSError('private sync diagnostic')
        if failure_point=='short_write':monkeypatch.setattr(journal.os,'write',write)
        else:monkeypatch.setattr(journal.os,'fsync',sync)
        with pytest.raises(ProviderAdapterError,match='provider_journal_failed') as error:
            tape.begin(request(),10)
        assert error.value.__context__ is None
        assert tape.snapshot()['failed'] and not tape.snapshot()['sealed']
        monkeypatch.setattr(journal.os,'write',actual_write)
        monkeypatch.setattr(journal.os,'fsync',actual_sync)
    assert (path/'001.pending.json').exists()
    with pytest.raises(ProviderAdapterError):journal.load_recordings(path,require_live=False)


def test_metadata_digest_and_parse_share_one_read(tmp_path,monkeypatch):
    path=tmp_path/'tape';sealed(path)
    original=journal._read
    reads={}
    def read(fd,name,maximum):
        reads[name]=reads.get(name,0)+1
        if reads[name]>1:
            return b'{}'
        return original(fd,name,maximum)
    monkeypatch.setattr(journal,'_read',read)
    assert len(journal.load_recordings(path,require_live=False))==1
    assert all(count==1 for count in reads.values())


@pytest.mark.parametrize('code', [
    'provider_http_auth_failed', 'provider_http_rate_limited', 'provider_http_server_failed',
    'provider_pacing_invalid', 'provider_pacing_failed',
])
def test_fixed_transport_categories_remain_unreplayable(tmp_path, code):
    path = tmp_path / 'tape'
    with journal.EvaluationJournal(path, evidence_kind='mock') as tape:
        ticket = tape.begin(request(), 10)
        tape.uncertain(ticket, code)
        with pytest.raises(ProviderAdapterError):
            tape.finish()
    assert json.loads((path / 'failure.json').read_text()) == {'ordinal': 1, 'code': code}
    with pytest.raises(ProviderAdapterError):
        journal.load_recordings(path, require_live=False)


def test_arbitrary_provider_error_text_is_not_journaled(tmp_path):
    path = tmp_path / 'tape'
    with journal.EvaluationJournal(path, evidence_kind='mock') as tape:
        ticket = tape.begin(request(), 10)
        with pytest.raises(ProviderAdapterError):
            tape.uncertain(ticket, 'provider_http_rate_limited synthetic-private-value')
        assert not (path / 'failure.json').exists()
        tape.uncertain(ticket, 'transport_failed')
    assert 'synthetic-private-value' not in (path / 'failure.json').read_text()
