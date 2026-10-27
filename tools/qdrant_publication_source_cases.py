"""Native public publication/source acceptance on parent-owned disposable fixtures."""
from __future__ import annotations

CHECKS = (
    'stage_has_no_search_candidates_or_active_generation',
    'prepared_replica_has_candidates_but_no_source_release',
    'published_generation_releases_exact_utf8_sources',
    'prepared_successor_preserves_previous_active_sources',
    'published_successor_replaces_fresh_source_admission',
    'retained_previous_binding_releases_exact_stale_evidence',
    'foreign_scope_cannot_search_or_release_source',
    'no_sql_lease_across_callback_or_http_and_borrowed_cleanup',
)
ERRORS = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability',
    'InvalidRequest', 'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady',
    'BudgetExhausted', 'CancelledError', 'AbortError', 'internal'))


class NativePublicationSourceFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('publication_source_native_case_failed')
        self.observation = observation


async def python_publication_source_cases(value):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from hashlib import sha256
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import UnauthorizedScope
    from cragkit.qdrant import HttpxQdrantTransport, QdrantSearchStore
    from cragkit.qdrant_source import PostgresQdrantSourceStore
    from cragkit.qdrant_publication import (QdrantPublicationManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier)
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']
    def configuration(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        config = PoolConfig.model_validate(raw)
        if config.max_size != 1:
            raise RuntimeError('source_fixture_pool_ceiling')
        return config
    resource = PoolResource(configuration(value['writer_config']))
    supervisor_resource = PoolResource(configuration(value['supervisor_config']))
    reader = PoolResource(configuration(value['reader_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    foreign = TrustedScope.model_validate(dict(inputs['scope'], tenant_id='foreign'))
    base, successor = inputs['stage'], inputs['successor']
    collection = base['manifest']['collection']
    document = base['manifest']['document_id']
    deadline = asyncio.get_running_loop().time() + 105
    checks, observations, stores, requests, handles = [], [], [], [], []
    endpoint = primary = manager = candidates = candidate_transport = publish_task = None
    credential = {}
    active_leases = 0
    callback_count = http_count = 0
    pause = dict(stage=None, reached=None, resume=None)
    original_lease = resource.lease
    @asynccontextmanager
    async def counted_lease(**options):
        nonlocal active_leases
        async with original_lease(**options) as connection:
            active_leases += 1
            try:
                yield connection
            finally:
                active_leases -= 1
    resource.lease = counted_lease
    def no_lease():
        if active_leases:
            raise RuntimeError('source_writer_lease_crosses_business_await')
    def reference(stage):
        return dict(collection=collection, document_id=document, intent_id=stage['intent']['intent_id'])
    def context(stage):
        return dict(scope=scope, **reference(stage), owner_token='00000000-0000-4000-8000-000000000099')
    def ledger():
        return ExecutionLedger(Limits(deadline_ms=60000, max_attempts=1, max_provider_calls=0), deadline=deadline)
    async def authorize(selected_scope, selected_collection, selected_document):
        nonlocal callback_count
        no_lease()
        if selected_scope != scope or (selected_collection, selected_document) != (collection, document):
            raise RuntimeError('source_authorizer_target')
        selected = pause['stage']
        if selected is not None:
            intent = await writer.inspect(context(selected), deadline=deadline)
            no_lease()
            if intent is not None and intent['state'] == 'prepared':
                callback_count += 1
                pause['reached'].set()
                await asyncio.wait_for(pause['resume'].wait(), 15)
                no_lease()
        return True
    target = '/collections/' + inputs['config']['physical_collection']
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline)
    original_transport_for = supervisor.transport_for
    class ObservedHandle:
        def __init__(self, inner):
            self.inner = inner
            self.closed = False
        async def request(self, *args, **kwargs):
            nonlocal http_count
            no_lease()
            http_count += 1
            result = await self.inner.request(*args, **kwargs)
            no_lease()
            return result
        async def close(self):
            await self.inner.close()
            self.closed = True
    def observed_transport(capability):
        handle = ObservedHandle(original_transport_for(capability))
        handles.append(handle)
        return handle
    supervisor.transport_for = observed_transport
    async def sink(raw):
        credential.update(raw)
    async def new_request(selected_scope=scope):
        store = PostgresQdrantSourceStore(reader, inputs['config'])
        stores.append(store)
        await store.initialize(deadline=deadline)
        request = store.open_request(inputs['request'], scope=selected_scope, deadline=deadline)
        requests.append(request)
        return request
    stages = {stage['manifest']['generation_id']: stage for stage in (base, successor)}
    def observe(phase, nomination, fetched, stale=False):
        payload = nomination.payload
        if fetched.state != 'verified':
            if (fetched.state != 'unavailable' or fetched.evidence is not None or fetched.binding is not None
                    or fetched.private_source is not None or fetched.source_bytes != 0 or fetched.stale):
                raise RuntimeError('source_unavailable_disclosed_data')
            observations.append([phase, nomination.point_id, fetched.state] + [None] * 13)
            return
        stage = stages[payload.generation_id]
        canonical = stage['canonical_text'].encode('utf-8')
        member = next(item for item in stage['manifest']['members'] if item['point_id'] == nomination.point_id)
        manifest = stage['manifest']
        if (any(getattr(payload, key) != manifest[key] for key in
                ('document_id', 'revision_id', 'generation_id', 'source_sha256'))
                or any(getattr(payload, key) != member[key] for key in
                ('chunk_id', 'start_byte', 'end_byte', 'text_sha256'))):
            raise RuntimeError('source_nomination_fixture_identity')
        start, end = member['start_byte'], member['end_byte']
        excerpt = canonical[start:end]
        text = excerpt.decode('utf-8')
        evidence = fetched.evidence
        evidence_id = sha256(request_bytes(['cragkit.evidence.v1', payload.tenant_id, collection,
            document, payload.revision_id, payload.chunk_id, str(start), str(end), sha256(excerpt).hexdigest()])).hexdigest()
        expected = dict(evidence_id=evidence_id, collection=collection, document_id=document,
            revision_id=payload.revision_id, chunk_id=payload.chunk_id,
            source_locator=stage['manifest']['source_locator'], start_byte=start, end_byte=end,
            text=text, source_sha256=sha256(canonical).hexdigest(), text_sha256=sha256(excerpt).hexdigest())
        if (evidence is None or evidence.model_dump(mode='json') != expected or fetched.binding is None
                or fetched.source_bytes != len(canonical) or fetched.stale is not stale
                or fetched.private_source is None
                or fetched.private_source.canonical_text != stage['canonical_text']
                or fetched.private_source.source_sha256 != expected['source_sha256']):
            raise RuntimeError('source_exact_evidence_mismatch')
        public = fetched.model_dump(mode='json')
        if 'binding' in public or 'private_source' in public:
            raise RuntimeError('source_public_serialization_disclosed_private')
        observations.append([phase, nomination.point_id, fetched.state, evidence_id, document,
            payload.revision_id, payload.generation_id, payload.chunk_id, expected['source_sha256'],
            expected['text_sha256'], str(start), str(end), text, stage['canonical_text'], str(len(canonical)), stale])
    async def search(selected_scope=scope):
        accounting = ExecutionLedger(inputs['request']['limits'], deadline=deadline)
        result = await candidates.search_candidates(inputs['request'], scope=selected_scope,
            dense=base['dense_vectors'][0], branch_limits={'dense': 8}, ledger=accounting, deadline=deadline)
        usage = accounting.snapshot()
        if usage['candidates'] != 8 or usage['provider_calls'] or usage['pending']:
            raise RuntimeError('source_candidate_accounting')
        return sorted(result, key=lambda nomination: nomination.point_id)
    async def phase(name, count, active_generation):
        nominations = await search()
        if len(nominations) != count:
            raise RuntimeError('source_candidate_count')
        observations.append(['phase', name, str(count)])
        request = await new_request()
        for nomination in nominations:
            fetched = await request.fetch_candidate(nomination, max_source_bytes=16777216, include_source=True)
            verified = nomination.payload.generation_id == active_generation
            if (fetched.state == 'verified') != verified:
                raise RuntimeError('source_fresh_generation_admission')
            observe(name, nomination, fetched)
        await request.close()
        await stores[-1].close()
        return nominations
    async def paused_publish(stage, phase_name, count, active_generation):
        nonlocal publish_task
        pause.update(stage=stage, reached=asyncio.Event(), resume=asyncio.Event())
        publish_task = asyncio.create_task(manager.publish(reference(stage), scope, ledger(), deadline=deadline))
        reached = asyncio.create_task(pause['reached'].wait())
        try:
            done, _ = await asyncio.wait({reached, publish_task}, timeout=20, return_when=asyncio.FIRST_COMPLETED)
            if reached not in done:
                if publish_task in done:
                    await publish_task
                raise RuntimeError('source_prepared_pause_missing')
        finally:
            reached.cancel()
            await asyncio.gather(reached, return_exceptions=True)
        snapshot = await writer.manager_snapshot(context(stage), deadline=deadline)
        if snapshot['intent']['state'] != 'prepared' or snapshot['document']['active_generation_id'] != active_generation:
            raise RuntimeError('source_prepared_pointer_changed')
        await phase(phase_name, count, active_generation)
        pause['resume'].set()
        result = plain(await publish_task)
        publish_task = None
        pause['stage'] = None
        if result['state'] != 'published' or result['published'] is not True:
            raise RuntimeError('source_publication_failed')
    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        await observed_listener(endpoint)
        await resource.open()
        await supervisor_resource.open()
        manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, authorize)
        await manager.initialize(deadline=deadline)
        capability = supervisor.issue_attempt(dict(intent_id='source-reader',
            owner_token='00000000-0000-4000-8000-000000000098', epoch=1, dispatch_id='source-reader'), deadline=deadline)
        await supervisor.deliver_worker_credential(capability, sink, deadline=deadline)
        await supervisor_resource.close()
        await reader.open()
        candidate_transport = HttpxQdrantTransport(credential['endpoint'], api_key=credential['api_key'], allow_loopback_http=True)
        class CandidateTransport:
            bounded_responses = cancellation_safe = True
            async def request(self, *args, **kwargs):
                nonlocal http_count
                no_lease()
                http_count += 1
                raw = await candidate_transport.request(*args, **kwargs)
                no_lease()
                return raw
        candidates = QdrantSearchStore(inputs['config'], CandidateTransport())
        await candidates.initialize(deadline=deadline)
        await manager.stage(base, scope, ledger(), deadline=deadline)
        await phase('staged', 0, None)
        if (await writer.manager_snapshot(context(base), deadline=deadline))['document']['active_generation_id'] is not None:
            raise RuntimeError('source_stage_active')
        checks.append(CHECKS[0])
        await paused_publish(base, 'g1_prepared', 2, None)
        checks.append(CHECKS[1])
        nominations = await phase('g1_published', 2, base['manifest']['generation_id'])
        retained_nomination = nominations[0]
        retained_request = await new_request()
        retained = await retained_request.fetch_candidate(retained_nomination, max_source_bytes=16777216, include_source=True)
        if retained.state != 'verified':
            raise RuntimeError('source_retained_binding_missing')
        checks.append(CHECKS[2])
        await manager.stage(successor, scope, ledger(), deadline=deadline)
        await paused_publish(successor, 'g2_prepared', 4, base['manifest']['generation_id'])
        checks.append(CHECKS[3])
        nominations = await phase('g2_published', 4, successor['manifest']['generation_id'])
        checks.append(CHECKS[4])
        for purpose in ('provider', 'final'):
            name = 'retained_' + purpose
            observations.append(['phase', name, '1'])
            fetched = await retained_request.release(retained.binding, purpose=purpose,
                max_source_bytes=16777216, include_source=True)
            observe(name, retained_nomination, fetched, stale=True)
        checks.append(CHECKS[5])
        if await search(foreign):
            raise RuntimeError('source_foreign_candidates')
        observations.append(['phase', 'foreign_search', '0'])
        foreign_request = await new_request(foreign)
        selected = next(item for item in nominations if item.payload.generation_id == successor['manifest']['generation_id'])
        try:
            await foreign_request.fetch_candidate(selected, max_source_bytes=16777216, include_source=True)
        except UnauthorizedScope:
            observations.append(['foreign_source', 'UnauthorizedScope'])
        else:
            raise RuntimeError('source_foreign_release')
        checks.append(CHECKS[6])
        await manager.close()
        await writer.initialize(deadline=deadline)
        await writer.manager_snapshot(context(successor), deadline=deadline)
        if supervisor.profile_binding(inputs['config'])['alive'] is not True or callback_count != 2 or not http_count:
            raise RuntimeError('source_borrowed_dependency_closed')
        if any(not handle.closed for handle in handles):
            raise RuntimeError('source_owned_transport_handle_open')
        no_lease()
        checks.append(CHECKS[7])
        return dict(runtime='python', checks=checks, proof_scope='public_source_publication_only',
            source_observations_sha256=sha256(request_bytes(observations)).hexdigest())
    except BaseException as error:
        primary = error
        name = type(error).__name__
        raise NativePublicationSourceFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 12
        async def cleanup(operation, function):
            try:
                await asyncio.wait_for(function(), max(.001, min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException as error:
                failures.append((operation, error))
        if publish_task is not None:
            publish_task.cancel()
            async def drain():
                try:
                    await publish_task
                except asyncio.CancelledError:
                    pass
            await cleanup('publish_drain', drain)
        owned = [('request_close', item) for item in requests] + [('source_close', item) for item in stores]
        if candidates is not None:
            owned.append(('candidate_close', candidates))
        if candidate_transport is not None:
            owned.append(('transport_close', candidate_transport))
        if manager is not None:
            owned.append(('manager_close', manager))
        if callable(getattr(transport, 'close', None)):
            owned.append(('transport_close', transport))
        owned += [('transport_close', item) for item in handles]
        owned += [('recovery_close', recovery)]
        if callable(getattr(verifier, 'close', None)):
            owned.append(('verifier_close', verifier))
        owned += [('writer_close', writer), ('resource_close', resource),
            ('resource_close', reader), ('supervisor_resource_close', supervisor_resource), ('controller_close', supervisor)]
        for operation, item in owned:
            await cleanup(operation, item.close)
        credential.clear()
        if endpoint is not None:
            async def listener():
                await observed_listener(endpoint, allow_absent=True)
            await cleanup('listener_close', listener)
        if failures:
            closed = [dict(operation=operation, outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal')
                for operation, error in failures][:64]
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicationSourceFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=closed)) from None
