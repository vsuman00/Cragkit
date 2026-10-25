"""Explicit, private, single-node Qdrant fixtures for native acceptance only."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request
from uuid import NAMESPACE_URL, uuid5

from runtime_diagnostics import CleanupFailure

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_BINARY_SHA256 = '830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3'


def point_identity(payload: dict[str, Any]) -> str:
    names = ('backend_namespace', 'physical_collection', 'collection_incarnation', 'tenant_id',
             'collection', 'document_id', 'revision_id', 'generation_id', 'chunk_id',
             'dense_profile_id', 'sparse_profile_id')
    value = ['cragkit.qdrant.point.v1', *(payload[name] for name in names)]
    return str(uuid5(NAMESPACE_URL, json.dumps(value, ensure_ascii=False, separators=(',', ':'))))


def native_cases(*, dense_only: bool = False) -> list[dict[str, Any]]:
    cases = [
        {'id': 'dual-scoped', 'document': 'doc-1', 'count': 2},
        {'id': 'missing', 'document': 'missing', 'count': 0},
        {'id': 'foreign-tenant', 'document': 'foreign-tenant', 'count': 0},
        {'id': 'foreign-collection', 'document': 'foreign-collection', 'count': 0},
        {'id': 'denied-grant', 'document': 'denied-grant', 'count': 0},
        {'id': 'principal-only', 'document': 'doc-1', 'empty_grants': True, 'count': 2},
        {'id': 'grant-only', 'document': 'grant-only', 'count': 2},
        {'id': 'empty-grants-deny', 'document': 'grant-only', 'empty_grants': True, 'count': 0},
        {'id': 'required-filter', 'document': 'doc-1', 'tag': 'absent', 'count': 0},
        {'id': 'stale-acl-nomination', 'document': 'stale-acl', 'count': 2},
        {'id': 'profile-integrity', 'document': 'bad-profile', 'error': 'integrity_violation'},
        {'id': 'array-metadata-integrity', 'document': 'bad-tag', 'tag': 'reference',
         'error': 'integrity_violation'},
    ]
    if dense_only:
        for case in cases:
            if case.get('count') == 2:
                case['count'] = 1
    return cases


class QdrantFixture:
    """Own only a verified local process, private config and temporary data directory."""

    def __init__(self, binary: Path, artifacts: Path, expected_sha256: str, *, dense_only: bool = False) -> None:
        self.dense_only = dense_only
        binary = binary.resolve(strict=True)
        if not binary.is_file() or sha256(binary.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError('qdrant_binary_identity')
        artifacts.mkdir(parents=True, exist_ok=True)
        self.binary, self.artifacts = binary, artifacts.resolve()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self._log: Any = None
        self._key = secrets.token_hex(32)
        self._reader_key = secrets.token_hex(32)
        self._client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.endpoint = ''
        self.checks: list[str] = []
        self.payloads: dict[str, dict[str, Any]] = {}
        self._created = False

    def __repr__(self) -> str:
        return 'QdrantFixture()'

    def request(self, method: str, path: str, data: object = None, *, reader: bool = False,
                authenticated: bool = True) -> dict[str, Any]:
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['api-key'] = self._reader_key if reader else self._key
        body = None if data is None else json.dumps(data, separators=(',', ':')).encode()
        req = urllib.request.Request(self.endpoint + path, data=body, method=method, headers=headers)
        try:
            with self._client.open(req, timeout=3) as response:
                result = response.read(1_048_577)
                if len(result) > 1_048_576:
                    raise ValueError('fixture_response_bound')
                value = json.loads(result)
                if not isinstance(value, dict):
                    raise ValueError('fixture_response_shape')
                return value
        except urllib.error.HTTPError:
            raise
        except Exception:
            raise RuntimeError('fixture_request_failed') from None

    def __enter__(self) -> QdrantFixture:
        try:
            return self._start()
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                raise CleanupFailure([('close', cleanup)], primary=primary) from None
            raise

    def _start(self) -> QdrantFixture:
        self._temporary = tempfile.TemporaryDirectory(prefix='native-', dir=self.artifacts)
        work = Path(self._temporary.name)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.endpoint = f'http://127.0.0.1:{port}'
        config = {'log_level': 'WARN', 'telemetry_disabled': True,
                  'storage': {'storage_path': str(work / 'storage'),
                              'snapshots_path': str(work / 'snapshots'),
                              'performance': {'max_search_threads': 1, 'optimizer_cpu_budget': 1},
                              'optimizers': {'max_optimization_threads': 1}},
                  'service': {'host': '127.0.0.1', 'http_port': port, 'grpc_port': None,
                              'max_workers': 1, 'max_request_size_mb': 1,
                              'api_key': self._key, 'read_only_api_key': self._reader_key,
                              'enable_cors': False, 'enable_snapshot_url_recovery': False},
                  'cluster': {'enabled': False}}
        config_path = work / 'config.yaml'
        with os.fdopen(os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
            json.dump(config, handle)
        self._log = (self.artifacts / 'qdrant-native.log').open('wb')
        env = {k: v for k, v in os.environ.items() if not k.startswith('QDRANT')}
        self.process = subprocess.Popen([str(self.binary), '--config-path', str(config_path)],
                                        cwd=work, env=env, stdout=self._log, stderr=subprocess.STDOUT)
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError('fixture_server_exited')
            try:
                if self.request('GET', '/')['version'] != '1.20.0':
                    raise ValueError('fixture_server_version')
                break
            except RuntimeError:
                time.sleep(.05)
        else:
            raise RuntimeError('fixture_startup_deadline')
        self._prepare()
        return self

    def _prepare(self) -> None:
        fixture = json.loads((ROOT / 'contracts/fixtures/qdrant_candidates.json').read_text())
        self.config = {'backend_namespace': 'fixture-local', 'physical_collection': 'cragkit_qc_r1',
                       'collection_incarnation': 'inc-1', 'dense_profile': fixture['profiles']['dense'],
                       'sparse_profile': None if self.dense_only else fixture['profiles']['sparse']}
        self.scope = fixture['trusted_scope']
        self.dense = [1.0] + [0.0] * 1535
        self.sparse = None if self.dense_only else fixture['vectors']['sparse_manual']
        self.collection_path = '/collections/' + self.config['physical_collection']
        metadata = {'vectors': {'dense': {'size': 1536, 'distance': 'Cosine'}},
                    'replication_factor': 1, 'write_consistency_factor': 1, 'hnsw_config': {'m': 0}}
        if not self.dense_only:
            metadata['sparse_vectors'] = {'sparse': {}}
        self.request('PUT', self.collection_path, metadata)
        self._created = True
        points = []
        for document in ('doc-1', 'foreign-tenant', 'foreign-collection', 'denied-grant',
                         'grant-only', 'stale-acl', 'bad-profile', 'bad-tag'):
            payload = deepcopy(fixture['base_payload'])
            payload['document_id'] = document
            payload['dense_profile'] = deepcopy(fixture['profiles']['dense'])
            payload['sparse_profile'] = deepcopy(self.config['sparse_profile'])
            if self.dense_only:
                payload['sparse_profile_id'] = ''
            if document == 'foreign-tenant': payload['tenant_id'] = 'tenant-b'
            if document == 'foreign-collection': payload['collection'] = 'other'
            if document == 'denied-grant': payload.update(principal_ids=[], grant_ids=['other'])
            if document == 'grant-only': payload['principal_ids'] = []
            if document == 'stale-acl': payload['authorization_revision'] = 'auth-old'
            if document == 'bad-profile': payload['dense_profile']['model'] = 'wrong-model'
            if document == 'bad-tag': payload['tag'] = ['reference']
            self.payloads[document] = payload
            vectors = {'dense': self.dense}
            if not self.dense_only:
                vectors['sparse'] = self.sparse
            points.append({'id': point_identity(payload), 'payload': payload, 'vector': vectors})
        result = self.request('PUT', self.collection_path + '/points?wait=true&ordering=strong', {'points': points})
        if result['result']['status'] != 'completed':
            raise ValueError('fixture_write_incomplete')
        self.checks.append('complete_owned_named_vector_fixture')
        for reader, authenticated in ((False, False), (True, True)):
            try:
                self.request('PUT', self.collection_path + '/points?wait=true', {'points': points[:1]},
                             reader=reader, authenticated=authenticated)
            except urllib.error.HTTPError as exc:
                if exc.code not in (401, 403): raise RuntimeError('fixture_auth_status') from None
            else:
                raise RuntimeError('fixture_write_role_not_restricted')
        self.checks.append('unauthenticated_and_readonly_writes_denied')
        assert self.process is not None
        listening = subprocess.run(['/usr/sbin/lsof', '-nP', '-a', '-p', str(self.process.pid),
                                    '-iTCP', '-sTCP:LISTEN'], capture_output=True, text=True, check=True).stdout
        listeners = [line for line in listening.splitlines() if '(LISTEN)' in line]
        if len(listeners) != 1 or self.endpoint.removeprefix('http://') not in listeners[0]:
            raise RuntimeError('fixture_listener_scope')
        self.checks.append('only_owned_loopback_listener')

    def child_input(self) -> dict[str, Any]:
        return {'endpoint': self.endpoint, 'api_key': self._reader_key, 'config': self.config,
                'scope': self.scope, 'dense': self.dense, 'sparse': self.sparse,
                'dense_only': self.dense_only, 'cases': native_cases(dense_only=self.dense_only)}

    def close(self) -> None:
        process, self.process = self.process, None
        cleanup_error = False
        if process is not None:
            if process.poll() is None:
                if self._created:
                    try:
                        self.request('DELETE', self.collection_path)
                        self._created = False
                        if self.request('GET', '/collections')['result']['collections']:
                            cleanup_error = True
                        else:
                            self.checks.append('owned_collection_deleted_inventory_empty')
                    except Exception:
                        cleanup_error = True
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
            if process.poll() is None:
                cleanup_error = True
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        self._key = self._reader_key = ''
        self.checks.append('owned_process_private_config_and_data_closed')
        if cleanup_error:
            raise RuntimeError('fixture_cleanup_failed')

    def __exit__(self, exc_type: object, primary: BaseException | None, tb: object) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            if primary is not None:
                raise CleanupFailure([('close', cleanup)], primary=primary) from None
            raise
