"""Private ownership journals and bounded recovery for native test fixtures."""

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat

from runtime_diagnostics import CleanupFailure, describe_error


_REASONS = frozenset({
    'invalid_manifest', 'unsafe_path', 'target_mismatch', 'ownership_mismatch',
    'unsafe_role', 'unexpected_policy', 'history_mismatch', 'schema_mismatch',
    'lock_busy', 'fixture_remaining',
})
_BASE_TABLES = ('collections', 'documents', 'document_revisions', 'index_generations',
                'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs')


class RecoveryRefused(ValueError):
    """A closed refusal reason, with no resource or exception content."""

    def __init__(self, reason):
        self.reason = reason if type(reason) is str and len(reason) <= 32 and reason in _REASONS else 'invalid_manifest'
        super().__init__('recovery_refused')


def _hex(value, length):
    return type(value) is str and len(value) == length and re.fullmatch('[0-9a-f]+', value) is not None


def target_fingerprint(host, port, dbname, user):
    """Hash only the bounded public connection identity, never credentials."""
    if (any(type(value) is not str or not 1 <= len(value) <= 1024 or '\0' in value
            for value in (host, dbname, user))
            or type(port) is not int or not 1 <= port <= 65535):
        raise RecoveryRefused('invalid_manifest')
    body = json.dumps([host, port, dbname, user], ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(body.encode('ascii')).hexdigest()


@dataclass(frozen=True)
class Manifest:
    """Immutable inputs; database resource names are derived, never supplied."""

    version: int
    run_id: str
    owner_nonce: str
    target_sha256: str
    ingestion: bool
    vectors: bool
    lifecycle: bool
    allow_schema_restore: bool
    migration_sha256: str
    vector_sha256: str | None

    def __post_init__(self):
        if (type(self.version) is not int or self.version != 1
                or not _hex(self.run_id, 16) or not _hex(self.owner_nonce, 64)
                or not _hex(self.target_sha256, 64) or not _hex(self.migration_sha256, 64)
                or any(type(value) is not bool for value in (
                    self.ingestion, self.vectors, self.lifecycle, self.allow_schema_restore))
                or (self.vectors and not _hex(self.vector_sha256, 64))
                or (not self.vectors and self.vector_sha256 is not None)):
            raise RecoveryRefused('invalid_manifest')

    @property
    def role(self):
        return 'cragkit_probe_' + self.run_id

    @property
    def collection(self):
        return 'probe_' + self.run_id

    @property
    def tenants(self):
        return ('probe_a_' + self.run_id, 'probe_b_' + self.run_id)

    @property
    def policy(self):
        return self.role + '_select'

    @property
    def owner_marker(self):
        return 'cragkit-runtime-v1:' + self.owner_nonce

    @property
    def tables(self):
        return _BASE_TABLES + (('chunk_vectors_fake_1536',) if self.vectors else ())

    @property
    def selected(self):
        return self.tables + ('migration_history',) + (('embedding_profiles',) if self.vectors else ())

    def to_dict(self):
        return asdict(self)


def _directory(root, *, create=False):
    path = Path(root) if root is not None else Path.home() / '.config/cragkit/runtime-recovery'
    try:
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(fd)
            raise RecoveryRefused('unsafe_path')
        return path, fd, (info.st_dev, info.st_ino)
    except OSError:
        raise RecoveryRefused('unsafe_path') from None


def _read(fd, name):
    file_fd = None
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        before = os.fstat(file_fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 1 <= before.st_size <= 8192):
            raise RecoveryRefused('unsafe_path')
        body = os.read(file_fd, 8193)
        after = os.fstat(file_fd)
        if (len(body) != before.st_size or len(body) > 8192
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise RecoveryRefused('unsafe_path')
        return body, (before.st_dev, before.st_ino)
    except OSError:
        raise RecoveryRefused('unsafe_path') from None
    finally:
        if file_fd is not None:
            os.close(file_fd)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryRefused('invalid_manifest')
        result[key] = value
    return result


def _decode(body, run_id, target):
    try:
        value = json.loads(body, object_pairs_hook=_pairs)
        if type(value) is not dict or set(value) != set(Manifest.__dataclass_fields__):
            raise RecoveryRefused('invalid_manifest')
        manifest = Manifest(**value)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise RecoveryRefused('invalid_manifest') from None
    if manifest.run_id != run_id:
        raise RecoveryRefused('invalid_manifest')
    if manifest.target_sha256 != target:
        raise RecoveryRefused('target_mismatch')
    return manifest


class Journal:
    """An exclusive private file whose identity must survive until removal."""

    def __init__(self, manifest, root, directory_identity, file_identity, body):
        self._manifest = manifest
        self._root = root
        self._directory_identity = directory_identity
        self._file_identity = file_identity
        self._body = body

    @property
    def manifest(self):
        return self._manifest

    @classmethod
    def create(cls, *, run_id, target_sha256, ingestion, vectors, lifecycle,
               allow_schema_restore, migration_sha256, vector_sha256, root=None):
        manifest = Manifest(1, run_id, secrets.token_hex(32), target_sha256,
                            ingestion, vectors, lifecycle, allow_schema_restore,
                            migration_sha256, vector_sha256)
        body = json.dumps(manifest.to_dict(), sort_keys=True, separators=(',', ':')).encode('ascii')
        path, directory_fd, directory_identity = _directory(root, create=True)
        file_fd = None
        try:
            file_fd = os.open(run_id + '.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=directory_fd)
            with os.fdopen(file_fd, 'wb', closefd=False) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(file_fd)
            info = os.fstat(file_fd)
            if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
                raise RecoveryRefused('unsafe_path')
            os.fsync(directory_fd)
            return cls(manifest, path, directory_identity, (info.st_dev, info.st_ino), body)
        except OSError:
            raise RecoveryRefused('unsafe_path') from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(directory_fd)

    @classmethod
    def load(cls, run_id, *, target_sha256, root=None):
        if not _hex(run_id, 16) or not _hex(target_sha256, 64):
            raise RecoveryRefused('invalid_manifest')
        path, fd, directory_identity = _directory(root)
        try:
            body, file_identity = _read(fd, run_id + '.json')
            manifest = _decode(body, run_id, target_sha256)
            return cls(manifest, path, directory_identity, file_identity, body)
        finally:
            os.close(fd)

    def validate(self):
        """Recheck the file before any database action or journal removal."""
        _, fd, identity = _directory(self._root)
        try:
            body, file_identity = _read(fd, self.manifest.run_id + '.json')
            if (identity != self._directory_identity or file_identity != self._file_identity
                    or body != self._body):
                raise RecoveryRefused('unsafe_path')
            if _decode(body, self.manifest.run_id, self.manifest.target_sha256) != self.manifest:
                raise RecoveryRefused('invalid_manifest')
        finally:
            os.close(fd)

    def remove(self):
        self.validate()
        _, fd, identity = _directory(self._root)
        try:
            body, file_identity = _read(fd, self.manifest.run_id + '.json')
            if identity != self._directory_identity or file_identity != self._file_identity or body != self._body:
                raise RecoveryRefused('unsafe_path')
            os.unlink(self.manifest.run_id + '.json', dir_fd=fd)
            os.fsync(fd)
        except OSError:
            raise RecoveryRefused('unsafe_path') from None
        finally:
            os.close(fd)


def _observe(task):
    try:
        task.result()
    except BaseException:
        pass


def _late_close(task):
    try:
        transport = task.result()
    except BaseException:
        return
    try:
        closer = asyncio.create_task(transport.close())
        closer.add_done_callback(_observe)
    except BaseException:
        pass


async def _bounded(awaitable, deadline, *, late=None, pending=None):
    task = asyncio.create_task(awaitable)
    try:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0 or not (await asyncio.wait({task}, timeout=remaining))[0]:
            raise TimeoutError()
        return task.result()
    except BaseException:
        if not task.done():
            task.cancel()
            if pending is not None:
                pending.append(task)
            task.add_done_callback(late or _observe)
        elif late is _late_close and not task.cancelled() and task.exception() is None:
            task.add_done_callback(late)
        else:
            _observe(task)
        raise


def _late_clean(task, transport):
    _observe(task)
    try:
        closer = asyncio.create_task(transport.close())
        closer.add_done_callback(_observe)
    except BaseException:
        pass


def _retryable(error):
    if issubclass(type(error), (RecoveryRefused, PermissionError)):
        return False
    record = describe_error(error, operation='admin_connect', stage='recovery')
    if record['category'] in ('cancelled', 'timeout', 'validation'):
        return False
    return record['category'] == 'connection' or record['sqlstate'] in ('40001', '40P01', '55P03')


async def recover(journal, *, connect, deadline, max_attempts=2, primary=None, stage='recovery'):
    """Recover exact journal ownership, serially and within one shared deadline."""
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or type(max_attempts) is not int or not 1 <= max_attempts <= 2
            or type(journal) is not Journal
            or (primary is not None and not issubclass(type(primary), BaseException))):
        raise RecoveryRefused('invalid_manifest')
    deadline = min(deadline, asyncio.get_running_loop().time() + 25)
    failures = []
    for attempt in range(1, max_attempts + 1):
        transport = None
        pending = []
        operation = 'journal_read'
        try:
            journal.validate()
            operation = 'admin_connect'
            transport = await _bounded(connect(deadline), deadline, late=_late_close)
            operation = 'fixture_transaction'
            await _bounded(transport.clean(journal.manifest, deadline=deadline), deadline,
                           pending=pending, late=lambda task, handle=transport: _late_clean(task, handle))
            operation = 'admin_close'
            await _bounded(transport.close(), deadline, pending=pending)
            transport = None
            operation = 'journal_remove'
            journal.remove()
            return {'state': 'passed', 'cleanup_verified': True, 'attempts': attempt,
                    'recovered': attempt > 1,
                    'failures': [describe_error(error, operation=op, stage=stage) for op, error in failures]}
        except BaseException as error:
            if transport is not None and operation == 'fixture_transaction':
                label = getattr(transport, 'operation', operation)
                operation = describe_error(error, operation=label, stage=stage)['operation']
            failures.append((operation, error))
            settled = not pending
            if transport is not None and operation != 'admin_close' and settled:
                try:
                    await _bounded(transport.close(), deadline)
                except BaseException as close_error:
                    failures.append(('admin_close', close_error))
                    settled = False
            if (settled and operation != 'admin_close' and _retryable(error) and attempt < max_attempts
                    and asyncio.get_running_loop().time() < deadline):
                continue
            failure = CleanupFailure(failures, primary=primary, stage=stage)
            if issubclass(type(error), RecoveryRefused):
                failure.refusal_reason = error.reason
            raise failure from None
