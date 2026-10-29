"""Mock process lifecycle checks; no PostgreSQL or OpenSSL command is executed."""
from pathlib import Path
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qdrant_source_native as module
from runtime_diagnostics import CleanupFailure


class Process:
    pid=812345
    def __init__(self):
        self.running=True
        self.waits=[]
        self.stubborn=False
    def poll(self):return None if self.running else 0
    def wait(self,timeout):
        self.waits.append(timeout)
        if self.running:raise subprocess.TimeoutExpired('owned_fixture',timeout)
        return 0


def mocks(tmp_path,monkeypatch):
    binary_dir=tmp_path/'bin';binary_dir.mkdir()
    for name in ('postgres','initdb','pg_ctl','pg_isready'):
        path=binary_dir/name;path.write_bytes(b'mock executable');path.chmod(0o755)
    state={'calls':[],'processes':[],'signals':[],'version':'17.11','ready':True,'ctl':True,'initdb':True}
    def run(arguments,**kwargs):
        state['calls'].append((arguments,kwargs))
        name=Path(arguments[0]).name
        if '--version' in arguments:
            return subprocess.CompletedProcess(arguments,0,(name+' (PostgreSQL) '+state['version']+'\n').encode(),b'')
        if name=='initdb':
            if not state['initdb']:raise OSError('PRIVATE_INITDB_DETAIL')
            data=Path(arguments[arguments.index('-D')+1]);data.mkdir(mode=0o700)
            (data/'postgresql.conf').write_text('# fixture\n')
            (data/'pg_hba.conf').write_text('# fixture\n')
        if name=='openssl':
            Path(arguments[arguments.index('-keyout')+1]).write_text('MOCK PRIVATE KEY')
            Path(arguments[arguments.index('-out')+1]).write_text('MOCK CERTIFICATE')
        if name=='pg_ctl' and state['ctl']:
            state['processes'][-1].running=False
        return subprocess.CompletedProcess(arguments,0 if name!='pg_isready' or state['ready'] else 1,b'',b'')
    def popen(arguments,**kwargs):
        state['calls'].append((arguments,kwargs))
        process=Process();state['processes'].append(process);return process
    def killpg(pid,requested):
        state['signals'].append((pid,requested))
        if requested==signal.SIGKILL or not state['processes'][-1].stubborn:state['processes'][-1].running=False
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    monkeypatch.setattr(module.shutil,'which',lambda name:'/mock/openssl')
    monkeypatch.setattr(module.os,'killpg',killpg)
    return binary_dir,state


def test_private_tls_scram_configuration_and_cleanup(tmp_path,monkeypatch):
    binaries,state=mocks(tmp_path,monkeypatch)
    fixture=module.PostgresSourceFixture(binaries,tmp_path/'artifacts')
    with fixture:
        config=fixture.config
        work=fixture._work;data=fixture._data;password=fixture._password
        assert work.stat().st_mode&0o777==0o700
        for path in (Path(config['passfile']),data/'server.key',data/'server.crt',work/'postgres.log'):
            assert path.stat().st_mode&0o777==0o600
        assert config['host']=='127.0.0.1' and config['max_size']==1 and config['user']=='cragkit_fixture_admin'
        assert isinstance(config['sslrootcert'],str) and isinstance(config['passfile'],str)
        server=(data/'postgresql.conf').read_text()
        for expected in ("listen_addresses = '127.0.0.1'",'max_connections = 5',"shared_buffers = '16MB'","work_mem = '1MB'",
                         'autovacuum = off','max_parallel_workers = 0',"unix_socket_directories = ''",'ssl = on',
                         "log_min_error_statement = 'panic'",'log_parameter_max_length_on_error = 0'):
            assert expected in server
        assert 'hostssl all all 127.0.0.1/32 scram-sha-256' in (data/'pg_hba.conf').read_text()
        assert 'subjectAltName=IP:127.0.0.1' in (work/'openssl.cnf').read_text()
        assert password not in repr(fixture) and password not in repr([call[0] for call in state['calls']])
        assert not (work/'initdb-password').exists()
        start=next(kwargs for arguments,kwargs in state['calls'] if Path(arguments[0]).name=='postgres' and '--version' not in arguments)
        assert start['start_new_session'] is True and start['stdin']==subprocess.DEVNULL
    assert not work.exists() and fixture.process is None
    fixture.close()
    assert 'owned_postgres_private_data_removed' in fixture.checks


