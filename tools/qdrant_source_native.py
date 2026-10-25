"""Explicit private PostgreSQL 17.11 TLS/SCRAM fixture for QS-r1 acceptance."""
from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from typing import Any

from runtime_diagnostics import CleanupFailure


class PostgresSourceFixture:
    """Own a disposable loopback server, its credentials and its complete directory.

    The caller creates roles and schemas explicitly. No hosted PostgreSQL target is
    used, and the fixture never reads a password from ambient PostgreSQL variables.
    """
    def __init__(self, binary_dir: Path, artifacts: Path) -> None:
        self.binary_dir = Path(binary_dir)
        self.artifacts = Path(artifacts)
        self.process: subprocess.Popen[bytes] | None = None
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._work: Path | None = None
        self._data: Path | None = None
        self._log: Any = None
        self._binaries: dict[str, Path] = {}
        self._port = 0
        self._initialized = False
        self._closed = False
        self._password = ''
        self._base_config: dict[str, Any] | None = None
        self.checks: list[str] = []

    def __repr__(self) -> str:
        return 'PostgresSourceFixture()'

    @staticmethod
    def _environment() -> dict[str, str]:
        return {key:value for key,value in os.environ.items()
                if not key.startswith('PG') and key not in ('OPENSSL_CONF','RANDFILE')}

    @staticmethod
    def _private_write(path: Path, value: str) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
                stream.write(value)
        except BaseException:
            # fdopen owns the descriptor, including failures after construction.
            raise
        os.chmod(path, 0o600)

    def _validate_binaries(self) -> None:
        try:
            directory = self.binary_dir.resolve(strict=True)
            if not directory.is_dir():
                raise RuntimeError()
            for name in ('postgres','initdb','pg_ctl','pg_isready'):
                binary = (directory / name).resolve(strict=True)
                if not binary.is_file() or not os.access(binary, os.X_OK):
                    raise RuntimeError()
                result = subprocess.run([str(binary),'--version'], stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
                    env=self._environment())
                expected = name + ' (PostgreSQL) 17.11'
                accepted = (expected.encode(), (expected + ' (Homebrew)').encode())
                if result.returncode != 0 or type(result.stdout) is not bytes or result.stdout.strip() not in accepted:
                    raise RuntimeError()
                self._binaries[name] = binary
        except Exception:
            raise RuntimeError('postgres_fixture_binary_profile') from None
        self.checks.append('postgres_17_11_binaries_verified')

    def _run(self, arguments: list[str], *, timeout: float, stage: str) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=self._log,
                stderr=subprocess.STDOUT, timeout=timeout, check=False, env=self._environment())
            if result.returncode != 0:
                raise RuntimeError()
            return result
        except Exception:
            raise RuntimeError('postgres_fixture_' + stage) from None

    def __enter__(self) -> PostgresSourceFixture:
        if self._closed or self._temporary is not None:
            raise RuntimeError('postgres_fixture_lifecycle')
        try:
            self._validate_binaries()
            self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._temporary = tempfile.TemporaryDirectory(prefix='qs-postgres-', dir=self.artifacts)
            self._work = Path(self._temporary.name)
            os.chmod(self._work, 0o700)
            self._data = self._work / 'data'
            self._log = open(self._work / 'postgres.log', 'xb')
            os.chmod(self._work / 'postgres.log', 0o600)
            self._password = secrets.token_hex(32)
            password_file = self._work / 'initdb-password'
            self._private_write(password_file, self._password + '\n')
            self._run([str(self._binaries['initdb']),'-D',str(self._data),'--encoding=UTF8','--locale=C',
                '--auth-local=scram-sha-256','--auth-host=scram-sha-256',
                '--username=cragkit_fixture_admin','--pwfile='+str(password_file),'--no-instructions'],
                timeout=30,stage='initdb')
            password_file.unlink()
            os.chmod(self._data, 0o700)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(('127.0.0.1', 0))
                self._port = probe.getsockname()[1]
            self._make_certificate()
            self._configure_server()
            self._initialized = True
            self._base_config = self.reader_config('cragkit_fixture_admin', self._password)
            self.start()
            return self
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                raise CleanupFailure([('close',cleanup)], primary=primary) from None
            raise

    def _make_certificate(self) -> None:
        assert self._work is not None and self._data is not None
        openssl = shutil.which('openssl')
        if openssl is None:
            raise RuntimeError('postgres_fixture_openssl_unavailable')
        configuration = self._work / 'openssl.cnf'
        self._private_write(configuration, '[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=server\n'
            '[dn]\nCN=127.0.0.1\n[server]\nsubjectAltName=IP:127.0.0.1\n'
            'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n'
            'extendedKeyUsage=serverAuth\n')
        self._run([openssl,'req','-x509','-newkey','rsa:2048','-sha256','-nodes','-days','1',
            '-keyout',str(self._data/'server.key'),'-out',str(self._data/'server.crt'),'-config',str(configuration)],
            timeout=20,stage='certificate')
        os.chmod(self._data/'server.key',0o600)
        os.chmod(self._data/'server.crt',0o600)
        self.checks.append('private_san_loopback_certificate_created')

    def _configure_server(self) -> None:
        assert self._data is not None
        configuration = "\n".join((
            "listen_addresses = '127.0.0.1'", 'port = '+str(self._port),
            'max_connections = 5', "shared_buffers = '16MB'", "work_mem = '1MB'",
            "maintenance_work_mem = '16MB'", 'autovacuum = off', 'max_parallel_workers = 0',
            'max_parallel_workers_per_gather = 0','max_parallel_maintenance_workers = 0',
            'max_worker_processes = 0','jit = off',"huge_pages = off", "unix_socket_directories = ''",
            'ssl = on',"ssl_cert_file = 'server.crt'","ssl_key_file = 'server.key'",
            "ssl_min_protocol_version = 'TLSv1.2'", "password_encryption = 'scram-sha-256'",
            'logging_collector = off',"log_statement = 'none'",'log_connections = off','log_disconnections = off',
            "log_min_error_statement = 'panic'", 'log_parameter_max_length_on_error = 0', "log_line_prefix = ''", 'max_wal_senders = 0',
            'fsync = on','synchronous_commit = on',''))
        with open(self._data/'postgresql.conf','a',encoding='utf-8') as stream:
            stream.write('\n'+configuration)
        (self._data/'pg_hba.conf').write_text('local all all scram-sha-256\n'
            'hostssl all all 127.0.0.1/32 scram-sha-256\n'
            'hostnossl all all 127.0.0.1/32 reject\n'
            'host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n',encoding='utf-8')
        os.chmod(self._data/'postgresql.conf',0o600)
        os.chmod(self._data/'pg_hba.conf',0o600)

    @property
    def config(self) -> dict[str, Any]:
        if self._closed or self._base_config is None:
            raise RuntimeError('postgres_fixture_config_unavailable')
        return dict(self._base_config)

    def reader_config(self, user: str, password: str) -> dict[str, Any]:
        if self._closed or self._work is None or self._data is None or not self._initialized:
            raise RuntimeError('postgres_fixture_config_unavailable')
        if (type(user) is not str or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}',user) is None
                or type(password) is not str or not password or len(password)>4096
                or any(ord(character)<33 or ord(character)>126 for character in password)):
            raise RuntimeError('postgres_fixture_reader_input')
        escape = lambda value: value.replace('\\','\\\\').replace(':','\\:')
        passfile = self._work / ('reader-' + secrets.token_hex(8) + '.pgpass')
        try:
            self._private_write(passfile, '127.0.0.1:'+str(self._port)+':postgres:'+escape(user)+':'+escape(password)+'\n')
        except Exception:
            raise RuntimeError('postgres_fixture_private_config') from None
        return {'host':'127.0.0.1','port':self._port,'dbname':'postgres','user':user,
                'sslrootcert':str(self._data/'server.crt'),'passfile':str(passfile),'max_size':1}

    def start(self) -> None:
        if self._closed or not self._initialized or self._data is None or self._log is None:
            raise RuntimeError('postgres_fixture_lifecycle')
        if self.process is not None and self.process.poll() is None:
            return
        try:
            self.process = subprocess.Popen([str(self._binaries['postgres']),'-D',str(self._data)],
                stdin=subprocess.DEVNULL,stdout=self._log,stderr=subprocess.STDOUT,
                env=self._environment(),start_new_session=True)
            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                if self.process.poll() is not None:
                    raise RuntimeError()
                status = subprocess.run([str(self._binaries['pg_isready']),'-h','127.0.0.1','-p',str(self._port),
                    '-d','postgres','-U','cragkit_fixture_admin','-t','1'],stdin=subprocess.DEVNULL,
                    stdout=self._log,stderr=subprocess.STDOUT,timeout=2,check=False,env=self._environment())
                if status.returncode==0 and self.process.poll() is None:
                    self.checks.append('owned_postgres_loopback_ready')
                    return
                time.sleep(.05)
            raise RuntimeError()
        except Exception:
            try:
                self.stop()
            except Exception as cleanup:
                raise CleanupFailure([('close',cleanup)],primary=RuntimeError('postgres_fixture_start')) from None
            raise RuntimeError('postgres_fixture_start') from None

    def stop(self) -> None:
        try:
            self._stop_owned_process()
        except Exception:
            raise RuntimeError('postgres_fixture_stop') from None

    def _stop_owned_process(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            assert self._data is not None
            try:
                self._run([str(self._binaries['pg_ctl']),'-D',str(self._data),'-m','fast','-w','-t','5','stop'],
                          timeout=7,stage='stop')
            except Exception:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        raise RuntimeError('postgres_fixture_stop') from None
                except ProcessLookupError:
                    process.wait(timeout=2)
        if process.poll() is None:
            raise RuntimeError('postgres_fixture_stop')
        self.process = None
        self.checks.append('owned_postgres_process_stopped')

    def close(self) -> None:
        if self._closed and self._temporary is None:
            return
        try:
            self.stop()
        except Exception:
            # Keep private data when shutdown has not been proven; never unlink a live database.
            raise RuntimeError('postgres_fixture_close') from None
        self._closed = True
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._temporary is not None:
            try:
                self._temporary.cleanup()
            except Exception:
                raise RuntimeError('postgres_fixture_private_cleanup') from None
            self._temporary = None
        self._password = ''
        self._base_config = None
        self.checks.append('owned_postgres_private_data_removed')

    def __exit__(self, exc_type: object, primary: BaseException | None, traceback: object) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            if primary is not None:
                raise CleanupFailure([('close',cleanup)],primary=primary) from None
            raise
