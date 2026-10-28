"""Optional owned-process Qdrant controller; physical observations are not SQL proof."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import socket
import stat
import sys
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any, AsyncIterator, Awaitable, Callable, cast
from uuid import uuid4
from weakref import WeakKeyDictionary

from ._qdrant_contract import QdrantConfig, decode_response, parse_model
from ._qdrant_source import metadata_guard
from ._qdrant_transport import deadline_value
from .embeddings import FAKE_PROFILE, OPENAI_PROFILE
from ._qdrant_contract import SPARSE_PROFILE
from .errors import (CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation,
                     InvalidRequest, ProviderUnavailable, UnsupportedCapability, UnauthorizedScope)

_BINARY_SHA256 = '830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3'
_MAX_BYTES = 1048576
_PATH = re.compile(r'/collections/[A-Za-z][A-Za-z0-9_-]{0,63}(?:/points(?:/(?:delete|scroll))?)?(?:\?wait=true(?:&ordering=strong)?)?')


def _safe(error: Exception) -> CragkitError:
    for kind in (DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
                 ProviderUnavailable, UnsupportedCapability, UnauthorizedScope):
        if type(error) is kind:
            return kind()
    return ProviderUnavailable()


def _identity(value: object) -> str:
    if type(value) is not str or not value.strip(' \t\r\n\v\f') or '\0' in value or len(value)>256:
        raise InvalidRequest()
    try:
        if len(value.encode('utf-8'))>256:
            raise InvalidRequest()
    except UnicodeError:
        raise InvalidRequest() from None
    return value


def _count(value: object) -> int:
    if type(value) not in (int,float):
        raise InvalidRequest()
    assert isinstance(value,(int,float))
    if not 1<=value<=9007199254740991 or not math.isfinite(value) or int(value)!=value:
        raise InvalidRequest()
    return int(value)


def _config(value: object) -> QdrantConfig:
    metadata_guard(value)
    result=parse_model(QdrantConfig,value)
    if result.dense_profile.model_dump() not in (FAKE_PROFILE.model_dump(),OPENAI_PROFILE.model_dump()):
        raise UnsupportedCapability()
    if result.sparse_profile is not None and (result.sparse_profile!=SPARSE_PROFILE or
        result.dense_profile.model_dump()!=FAKE_PROFILE.model_dump()):
        raise UnsupportedCapability()
    return result


class _Opaque:
    __slots__=('__weakref__',)
    def __repr__(self) -> str:
        return 'QdrantCapability()'
    def __reduce__(self) -> Any:
        raise TypeError('Capabilities cannot be serialized')


class _Attempt(_Opaque):
    __slots__=()


class _Proof(_Opaque):
    __slots__=()


class _Barrier(_Opaque):
    __slots__=()


class _ControlSession(_Opaque):
    """Sequencing permission, not evidence of fencing or SQL completion."""
    __slots__ = ('_owner', '_token', '_attempts', '_handles')
    _owner: ManagedQdrantSupervisor
    _token: object
    _attempts: dict[_Attempt, object]
    _handles: set[_Transport]

    def __init__(self, owner: ManagedQdrantSupervisor, token: object) -> None:
        object.__setattr__(self, '_owner', owner)
        object.__setattr__(self, '_token', token)
        object.__setattr__(self, '_attempts', {})
        object.__setattr__(self, '_handles', set())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError('Immutable control session')

    def block_ordinary(self) -> None:
        self._owner.block_ordinary(_control=self._token)

    async def recover(self, request: object, *, deadline: float) -> _Proof:
        self._owner._control_access(self._token)
        task = asyncio.current_task()
        assert task is not None
        self._owner._control_work.add(task)
        try:
            return await self._owner.recover(request, deadline=deadline, _control=self._token)
        finally:
            self._owner._control_work.discard(task)

    async def seal_recovery(self, proof: object, *, deadline: float) -> _Barrier:
        self._owner._control_access(self._token)
        task = asyncio.current_task()
        assert task is not None
        self._owner._control_work.add(task)
        try:
            return await self._owner.seal_recovery(proof, deadline=deadline, _control=self._token)
        finally:
            self._owner._control_work.discard(task)

    def finish_recovery(self, barrier: object, settlement: object, *, deadline: float) -> None:
        self._owner.finish_recovery(barrier, settlement, deadline=deadline, _control=self._token)

    def issue_recovery_attempt(self, proof: object, binding: object, *, deadline: float) -> _Attempt:
        self._owner._control_access(self._token)
        attempt = self._owner.issue_recovery_attempt(proof, binding, deadline=deadline, _control=self._token)
        _session_activity(self)
        self._attempts[attempt] = proof
        return attempt

    def recovery_transport_for(self, attempt: object) -> _Transport:
        self._owner._control_access(self._token)
        if type(attempt) is not _Attempt or attempt not in self._attempts:
            raise InvalidRequest()
        if len(self._handles) >= 8:
            raise ProviderUnavailable()
        proof = self._attempts[attempt]
        self._owner.recovery_binding(proof)
        assert isinstance(proof, _Proof)
        handle = self._owner.transport_for(attempt, _control=self._token)
        state = self._owner._transports[handle]
        state.control = self
        state.attempt = attempt
        state.proof = proof
        self._handles.add(handle)
        return handle


_CONTROL_SESSIONS: WeakKeyDictionary[_ControlSession, tuple[ManagedQdrantSupervisor, object, dict[str, int]]] = WeakKeyDictionary()


def control_session_binding(control: object, supervisor: object, proof: object) -> Mapping[str, Any]:
    """Resolve an original active facade and its conservative activity snapshot."""
    if (type(control) is not _ControlSession or control not in _CONTROL_SESSIONS
            or type(supervisor) is not ManagedQdrantSupervisor):
        raise InvalidRequest()
    owner, token, state = _CONTROL_SESSIONS[control]
    if owner is not supervisor:
        raise InvalidRequest()
    owner._control_access(token)
    return MappingProxyType(dict(physical_binding=owner.recovery_binding(proof),activity=state['activity']))


def _session_activity(control: _ControlSession) -> None:
    record = _CONTROL_SESSIONS.get(control)
    if record is None:
        raise ProviderUnavailable()
    owner, token, state = record
    owner._control_access(token)
    if state['activity'] >= 9007199254740991:
        raise ProviderUnavailable()
    state['activity'] += 1


@dataclass(frozen=True,slots=True)
class _Binding:
    intent_id: str
    owner_token: str
    epoch: int
    dispatch_id: str
    recovery_id: str | None = None


@dataclass(slots=True)
class _TransportState:
    key: str = field(repr=False)
    kind: str
    proof: _Proof | None = None
    client: Any = field(default=None,repr=False)
    closed: bool = False
    control: _ControlSession | None = field(default=None,repr=False)
    attempt: _Attempt | None = field(default=None,repr=False)


class _Transport:
    __slots__=('_controller','__weakref__')
    _controller: ManagedQdrantSupervisor
    bounded_responses=True
    cancellation_safe=True
    def __init__(self, controller: ManagedQdrantSupervisor) -> None:
        object.__setattr__(self,'_controller',controller)
    def __setattr__(self,name: str,value: object) -> None:
        raise AttributeError('Immutable transport')
    def __repr__(self) -> str:
        return 'QdrantEpochTransport()'
    def __reduce__(self) -> Any:
        raise TypeError('Transports cannot be serialized')
    async def request(self,method: str,path: str,*,body: bytes | None=None,
                      deadline: float,max_response_bytes: int=_MAX_BYTES) -> bytes:
        return await self._controller._transport_request(self,method,path,body,deadline,max_response_bytes)
    async def close(self) -> None:
        await self._controller._close_transport(self)


class ManagedQdrantSupervisor:
    """A caller-owned long-lived controller; there is no automatic takeover."""
    def __init__(self,binary: Path,work_dir: Path,instance_id: object,config: object) -> None:
        if type(binary) is not type(Path('/')) or type(work_dir) is not type(Path('/')):
            raise InvalidRequest()
        if not binary.is_absolute() or not work_dir.is_absolute() or any('\0' in str(path) for path in (binary,work_dir)):
            raise InvalidRequest()
        self._binary=binary
        self._work=work_dir
        self._instance=_identity(instance_id)
        primary=_config(config)
        self._profiles={primary.physical_collection:primary}
        self._process: asyncio.subprocess.Process | None=None
        self._active: asyncio.Task[Any] | None=None
        self._requests: set[asyncio.Task[Any]]=set()
        self._attempts: WeakKeyDictionary[_Attempt,tuple[_Binding,str,str]]=WeakKeyDictionary()
        self._proofs: WeakKeyDictionary[_Proof,dict[str,Any]]=WeakKeyDictionary()
        self._transports: WeakKeyDictionary[_Transport,_TransportState]=WeakKeyDictionary()
        self._initialized=False
        self._closed=False
        self._cleaned=False
        self._gate=False
        self._epoch=1
        self._key=''
        self._credential_generation=''
        self._endpoint=''
        self._storage_id=''
        self._supervisor_id=''
        self._probe: dict[str,Any]={}
        self._owned: tuple[int,int] | None=None
        self._storage_inode: tuple[int,int] | None=None
        self._recovery: dict[str,Any] | None=None
        self._sealed = False
        self._barrier: _Barrier | None = None
        self._barriers: WeakKeyDictionary[_Barrier, tuple[_Proof, dict[str, Any]]] = WeakKeyDictionary()
        self._control_token: object | None = None
        self._control_draining = False
        self._control_work: set[asyncio.Task[Any]] = set()

    def __repr__(self) -> str:
        return 'ManagedQdrantSupervisor()'

    def register_profile(self,value: object) -> None:
        self._control_access()
        if self._active is not None or self._owned is not None or self._closed:
            raise InvalidRequest()
        profile=_config(value)
        primary=next(iter(self._profiles.values()))
        if profile.backend_namespace!=primary.backend_namespace or len(self._profiles)>=16:
            raise InvalidRequest()
        if profile.physical_collection in self._profiles:
            if profile!=self._profiles[profile.physical_collection]:
                raise IntegrityViolation()
            return
        self._profiles[profile.physical_collection]=profile

    def identity(self) -> dict[str,Any]:
        if self._owned is None:
            raise IndexNotReady()
        return {'instance_id':self._instance,'storage_identity':self._storage_id,
                'supervisor_id':self._supervisor_id,'endpoint':self._endpoint,
                'probe_spec':json.loads(json.dumps(self._probe))}

    def control_binding(self) -> Mapping[str, Any]:
        """Owned local metadata, including failed recovery; never physical proof."""
        if not self._initialized or self._closed:
            raise ProviderUnavailable()
        self._assert_owner()
        recovery = None if self._recovery is None else MappingProxyType({
            key: self._recovery[key] for key in ('recovery_id', 'old_epoch', 'new_epoch')
        })
        return MappingProxyType({
            'instance_id': self._instance,
            'backend_namespace': next(iter(self._profiles.values())).backend_namespace,
            'storage_identity': self._storage_id,
            'supervisor_id': self._supervisor_id,
            'epoch': self._epoch,
            'credential_generation': self._credential_generation,
            'recovery': recovery,
            'sealed': self._sealed,
            'alive': self._process is not None and self._process.returncode is None,
        })

    def profile_binding(self, config: object) -> Mapping[str, Any]:
        """Exact registered profile metadata; never readiness or physical proof."""
        profile = _config(config)
        if self._profiles.get(profile.physical_collection) != profile:
            raise UnsupportedCapability()
        return self.control_binding()

    def _control_access(self, token: object | None = None) -> None:
        if token is not self._control_token or token is not None and self._control_draining:
            raise ProviderUnavailable()

    @asynccontextmanager
    async def control_session(self) -> AsyncIterator[_ControlSession]:
        if self._control_token is not None or self._active is not None or self._closed:
            raise ProviderUnavailable()
        token = object()
        self._control_token = token
        facade = _ControlSession(self, token)
        _CONTROL_SESSIONS[facade] = (self, token, {'activity': 0})
        try:
            yield facade
        finally:
            self._control_draining = True
            pending = [task for task in self._control_work if task is not asyncio.current_task()]
            cancelled = False
            failures = []
            try:
                if pending:
                    drain = asyncio.gather(*pending, return_exceptions=True)
                    while not drain.done():
                        try:
                            await asyncio.shield(drain)
                        except asyncio.CancelledError:
                            cancelled = True
                    failures = [result for result in drain.result() if isinstance(result, BaseException)]
                # Keep exclusion until every owned close actually unwinds.
                for handle in tuple(facade._handles):
                    closing = asyncio.create_task(self._close_transport(handle))
                    while not closing.done():
                        try:
                            await asyncio.shield(closing)
                        except asyncio.CancelledError:
                            cancelled = True
                        except Exception:
                            break
                    try:
                        closing.result()
                    except BaseException as error:
                        failures.append(error)
            finally:
                _CONTROL_SESSIONS.pop(facade, None)
                self._control_token = None
                self._control_draining = False
            if cancelled:
                raise asyncio.CancelledError()
            if failures:
                raise ProviderUnavailable() from None

    def block_ordinary(self, *, _control: object | None = None) -> None:
        self._control_access(_control)
        self.control_binding()
        self._gate = False

    def _assert_owner(self) -> None:
        if self._owned is None:
            raise IndexNotReady()
        try:
            work=self._work.lstat()
            lock=(self._work/'.cragkit-supervisor.lock').lstat()
            owner_path=self._work/'.cragkit-supervisor.lock'/'owner.json'
            owner=owner_path.lstat()
            if (not stat.S_ISDIR(work.st_mode) or (work.st_dev,work.st_ino)!=self._owned
                or work.st_uid!=os.getuid() or stat.S_IMODE(work.st_mode)!=0o700
                or not stat.S_ISDIR(lock.st_mode) or stat.S_IMODE(lock.st_mode)!=0o700
                or not stat.S_ISREG(owner.st_mode) or stat.S_IMODE(owner.st_mode)!=0o600
                or owner.st_nlink!=1 or owner.st_size>4096):
                raise ProviderUnavailable()
            data=json.loads(owner_path.read_bytes())
            if data!={'instance_id':self._instance,'storage_identity':self._storage_id,'supervisor_id':self._supervisor_id}:
                raise ProviderUnavailable()
            storage=(self._work/'storage').lstat()
            if not stat.S_ISDIR(storage.st_mode) or (storage.st_dev,storage.st_ino)!=self._storage_inode:
                raise ProviderUnavailable()
        except (OSError,ValueError,TypeError):
            raise ProviderUnavailable() from None

    def _assert_live(self) -> None:
        self._assert_owner()
        if self._process is None or self._process.returncode is not None:
            raise ProviderUnavailable()

    def _claim(self,deadline: float) -> None:
        if sys.platform!='darwin' or platform.machine()!='arm64' or not Path('/usr/sbin/lsof').is_file():
            raise UnsupportedCapability()
        if not self._binary.is_file() or self._binary.is_symlink():
            raise UnsupportedCapability()
        digest=hashlib.sha256()
        if self._binary.stat().st_size>536870912:
            raise UnsupportedCapability()
        with self._binary.open('rb') as handle:
            while chunk:=handle.read(1048576):
                deadline_value(deadline)
                digest.update(chunk)
        if digest.hexdigest()!=_BINARY_SHA256:
            raise UnsupportedCapability()
        if not self._work.exists():
            self._work.mkdir(mode=0o700)
        current=self._work.lstat()
        if not stat.S_ISDIR(current.st_mode) or current.st_uid!=os.getuid() or stat.S_IMODE(current.st_mode)!=0o700:
            raise InvalidRequest()
        # This marker survives a crash. No lease expiry or stale-lock deletion exists.
        if any(self._work.iterdir()):
            raise ProviderUnavailable()
        lock=self._work/'.cragkit-supervisor.lock'
        lock.mkdir(mode=0o700)
        self._owned=(current.st_dev,current.st_ino)
        self._storage_id=secrets.token_hex(16)
        self._supervisor_id=secrets.token_hex(16)
        self._write_private(lock/'owner.json',json.dumps({'instance_id':self._instance,
            'storage_identity':self._storage_id,'supervisor_id':self._supervisor_id}).encode())
        storage=self._work/'storage';storage.mkdir(mode=0o700)
        info=storage.stat();self._storage_inode=(info.st_dev,info.st_ino)
        (self._work/'snapshots').mkdir(mode=0o700)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        self._endpoint=f'http://127.0.0.1:{port}'
        self._key=secrets.token_hex(32)
        self._credential_generation='credential-'+secrets.token_hex(16)
        self._probe={'collection':'cragkit_control_'+secrets.token_hex(12),
            'collection_config':{'vectors':{'control':{'size':1,'distance':'Cosine'}},
                'optimizers_config':{'prevent_unoptimized':False},'replication_factor':1,'write_consistency_factor':1},
            'point':{'id':str(uuid4()),'vector':{'control':[1.0]},
                'payload':{'supervisor_id':self._supervisor_id,'storage_identity':self._storage_id}}}

    @staticmethod
    def _write_private(path: Path,data: bytes) -> None:
        temporary=path.with_name(path.name+'.new')
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(descriptor,'wb') as handle:
                handle.write(data);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():
                temporary.unlink()

    async def _spawn(self) -> None:
        self._assert_owner()
        if self._process is not None and self._process.returncode is None:
            raise ProviderUnavailable()
        port=int(self._endpoint.rsplit(':',1)[1])
        config={'log_level':'ERROR','telemetry_disabled':True,'cluster':{'enabled':False},
            'storage':{'storage_path':str(self._work/'storage'),'snapshots_path':str(self._work/'snapshots'),
                'performance':{'max_search_threads':1,'optimizer_cpu_budget':1},
                'optimizers':{'max_optimization_threads':1,'prevent_unoptimized':False}},
            'service':{'host':'127.0.0.1','http_port':port,'grpc_port':None,'max_workers':1,
                'max_request_size_mb':1,'api_key':self._key,'enable_cors':False,
                'enable_snapshot_url_recovery':False}}
        self._write_private(self._work/'config.yaml',json.dumps(config).encode())
        self._process=await asyncio.create_subprocess_exec(str(self._binary),'--config-path',str(self._work/'config.yaml'),
            cwd=self._work,env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C','LC_ALL':'C'},
            stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,start_new_session=True)

    async def _listener(self,deadline: float) -> bool:
        process=self._process
        if process is None or process.returncode is not None:
            raise ProviderUnavailable()
        self._assert_owner()
        port=self._endpoint.rsplit(':',1)[1]
        verifier=await asyncio.create_subprocess_exec('/usr/sbin/lsof','-nP','-a','-p',str(process.pid),
            '-iTCP@127.0.0.1:'+port,'-sTCP:LISTEN','-Fpn',stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
        try:
            async with asyncio.timeout_at(deadline):
                assert verifier.stdout is not None
                output=await verifier.stdout.read(16385)
                if len(output)>16384:
                    raise ProviderUnavailable()
                await verifier.wait()
            if len(output)>16384:
                raise ProviderUnavailable()
            lines=output.decode('ascii',errors='strict').splitlines()
            return verifier.returncode==0 and 'p'+str(process.pid) in lines and 'n127.0.0.1:'+port in lines
        finally:
            if verifier.returncode is None:
                verifier.kill()
                async with asyncio.timeout(1):
                    await verifier.wait()

    def _new_transport(self,key: str,kind: str,proof: _Proof | None=None) -> _Transport:
        if len(self._transports)>=256:
            raise ProviderUnavailable()
        handle=_Transport(self)
        self._transports[handle]=_TransportState(key,kind,proof)
        return handle

    async def _http(self,key: str,method: str,path: str,body: bytes | None,deadline: float,
                    maximum: int=_MAX_BYTES, state: _TransportState | None=None) -> tuple[int,bytes]:
        self._assert_live()
        try:
            import httpx
        except ImportError:
            raise UnsupportedCapability() from None
        client=state.client if state is not None else None
        owned=client is None
        if client is None:
            client=httpx.AsyncClient(trust_env=False,follow_redirects=False,
                transport=httpx.AsyncHTTPTransport(retries=0),
                limits=httpx.Limits(max_connections=2,max_keepalive_connections=2))
            if state is not None:
                state.client=client;owned=False
        try:
            async with client.stream(method,self._endpoint+path,content=body,
                headers={'api-key':key,'Accept-Encoding':'identity','Content-Type':'application/json'},
                timeout=max(.001,deadline-asyncio.get_running_loop().time()),follow_redirects=False) as response:
                if response.headers.get('content-encoding','identity').lower().strip()!='identity':
                    raise ProviderUnavailable()
                length=response.headers.get('content-length')
                if length is not None and (len(length)>10 or not length.isdecimal() or int(length)>maximum):
                    raise ProviderUnavailable()
                chunks=bytearray()
                async for chunk in response.aiter_raw(chunk_size=16384):
                    if type(chunk) is not bytes or len(chunks)+len(chunk)>maximum:
                        raise ProviderUnavailable()
                    chunks.extend(chunk)
                return int(response.status_code),bytes(chunks)
        finally:
            if owned:
                async with asyncio.timeout(1):
                    await client.aclose()

    async def _json(self,method: str,path: str,deadline: float,body: object=None) -> dict[str,Any]:
        encoded=None if body is None else json.dumps(body,separators=(',',':'),allow_nan=False).encode()
        status,raw=await self._http(self._key,method,path,encoded,deadline)
        if status!=200:
            raise ProviderUnavailable()
        value=decode_response(raw)
        if type(value) is not dict:
            raise IntegrityViolation()
        return cast(dict[str,Any],value)

    async def _ready(self,deadline: float) -> None:
        while True:
            deadline_value(deadline)
            if await self._listener(deadline):
                try:
                    root=await self._json('GET','/',deadline)
                    if root.get('version')!='1.20.0':
                        raise UnsupportedCapability()
                    cluster=await self._json('GET','/cluster',deadline)
                    if cluster.get('result',{}).get('status')!='disabled':
                        raise UnsupportedCapability()
                    return
                except ProviderUnavailable:
                    pass
            await asyncio.sleep(.025)

    async def _verify_profiles(self,deadline: float) -> None:
        self._assert_owner()
        listing=await self._json('GET','/collections',deadline)
        collections=listing.get('result',{}).get('collections')
        expected=set(self._profiles)|{self._probe['collection']}
        if type(collections) is not list or len(collections)!=len(expected) or any(type(item) is not dict or set(item)!={'name'} for item in collections):
            raise UnsupportedCapability()
        if {item['name'] for item in collections}!=expected:
            raise UnsupportedCapability()
        for name in sorted(expected):
            result=(await self._json('GET','/collections/'+name,deadline)).get('result',{})
            config=result.get('config',{})
            params=config.get('params',{})
            if (config.get('optimizer_config',{}).get('prevent_unoptimized') is not False
                or params.get('replication_factor')!=1 or params.get('write_consistency_factor')!=1):
                raise UnsupportedCapability()
            vectors=params.get('vectors')
            if name==self._probe['collection']:
                if type(vectors) is not dict or set(vectors)!={'control'} or vectors['control'].get('size')!=1 or vectors['control'].get('distance')!='Cosine':
                    raise UnsupportedCapability()
            else:
                profile=self._profiles[name]
                if type(vectors) is not dict or set(vectors)!={'dense'} or vectors['dense'].get('size')!=profile.dense_profile.dimensions or vectors['dense'].get('distance')!='Cosine' or vectors['dense'].get('multivector_config') is not None:
                    raise UnsupportedCapability()
                sparse=params.get('sparse_vectors')
                if profile.sparse_profile is None:
                    if sparse not in (None,{}):
                        raise UnsupportedCapability()
                elif type(sparse) is not dict or set(sparse)!={'sparse'} or sparse['sparse'].get('modifier') is not None:
                    raise UnsupportedCapability()

    async def _probe_read(self,deadline: float) -> None:
        point=self._probe['point']
        result=(await self._json('POST','/collections/'+self._probe['collection']+'/points',deadline,
            {'ids':[point['id']],'with_payload':True,'with_vector':True})).get('result')
        if type(result) is not list or len(result)!=1 or result[0].get('id')!=point['id'] or result[0].get('payload')!=point['payload'] or result[0].get('vector')!=point['vector']:
            raise IntegrityViolation()

    async def initialize(self,*,deadline: float,provision: Callable[[_Transport,dict[str,Any]],Awaitable[object]] | None=None) -> None:
        self._control_access()
        deadline=deadline_value(deadline)
        if self._active is not None or self._owned is not None or self._closed:
            raise ProviderUnavailable()
        if provision is not None and not callable(provision):
            raise InvalidRequest()
        self._active=asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                self._claim(deadline);await self._spawn();await self._ready(deadline)
                if provision is not None:
                    admin=self._new_transport(self._key,'bootstrap')
                    try:
                        await provision(admin,self.identity()['probe_spec'])
                    finally:
                        await self._close_transport(admin)
                await self._verify_profiles(deadline);await self._probe_read(deadline)
                self._initialized=True;self._gate=True
        except asyncio.CancelledError:
            await self.close()
            raise
        except TimeoutError:
            await self.close()
            raise DeadlineExceeded() from None
        except Exception as error:
            await self.close()
            raise _safe(error) from None
        finally:
            self._active=None

    def _binding(self,value: object,recovery_id: str | None=None) -> _Binding:
        metadata_guard(value)
        keys={'intent_id','owner_token','epoch','dispatch_id'}|({'recovery_id'} if recovery_id is not None else set())
        if type(value) is not dict or set(value)!=keys:
            raise InvalidRequest()
        token=value['owner_token']
        if type(token) is not str or re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',token) is None:
            raise InvalidRequest()
        if recovery_id is not None and value['recovery_id']!=recovery_id:
            raise InvalidRequest()
        return _Binding(_identity(value['intent_id']),token,_count(value['epoch']),_identity(value['dispatch_id']),recovery_id)

    def issue_attempt(self,binding: object,*,deadline: float) -> _Attempt:
        self._control_access()
        deadline_value(deadline)
        if not self._initialized:
            raise IndexNotReady()
        if self._closed or not self._gate or self._active is not None or len(self._attempts)>=256:
            raise ProviderUnavailable()
        self._assert_live()
        parsed=self._binding(binding)
        if parsed.epoch!=self._epoch:
            raise ProviderUnavailable()
        cap=_Attempt();self._attempts[cap]=(parsed,self._key,self._credential_generation)
        return cap

    def transport_for(self,capability: object, *, _control: object | None = None) -> _Transport:
        self._control_access(_control)
        if type(capability) is not _Attempt or capability not in self._attempts or self._closed:
            raise InvalidRequest()
        self._assert_live()
        binding,key,generation=self._attempts[capability]
        if binding.epoch!=self._epoch or generation!=self._credential_generation or (binding.recovery_id is None and not self._gate):
            raise ProviderUnavailable()
        proof=None
        if binding.recovery_id is not None:
            proof=next((item for item,data in self._proofs.items() if data['recovery_id']==binding.recovery_id),None)
            if proof is None:
                raise ProviderUnavailable()
        return self._new_transport(key,'recovery' if proof else 'ordinary',proof)

    async def deliver_worker_credential(self,capability: object,sink: Callable[[dict[str,Any]],Awaitable[object]],*,deadline: float) -> None:
        self._control_access()
        deadline=deadline_value(deadline)
        if not callable(sink) or type(capability) is not _Attempt or capability not in self._attempts:
            raise InvalidRequest()
        binding,key,_=self._attempts[capability]
        if binding.recovery_id is not None:
            raise UnsupportedCapability()
        if binding.epoch!=self._epoch or not self._gate or self._closed or self._active is not None or self._requests:
            raise ProviderUnavailable()
        self._assert_live()
        task=asyncio.current_task();assert task is not None
        self._requests.add(task)
        try:
            async with asyncio.timeout_at(deadline):
                await sink({'endpoint':self._endpoint,'api_key':key,'epoch':binding.epoch,'instance_id':self._instance})
        except TimeoutError:
            raise DeadlineExceeded() from None
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _safe(error) from None
        finally:
            self._requests.discard(task)

    async def _transport_request(self,handle: _Transport,method: str,path: str,body: bytes | None,deadline: float,maximum: int) -> bytes:
        state=self._transports.get(handle)
        if state is None or state.closed or self._closed:
            raise ProviderUnavailable()
        self._control_access(state.control._token if state.control is not None else None)
        deadline=deadline_value(deadline)
        self._assert_live()
        if state.kind=='recovery':
            self.recovery_binding(state.proof)
        if state.control is not None:
            if (type(state.attempt) is not _Attempt or state.attempt not in state.control._attempts
                    or state.control._attempts[state.attempt] is not state.proof
                    or state.attempt not in self._attempts):
                raise InvalidRequest()
            binding,key,generation=self._attempts[state.attempt]
            if (binding.recovery_id is None or binding.epoch!=self._epoch
                    or key!=state.key or generation!=self._credential_generation):
                raise ProviderUnavailable()
        if type(method) is not str or method not in ('GET','PUT','POST','DELETE') or type(path) is not str or len(path)>256:
            raise InvalidRequest()
        if path not in ('/','/cluster','/collections') and _PATH.fullmatch(path) is None:
            raise InvalidRequest()
        route,_,query=path.partition('?')
        write_query=query in ('wait=true','wait=true&ordering=strong')
        if method=='GET':
            if body is not None or query or '/points' in route:
                raise InvalidRequest()
        elif method=='PUT':
            collection_create=state.kind=='bootstrap' and route.startswith('/collections/') and route.count('/')==2 and not query
            if not collection_create and not (route.endswith('/points') and write_query):
                raise InvalidRequest()
        elif method=='POST':
            if not (route.endswith(('/points','/points/scroll')) and not query or route.endswith('/points/delete') and write_query):
                raise InvalidRequest()
        else:
            raise InvalidRequest()
        if method!='GET' and type(body) is not bytes:
            raise InvalidRequest()
        if type(maximum) is not int or not 1<=maximum<=_MAX_BYTES or body is not None and (type(body) is not bytes or len(body)>_MAX_BYTES):
            raise InvalidRequest()
        names=set(self._profiles)|({self._probe['collection']} if state.kind=='bootstrap' else set())
        if path.startswith('/collections/') and path.split('/')[2].split('?')[0] not in names:
            raise InvalidRequest()
        if state.kind!='bootstrap' and method in ('PUT','DELETE') and '/points' not in path:
            raise InvalidRequest()
        if self._requests or (self._active is not None and state.kind!='bootstrap'):
            raise ProviderUnavailable()
        if state.control is not None:
            _session_activity(state.control)
        task=asyncio.current_task();assert task is not None
        self._requests.add(task)
        if state.control is not None:
            self._control_work.add(task)
        try:
            async with asyncio.timeout_at(deadline):
                status,result=await self._http(state.key,method,path,body,deadline,maximum,state)
                if status in (401,403):
                    raise UnauthorizedScope()
                if status!=200:
                    raise ProviderUnavailable()
                return result
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            self._requests.discard(task)
            if state.control is not None:
                self._control_work.discard(task)

    async def _close_transport(self,handle: _Transport) -> None:
        state=self._transports.get(handle)
        if state is not None:
            state.closed=True
            if state.client is not None:
                async with asyncio.timeout(1):
                    await state.client.aclose()
                state.client=None
            self._transports.pop(handle,None)
            if state.control is not None:
                state.control._handles.discard(handle)

    async def _stop(self) -> None:
        self._assert_owner()
        process=self._process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            async with asyncio.timeout(2):
                await process.wait()
        except TimeoutError:
            process.kill()
            async with asyncio.timeout(2):
                await process.wait()
        if process.returncode is None:
            raise ProviderUnavailable()

    async def recover(self,request: object,*,deadline: float,_control: object | None=None) -> _Proof:
        self._control_access(_control)
        deadline=deadline_value(deadline)
        metadata_guard(request)
        if type(request) is not dict or set(request)!={'recovery_id','old_epoch','new_epoch'}:
            raise InvalidRequest()
        recovery_id=_identity(request['recovery_id']);old=_count(request['old_epoch']);new=_count(request['new_epoch'])
        if new!=old+1:
            raise InvalidRequest()
        if not self._initialized or self._closed or self._active is not None or self._requests:
            raise ProviderUnavailable()
        state=self._recovery
        if state is None:
            if old!=self._epoch:
                raise InvalidRequest()
        elif (state['recovery_id'],state['old_epoch'],state['new_epoch'])!=(recovery_id,old,new):
            raise InvalidRequest()
        if self._epoch not in (old,new):
            raise ProviderUnavailable()
        self._gate=False
        self._sealed = False
        self._barrier = None
        self._barriers.clear()
        if state is None:
            self._recovery=state={'recovery_id':recovery_id,'old_epoch':old,'new_epoch':new,'proof':None}
        # A later unknown recovery mutation requires another physical fence,
        # even though SQL correctly retains the same closed gate and epoch.
        self._proofs.clear()
        state['proof']=None
        state['old_key']=self._key
        state['new_key']=secrets.token_hex(32)
        state['credential_generation']='credential-'+secrets.token_hex(16)
        self._active=asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                await self._stop()
                for transport_state in list(self._transports.values()):
                    if transport_state.client is not None:
                        await transport_state.client.aclose();transport_state.client=None
                self._key=state['new_key']
                await self._spawn();await self._ready(deadline);await self._verify_profiles(deadline)
                await self._probe_read(deadline)
                path='/collections/'+self._probe['collection']+'/points?wait=true'
                body=json.dumps({'points':[self._probe['point']]},separators=(',',':')).encode()
                status,_=await self._http(state['old_key'],'PUT',path,body,deadline)
                if status!=401:
                    raise IntegrityViolation()
                result=await self._json('PUT',path,deadline,{'points':[self._probe['point']]})
                if result.get('result',{}).get('status')!='completed':
                    raise ProviderUnavailable()
                await self._probe_read(deadline)
                self._epoch=new
                self._credential_generation=state['credential_generation']
                proof=_Proof()
                self._proofs[proof]={'instance_id':self._instance,'storage_identity':self._storage_id,
                    'supervisor_id':self._supervisor_id,'recovery_id':recovery_id,'old_epoch':old,'new_epoch':new,
                    'credential_generation':self._credential_generation}
                state['proof']=proof
                return proof
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            self._active=None

    def issue_recovery_attempt(self,proof: object,binding: object,*,deadline: float,_control: object | None=None) -> _Attempt:
        self._control_access(_control)
        deadline_value(deadline)
        self.recovery_binding(proof)
        assert isinstance(proof,_Proof)
        if len(self._attempts)>=256:
            raise ProviderUnavailable()
        record=self._proofs[proof]
        parsed=self._binding(binding,record['recovery_id'])
        if parsed.epoch!=self._epoch or self._process is None or self._process.returncode is not None:
            raise ProviderUnavailable()
        cap=_Attempt();self._attempts[cap]=(parsed,self._key,self._credential_generation)
        return cap

    def recovery_binding(self,proof: object) -> Mapping[str,Any]:
        if type(proof) is not _Proof or proof not in self._proofs or self._closed or self._gate or self._sealed:
            raise UnsupportedCapability()
        self._assert_owner()
        record=self._proofs[proof]
        if (record['new_epoch']!=self._epoch or record['credential_generation']!=self._credential_generation
            or self._process is None or self._process.returncode is not None or self._requests or self._active is not None):
            raise ProviderUnavailable()
        return MappingProxyType(dict(record))

    def barrier_binding(self, barrier: object) -> Mapping[str, Any]:
        if (type(barrier) is not _Barrier or barrier not in self._barriers
                or barrier is not self._barrier or not self._sealed or self._gate
                or self._closed):
            raise UnsupportedCapability()
        self._assert_live()
        proof, physical = self._barriers[barrier]
        if (proof not in self._proofs or self._proofs[proof] != physical
                or physical['new_epoch'] != self._epoch
                or physical['credential_generation'] != self._credential_generation
                or self._active is not None or self._requests):
            raise ProviderUnavailable()
        return MappingProxyType(dict(physical))

    async def seal_recovery(self, proof: object, *, deadline: float, _control: object | None = None) -> _Barrier:
        self._control_access(_control)
        deadline = deadline_value(deadline)
        if self._barrier is not None:
            recorded_proof, _ = self._barriers[self._barrier]
            if recorded_proof is proof:
                self.barrier_binding(self._barrier)
                return self._barrier
        physical = dict(self.recovery_binding(proof))
        assert type(proof) is _Proof
        self._sealed = True
        self._gate = False
        self._attempts.clear()
        self._active = asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                for handle in list(self._transports):
                    await handle.close()
                deadline_value(deadline)
                self._assert_live()
                barrier = _Barrier()
                self._barriers[barrier] = (proof, physical)
                self._barrier = barrier
                return barrier
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            self._active = None

    def finish_recovery(self, barrier: object, settlement: object, *, deadline: float,
                        _control: object | None = None) -> None:
        self._control_access(_control)
        from ._qdrant_recovery import settlement_data
        deadline_value(deadline)
        physical = self.barrier_binding(barrier)
        committed = settlement_data(settlement, self, barrier)
        if dict(committed) != dict(physical):
            raise IntegrityViolation()
        deadline_value(deadline)
        self._proofs.clear()
        self._attempts.clear()
        self._barriers.clear()
        self._barrier = None
        self._recovery = None
        self._sealed = False
        self._gate = True

    def attempt_binding(self,capability: object) -> Mapping[str,Any]:
        if type(capability) is not _Attempt or capability not in self._attempts or self._closed:
            raise InvalidRequest()
        self._assert_live()
        binding,_,generation=self._attempts[capability]
        if binding.epoch!=self._epoch or generation!=self._credential_generation or self._active is not None:
            raise ProviderUnavailable()
        if binding.recovery_id is None:
            if not self._gate:
                raise ProviderUnavailable()
        else:
            proof=next((item for item,data in self._proofs.items() if data['recovery_id']==binding.recovery_id),None)
            if proof is None:
                raise InvalidRequest()
            self.recovery_binding(proof)
        result={'instance_id':self._instance,'storage_identity':self._storage_id,
            'supervisor_id':self._supervisor_id,'epoch':binding.epoch,'credential_generation':generation,
            'intent_id':binding.intent_id,'owner_token':binding.owner_token,'dispatch_id':binding.dispatch_id}
        if binding.recovery_id is not None:
            result['recovery_id']=binding.recovery_id
        return MappingProxyType(result)

    async def close(self) -> None:
        self._control_access()
        try:
            async with asyncio.timeout(8):
                await self._close_owned()
        except TimeoutError:
            raise ProviderUnavailable() from None

    async def _close_owned(self) -> None:
        if self._cleaned:
            return
        self._closed=True;self._gate=False
        tasks={task for task in self._requests if task is not asyncio.current_task()}
        if self._active is not None and self._active is not asyncio.current_task():
            tasks.add(self._active)
        for task in tasks:
            task.cancel()
        if tasks:
            done,pending=await asyncio.wait(tasks,timeout=2)
            for task in done:
                if not task.cancelled():
                    task.exception()
            if pending:
                raise ProviderUnavailable()
        try:
            if self._owned is not None:
                await self._stop()
                for handle in list(self._transports):
                    await self._close_transport(handle)
                self._assert_owner()
                config=self._work/'config.yaml'
                if config.exists():
                    config.unlink()
                (self._work/'.cragkit-supervisor.lock'/'owner.json').unlink()
                (self._work/'.cragkit-supervisor.lock').rmdir()
            self._cleaned=True
        except Exception as error:
            raise _safe(error) from None