def test_explicit_bounded_runtime_client_fixtures_preserve_reserved_slots(tmp_path,monkeypatch):
    binaries,_=mocks(tmp_path,monkeypatch)
    for ceiling in (6,7):
        with module.PostgresSourceFixture(binaries,tmp_path/'worker-artifacts',max_connections=ceiling) as fixture:
            server=(fixture._data/'postgresql.conf').read_text()
            assert f'max_connections = {ceiling}' in server
            assert 'superuser_reserved_connections' not in server
            assert "shared_buffers = '16MB'" in server
    for invalid in (True,0,4,8,100,'6'):
        with pytest.raises(RuntimeError,match='postgres_fixture_connection_ceiling'):
            module.PostgresSourceFixture(tmp_path,tmp_path/'unused',max_connections=invalid)


def test_reader_passfile_exact_endpoint_and_escape_no_credential_argv(tmp_path,monkeypatch):
    binaries,state=mocks(tmp_path,monkeypatch)
    with module.PostgresSourceFixture(binaries,tmp_path/'artifacts') as fixture:
        config=fixture.reader_config('fixture_reader',r'CANARY:password\value')
        assert Path(config['passfile']).read_text()==f"127.0.0.1:{config['port']}:postgres:fixture_reader:CANARY\\:password\\\\value\n"
        assert 'CANARY' not in repr(state['calls'])
        config['host']='forged'
        assert fixture.config['host']=='127.0.0.1'


@pytest.mark.parametrize('user,password',[('bad user','pass'),('reader',''),('reader','line\nfeed'),('reader','nul\0'),('reader','x'*4097)])
def test_reader_input_is_rejected_without_secret_error(tmp_path,monkeypatch,user,password):
    binaries,_=mocks(tmp_path,monkeypatch)
    with module.PostgresSourceFixture(binaries,tmp_path/'artifacts') as fixture:
        with pytest.raises(RuntimeError,match='postgres_fixture_reader_input'):
            fixture.reader_config(user,password)


def test_restart_reuses_initialized_database_port_and_private_config(tmp_path,monkeypatch):
    binaries,state=mocks(tmp_path,monkeypatch)
    with module.PostgresSourceFixture(binaries,tmp_path/'artifacts') as fixture:
        config=fixture.config
        fixture.stop();fixture.stop()
        fixture.start()
        assert fixture.config==config and len(state['processes'])==2
        assert sum(Path(args[0]).name=='initdb' and '--version' not in args for args,_ in state['calls'])==1
        assert len([args for args,_ in state['calls'] if Path(args[0]).name=='openssl'])==1


def test_fast_stop_failure_uses_only_owned_process_group(tmp_path,monkeypatch):
    binaries,state=mocks(tmp_path,monkeypatch)
    with module.PostgresSourceFixture(binaries,tmp_path/'artifacts') as fixture:
        state['ctl']=False
        state['processes'][-1].stubborn=True
        fixture.stop()
        assert state['signals']==[(Process.pid,signal.SIGTERM),(Process.pid,signal.SIGKILL)]
        assert fixture.process is None


