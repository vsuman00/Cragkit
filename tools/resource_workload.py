"""Bounded RST-r1 native workload; fake embeddings and sanitized numeric output."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import math
from pathlib import Path
import resource
import sys
import time

from cragkit import __version__
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit.contracts import parse_request, parse_scope
from cragkit.context import Cl100kCounter
from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
from cragkit.errors import ProviderUnavailable
from cragkit.retrieval import PostgresRetriever
from cragkit.vector_ingestion import PostgresVectorIndexer

_LIMITS = dict(deadline_ms=25000, max_candidates=15, max_attempts=3,
               max_subqueries=3, max_provider_calls=8, max_context_tokens=20000)
_OUTPUT = dict(renderer='cragkit.context.v2', tokenizer='cl100k_base',
               counting_mode='strict', envelope_reserve_tokens=256)
_CHECKS = ('ingestion_fidelity', 'evidence_scope', 'evidence_spans', 'usage_limits',
           'strict_tokens', 'deadlines', 'overload_refused', 'queued_cancelled',
           'active_cancelled', 'reuse_after_queue', 'reuse_after_active', 'cleanup_verified')


class ResourceWorkloadError(ValueError):
    """Fixed diagnostic; never retain native errors or configuration values."""


def _require(condition):
    if not condition:
        raise ResourceWorkloadError('resource_workload_failed')


def _pool_config(value):
    data = dict(value)
    data['sslrootcert'], data['passfile'] = Path(data['sslrootcert']), Path(data['passfile'])
    data.update(max_size=1, max_waiting=1, acquire_timeout=2.0,
                close_timeout=5.0, release_timeout=1.0)
    return PoolConfig.model_validate(data)


def _milliseconds(start):
    value = (time.perf_counter()-start)*1000
    _require(math.isfinite(value) and value > 0)
    return value


async def _observe(predicate, task=None):
    """Bounded polling of native state, never a timer-only dispatch assumption."""
    async with asyncio.timeout(1):
        while not predicate():
            _require(task is None or not task.done())
            await asyncio.sleep(0.001)


async def _healthy(reader):
    async with asyncio.timeout(5):
        async with reader.lease(deadline=asyncio.get_running_loop().time()+5) as connection:
            cursor = await connection.execute('SELECT 1')
            try:
                _require(await cursor.fetchone() == (1,))
            finally:
                await cursor.close()
            await connection.rollback()


async def _cancel_and_join(task):
    task.cancel()
    cancelled = False
    try:
        async with asyncio.timeout(5):
            await task
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise
        cancelled = True
    _require(cancelled and task.cancelled())


async def _contention(reader, tasks):
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), asyncio.Event()
    async def holder():
        async with reader.lease(deadline=loop.time()+10):
            entered.set()
            await release.wait()
    async def waiter():
        async with reader.lease(deadline=loop.time()+10):
            raise ResourceWorkloadError('resource_workload_failed')
    holding = asyncio.create_task(holder());tasks.add(holding)
    waiting = None
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        waiting = asyncio.create_task(waiter());tasks.add(waiting)
        await _observe(lambda: waiting in reader._users and waiting not in reader._leases, waiting)
        refused = False
        async with asyncio.timeout(1):
            try:
                async with reader.lease(deadline=loop.time()+5):
                    pass
            except ProviderUnavailable as error:
                refused = error.code == 'provider_unavailable'
        _require(refused)
        await _cancel_and_join(waiting)
    finally:
        release.set()
        if waiting is not None and not waiting.done():
            await _cancel_and_join(waiting)
        async with asyncio.timeout(5):
            await holding
    await _healthy(reader)


async def _active_cancellation(reader, tasks):
    loop = asyncio.get_running_loop()
    active = []
    async def operation():
        async with reader.lease(deadline=loop.time()+5) as connection:
            warm = await connection.execute('SELECT 1')
            await warm.close()
            active.append(connection)
            cancelled = failed = False
            try:
                cursor = await connection.execute('SELECT pg_sleep(2)')
                await cursor.close()
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True
            try:
                await connection.rollback()
            except Exception:
                failed = True
            if cancelled:
                raise asyncio.CancelledError()
            _require(not failed)
    task = asyncio.create_task(operation());tasks.add(task)
    try:
        # libpq's ACTIVE transaction status is 1 while a native command is in progress.
        await _observe(lambda: bool(active) and active[0].pgconn.transaction_status == 1
            and active[0].pgconn.is_busy(), task)
        await _cancel_and_join(task)
    finally:
        if not task.done():
            await _cancel_and_join(task)
    await _healthy(reader)


class _ByteCounter:
    name = 'fake-byte-v1'
    def count(self, text):
        return len(text.encode('utf-8'))


def _embedder(reader, writer):
    async def fake(body, *, deadline, max_response_bytes):
        task = asyncio.current_task()
        _require(task not in reader._leases and task not in writer._leases)
        _require(asyncio.get_running_loop().time() < deadline)
        value = json.loads(body)
        tokens = sum(len(text.encode('utf-8')) for text in value['input'])
        result = json.dumps(dict(model=FAKE_PROFILE.model,
            data=[dict(index=index, embedding=[1.0]+[0.0]*1535)
                  for index in range(len(value['input']))],
            usage=dict(prompt_tokens=tokens, total_tokens=tokens)), separators=(',', ':')).encode()
        _require(len(result) <= max_response_bytes)
        return result
    return EmbeddingAdapter(fake, _ByteCounter(), profile=FAKE_PROFILE)


def _inspect_result(result, receipt, source, counter):
    _require(result.execution == 'complete' and 1 <= len(result.evidence) <= 15)
    raw = source.encode('utf-8');digest = sha256(raw).hexdigest()
    for evidence in result.evidence:
        _require(evidence.document_id == 'resource-0' and evidence.collection == 'resource-tests'
            and evidence.revision_id == receipt.revision_id and evidence.source_sha256 == digest)
        _require(0 <= evidence.start_byte < evidence.end_byte <= len(raw)
            and raw[evidence.start_byte:evidence.end_byte].decode('utf-8') == evidence.text
            and sha256(evidence.text.encode('utf-8')).hexdigest() == evidence.text_sha256)
    usage = result.usage
    _require(usage.context_counting == 'strict' and counter.count(result.context) == usage.context_tokens
        and usage.context_tokens+256 <= 20000)
    _require(1 <= usage.attempt_count <= 3 and 1 <= usage.provider_calls <= 8
        and usage.cost_kind == 'known' and usage.cost_usd == 0)
    return usage.context_tokens, usage.attempt_count, usage.provider_calls


async def _stage(reader, writer, receipt, source, scope, counter, concurrency, tasks):
    """A fixed worker count bounds admission; no per-request task fanout."""
    loop = asyncio.get_running_loop();rows = [None]*20
    async def worker(worker_id):
        target = PostgresRetriever(reader, mode='hybrid', embedder=_embedder(reader, writer),
            embedding_profile=FAKE_PROFILE, evidence_options=dict(counter=counter))
        for index in range(worker_id, 20, concurrency):
            request = parse_request(dict(request_id=f'resource-{concurrency}-{index}',
                query='support route queue', collection='resource-tests',
                required_filters=[dict(op='eq', field='document_id', value='resource-0')],
                limits=dict(_LIMITS), output_profile=dict(_OUTPUT)))
            started=time.perf_counter();deadline=loop.time()+25
            async with asyncio.timeout_at(deadline):
                result = await target.retrieve(request, scope=scope, deadline=deadline)
            latency = _milliseconds(started)
            _require(loop.time() < deadline and latency < 25000)
            rows[index] = (latency, *_inspect_result(result, receipt, source, counter))
    started=time.perf_counter()
    workers=[asyncio.create_task(worker(index)) for index in range(concurrency)]
    tasks.update(workers)
    await asyncio.gather(*workers)
    elapsed=_milliseconds(started)
    _require(all(row is not None for row in rows))
    return dict(concurrency=concurrency, elapsed_ms=elapsed, latency_ms=[r[0] for r in rows],
        context_tokens=[r[1] for r in rows], attempts=[r[2] for r in rows],
        provider_calls=[r[3] for r in rows], throughput_per_second=20000/elapsed)


async def run_resource_workload(configuration):
    """Run RST-r1 on caller-owned isolated native configuration, without HTTP."""
    reader=writer=None;tasks=set();failure=False;cancelled=False;closed=False;summary=None
    try:
        _require(type(configuration) is dict and set(configuration) == {
            'reader_config', 'writer_config', 'tokenizer_path', 'sdk_root'})
        _require(type(configuration['tokenizer_path']) is str and type(configuration['sdk_root']) is str)
        reader=PoolResource(_pool_config(configuration['reader_config']))
        writer=PoolResource(_pool_config(configuration['writer_config']))
        async with asyncio.timeout(180):
            scope=parse_scope(dict(tenant_id='resource-tenant', principal_id='resource-runner',
                authorization_revision='resource-auth-r1', grant_ids=[]))
            sources=[f'Resource handbook {index}. The support route is queue {index}.' for index in range(3)]
            async def authorize(candidate, collection, document):
                return candidate == scope and collection == 'resource-tests' and document in {
                    'resource-0', 'resource-1', 'resource-2'}
            counter=Cl100kCounter.from_file(configuration['tokenizer_path'])
            indexer=PostgresVectorIndexer(writer, authorize_write=authorize,
                embedder=_embedder(reader, writer), embedding_profile=FAKE_PROFILE)
            await writer.open();ingestion=[];receipts=[]
            for index,source in enumerate(sources):
                started=time.perf_counter();deadline=asyncio.get_running_loop().time()+25
                async with asyncio.timeout_at(deadline):
                    receipt=await indexer.ingest(source, collection='resource-tests',
                        document_id=f'resource-{index}', intent_id=f'resource-ingest-{index}',
                        source_locator=f'resource:synthetic-{index}', scope=scope, deadline=deadline,
                        canonical_options=dict(target_bytes=2048, max_chunk_bytes=4096))
                ingestion.append(_milliseconds(started))
                _require(ingestion[-1] < 25000 and asyncio.get_running_loop().time() < deadline)
                _require(receipt.canonical_sha256 == sha256(source.encode('utf-8')).hexdigest()
                    and receipt.embedding_profile == FAKE_PROFILE.profile_id
                    and receipt.tenant_id == scope.tenant_id and receipt.collection == 'resource-tests'
                    and receipt.document_id == f'resource-{index}')
                receipts.append(receipt)
            await writer.close();await reader.open()
            stages=[]
            for concurrency in (1,2):
                stages.append(await _stage(reader,writer,receipts[0],sources[0],scope,counter,concurrency,tasks))
            await _contention(reader,tasks)
            await _active_cancellation(reader,tasks)
            summary=dict(revision='RST-r1', runtime='python', version=__version__, ingestion_ms=ingestion,
                retrieval=stages, checks={name:True for name in _CHECKS}, provider_http_calls=0,
                active_dispatch_observation=1)
    except asyncio.CancelledError:
        cancelled=True
    except Exception:
        failure=True
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        async def cleanup():
            outcomes=[]
            for target in (reader,writer):
                if target is not None:
                    try:await target.close()
                    except Exception:outcomes.append(False)
            if tasks:
                done,pending=await asyncio.wait(tasks,timeout=1)
                for task in done:
                    if not task.cancelled():task.exception()
                if pending:outcomes.append(False)
            return not outcomes
        cleanup_task=asyncio.create_task(cleanup())
        try:
            async with asyncio.timeout(12):
                closed=await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            cancelled=True
            try:
                async with asyncio.timeout(12):closed=await asyncio.shield(cleanup_task)
            except BaseException:closed=False
        except Exception:
            closed=False
        finally:
            if not cleanup_task.done():
                cleanup_task.cancel()
                await asyncio.wait({cleanup_task},timeout=1)
    if cancelled:raise asyncio.CancelledError()
    if failure or not closed or summary is None:
        raise ResourceWorkloadError('resource_workload_failed')
    summary['peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    _require(summary['peak_rss_bytes'] > 0)
    return summary
