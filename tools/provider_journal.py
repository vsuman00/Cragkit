"""Private durable evaluation tapes; incomplete runs cannot be replayed."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from provider_adapters import ProviderAdapterError, ProviderRecording
from provider_recordings import request_metadata, validate_recording

_CODES = frozenset(('transport_failed', 'response_invalid', 'cancelled', 'deadline_exceeded',
                    'journal_failed', 'usage_overrun', 'provider_http_auth_failed',
                    'provider_http_rate_limited', 'provider_http_server_failed',
                    'provider_pacing_invalid', 'provider_pacing_failed'))
_LIMIT = 2097152


def _invalid():
    raise ProviderAdapterError('provider_journal_invalid')


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _private(info, directory=False):
    return (info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)))


def _count(value):
    return type(value) is int and 0 < value <= 2147483647


def _write(fd, name, value):
    child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        if not _private(os.fstat(child)):
            _invalid()
        offset = 0
        while offset < len(value):
            written = os.write(child, value[offset:])
            if written <= 0:
                raise OSError()
            offset += written
        os.fsync(child)
    finally:
        os.close(child)
    os.fsync(fd)


def _read(fd, name, maximum):
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(child)
        if not _private(info) or info.st_size > maximum or info.st_nlink != 1:
            _invalid()
        chunks, size = [], 0
        while True:
            chunk = os.read(child, min(65536, maximum + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                _invalid()
            chunks.append(chunk)
        return b''.join(chunks)
    finally:
        os.close(child)


def _decode(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                _invalid()
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: _invalid())


def _json(fd, name, maximum=8192):
    return _decode(_read(fd, name, maximum))


class EvaluationJournal:
    def __init__(self, directory, *, evidence_kind):
        if type(evidence_kind) is not str or evidence_kind not in ('live', 'mock'):
            _invalid()
        self._directory = Path(directory)
        self._kind = evidence_kind
        self._fd = None
        self._closed = False
        self._attempts = []
        self._completed = []
        self._ticket = None
        self._failed = False
        self._sealed = False

    def __enter__(self):
        if self._closed or self._fd is not None:
            _invalid()
        failure = False
        try:
            self._directory.mkdir(mode=0o700)
            self._fd = os.open(self._directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if not _private(os.fstat(self._fd), True):
                _invalid()
            _write(self._fd, 'run.json', _encode({'version': 'EREC-r1', 'evidence_kind': self._kind}))
            parent = os.open(self._directory.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except Exception:
            failure = True
        if failure:
            self._failed = True
            self.close()
            raise ProviderAdapterError('provider_journal_failed')
        return self

    def close(self):
        self._closed = True
        fd, self._fd = self._fd, None
        failure = False
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                failure = True
        if failure:
            raise ProviderAdapterError('provider_journal_failed')

    def __exit__(self, *args):
        self.close()

    def _active(self):
        if self._fd is None or self._closed or self._failed or self._sealed:
            _invalid()

    def _persist(self, name, value):
        failure = False
        try:
            _write(self._fd, name, value)
        except Exception:
            failure = True
        if failure:
            self._failed = True
            raise ProviderAdapterError('provider_journal_failed')

    def begin(self, request, input_token_ceiling):
        self._active()
        if self._ticket is not None or len(self._attempts) >= 60 or not _count(input_token_ceiling):
            _invalid()
        metadata = request_metadata(request)
        row = dict(metadata, ordinal=len(self._attempts)+1, input_token_ceiling=input_token_ceiling)
        self._persist(f'{row["ordinal"]:03d}.pending.json', _encode(row))
        self._attempts.append(row)
        self._ticket = object()
        return self._ticket

    def _pending(self, ticket):
        self._active()
        if ticket is not self._ticket or ticket is None:
            _invalid()
        return self._attempts[-1]

    def complete(self, ticket, response):
        row = self._pending(ticket)
        usage = validate_recording(row['provider'], row['model'], response,
                                   expected_items=row['response_items'])
        ordinal = row['ordinal']
        self._persist(f'{ordinal:03d}.response', response)
        completion = dict(row, response_sha256=sha256(response).hexdigest(),
                          response_bytes=len(response), reported_input_tokens=usage)
        self._persist(f'{ordinal:03d}.complete.json', _encode(completion))
        self._completed.append(sha256(_encode(completion)).hexdigest())
        self._ticket = None
        return usage

    def uncertain(self, ticket, code):
        row = self._pending(ticket)
        if type(code) is not str or code not in _CODES:
            _invalid()
        self._persist('failure.json', _encode({'ordinal':row['ordinal'], 'code':code}))
        self._failed = True
        self._ticket = None

    def fail(self, code):
        self._active()
        if type(code) is not str or code not in _CODES:
            _invalid()
        self._persist('failure.json', _encode({'ordinal':len(self._attempts), 'code':code}))
        self._failed = True

    def finish(self):
        if self._sealed:
            return
        self._active()
        if self._ticket is not None:
            _invalid()
        seal = dict(version='EREC-r1', evidence_kind=self._kind, attempts=len(self._attempts),
                    pending_sha256=[sha256(_encode(row)).hexdigest() for row in self._attempts],
                    complete_sha256=list(self._completed))
        self._persist('seal.json', _encode(seal))
        self._sealed = True

    def snapshot(self):
        return dict(evidence_kind=self._kind, attempts=len(self._attempts),
                    completed=len(self._completed),
                    pending=int(self._ticket is not None), failed=self._failed, sealed=self._sealed)


def load_recordings(directory, *, require_live=True):
    fd = None
    failure = False
    result = []
    try:
        if type(require_live) is not bool:
            _invalid()
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if not _private(os.fstat(fd), True):
            _invalid()
        run, seal = _json(fd, 'run.json'), _json(fd, 'seal.json', 16384)
        if (type(run) is not dict or set(run) != {'version','evidence_kind'}
                or run['version'] != 'EREC-r1' or run['evidence_kind'] not in ('live','mock')
                or (require_live and run['evidence_kind'] != 'live')
                or type(seal) is not dict or set(seal) != {'version','evidence_kind','attempts','pending_sha256','complete_sha256'}
                or seal['version'] != run['version'] or seal['evidence_kind'] != run['evidence_kind']
                or type(seal['attempts']) is not int or not 0 <= seal['attempts'] <= 60
                or type(seal['pending_sha256']) is not list or len(seal['pending_sha256']) != seal['attempts']
                or type(seal['complete_sha256']) is not list or len(seal['complete_sha256']) != seal['attempts']):
            _invalid()
        expected = {'run.json','seal.json'}
        for ordinal in range(1, seal['attempts']+1):
            pending_name, complete_name, response_name = (f'{ordinal:03d}.pending.json',
                f'{ordinal:03d}.complete.json', f'{ordinal:03d}.response')
            expected.update((pending_name,complete_name,response_name))
            raw = _read(fd, pending_name, 8192)
            complete_raw = _read(fd, complete_name, 8192)
            pending, complete = _decode(raw), _decode(complete_raw)
            fields = {'provider','model','replay_key','request_sha256','response_items','ordinal','input_token_ceiling'}
            if (type(pending) is not dict or set(pending) != fields or pending['ordinal'] != ordinal
                    or type(pending['ordinal']) is not int or not _count(pending['input_token_ceiling'])
                    or sha256(raw).hexdigest() != seal['pending_sha256'][ordinal-1]
                    or type(complete) is not dict or set(complete) != fields | {'response_sha256','response_bytes','reported_input_tokens'}
                    or any(complete[key] != value for key,value in pending.items())
                    or sha256(complete_raw).hexdigest() != seal['complete_sha256'][ordinal-1]):
                _invalid()
            for key in ('replay_key','request_sha256'):
                value = pending[key]
                if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                    _invalid()
            if type(pending['response_items']) is not int or not 1 <= pending['response_items'] <= 40:
                _invalid()
            response = _read(fd, response_name, _LIMIT)
            if (type(complete['response_bytes']) is not int or complete['response_bytes'] != len(response)
                    or complete['response_sha256'] != sha256(response).hexdigest()):
                _invalid()
            usage = validate_recording(pending['provider'], pending['model'], response,
                                       expected_items=pending['response_items'])
            if complete['reported_input_tokens'] != usage or (usage is not None and type(complete['reported_input_tokens']) is not int):
                _invalid()
            result.append(ProviderRecording(pending['provider'],pending['model'],pending['replay_key'],response))
        if set(os.listdir(fd)) != expected:
            _invalid()
    except Exception:
        failure = True
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                failure = True
    if failure:
        raise ProviderAdapterError('provider_journal_invalid')
    return tuple(result)