def test_version_mismatch_and_initdb_failure_cleanup_are_redacted(tmp_path,monkeypatch):
    binaries,state=mocks(tmp_path,monkeypatch)
    fixture=module.PostgresSourceFixture(binaries,tmp_path/'artifacts')
    state['version']='17.10'
    with pytest.raises(RuntimeError,match='postgres_fixture_binary_profile'):fixture.__enter__()
    assert fixture._temporary is None and not state['processes']
    state['version']='17.11';state['initdb']=False
    fixture2=module.PostgresSourceFixture(binaries,tmp_path/'other')
    with pytest.raises(RuntimeError,match='postgres_fixture_initdb') as caught:fixture2.__enter__()
    assert 'PRIVATE' not in str(caught.value) and caught.value.__suppress_context__
    assert fixture2._temporary is None


def test_unproven_shutdown_preserves_private_data_for_owned_recovery(tmp_path,monkeypatch):
    binaries,_=mocks(tmp_path,monkeypatch)
    fixture=module.PostgresSourceFixture(binaries,tmp_path/'artifacts').__enter__()
    work=fixture._work
    original=fixture.stop
    def fail():raise RuntimeError('PRIVATE_STOP_DETAIL')
    monkeypatch.setattr(fixture,'stop',fail)
    with pytest.raises(RuntimeError,match='postgres_fixture_close'):fixture.close()
    assert work.exists()
    monkeypatch.setattr(fixture,'stop',original)
    fixture.close()
    assert not work.exists()


def test_primary_and_cleanup_failure_both_survive_without_private_text(tmp_path,monkeypatch):
    fixture=module.PostgresSourceFixture(tmp_path,tmp_path/'artifacts')
    def fail():raise RuntimeError('PRIVATE_CLEANUP')
    monkeypatch.setattr(fixture,'close',fail)
    with pytest.raises(CleanupFailure) as caught:
        fixture.__exit__(ValueError,ValueError('PRIVATE_PRIMARY'),None)
    assert 'PRIVATE' not in str(caught.value)
    assert caught.value.to_dict()['primary'] is not None


def test_ambient_postgres_settings_are_not_discovered_or_forwarded(monkeypatch):
    monkeypatch.setenv('PGPASSWORD','PRIVATE_ENV_PASSWORD')
    monkeypatch.setenv('PGHOST','foreign.invalid')
    monkeypatch.setenv('OPENSSL_CONF','/foreign/openssl.cnf')
    environment=module.PostgresSourceFixture._environment()
    assert not any(key.startswith('PG') for key in environment)
    assert 'OPENSSL_CONF' not in environment and 'PRIVATE_ENV_PASSWORD' not in repr(environment)


def test_config_and_lifecycle_before_enter_and_after_close_are_redacted(tmp_path):
    fixture=module.PostgresSourceFixture(tmp_path,tmp_path/'artifacts')
    with pytest.raises(RuntimeError,match='postgres_fixture_config_unavailable'):_=fixture.config
    with pytest.raises(RuntimeError,match='postgres_fixture_lifecycle'):fixture.start()
    fixture.close()
    with pytest.raises(RuntimeError,match='postgres_fixture_lifecycle'):fixture.__enter__()



@pytest.mark.parametrize('version',['17.11','17.11 (Homebrew)'])
def test_exact_reference_binary_version_accepts_verified_distribution_suffix(tmp_path,monkeypatch,version):
    binaries,state=mocks(tmp_path,monkeypatch)
    state['version']=version
    with module.PostgresSourceFixture(binaries,tmp_path/'artifacts') as fixture:
        assert 'postgres_17_11_binaries_verified' in fixture.checks


@pytest.mark.parametrize('version',['17.10','17.11.1','17.11 unknown','17.11 (Homebrew) extra'])
def test_other_binary_versions_and_unrecognized_suffixes_fail_closed(tmp_path,monkeypatch,version):
    binaries,state=mocks(tmp_path,monkeypatch)
    state['version']=version
    with pytest.raises(RuntimeError,match='postgres_fixture_binary_profile'):
        module.PostgresSourceFixture(binaries,tmp_path/'artifacts').__enter__()
    assert not state['processes']
