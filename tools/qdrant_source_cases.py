"""Native QS-r1 cases; administrator actions stay in the fixture parent."""
from __future__ import annotations

import asyncio
from copy import deepcopy

from runtime_diagnostics import CleanupFailure

STEP = 'not_started'


class SourceCaseMismatch(RuntimeError):
    def __init__(self, case_id, outcome, spy_calls):
        super().__init__('native_source_case_mismatch')
        self.observation = {'case_id': case_id, 'outcome': outcome, 'provider_spy_calls': spy_calls}


async def run_cases(value, mutate):
    global STEP
    from cragkit._postgres_pool import PoolResource, parse_pool_config
    from cragkit.errors import CragkitError
    from cragkit.execution import ExecutionLedger
    from cragkit.qdrant import HttpxQdrantTransport, QdrantSearchStore
    from cragkit.qdrant_source import PostgresQdrantSourceStore
    from pathlib import Path

    config = dict(value['postgres_config'])
    for key in ('sslrootcert', 'passfile'):
        config[key] = Path(config[key])
    resource = PoolResource(parse_pool_config(config))
    qdrant = value['qdrant']
    transport = HttpxQdrantTransport(qdrant['endpoint'], api_key=qdrant['api_key'], allow_loopback_http=True)
    candidates = QdrantSearchStore(qdrant['config'], transport)
    records = []
    primary = None
    try:
        STEP = 'reader_pool_open'
        await resource.open()
        STEP = 'candidate_initialize'
        await candidates.initialize(deadline=asyncio.get_running_loop().time() + 10)
        for case in value['cases']:
            STEP = 'reset_' + case['id']
            await mutate('reset_' + case['setup'])
            deadline = asyncio.get_running_loop().time() + 10
            request = deepcopy(value['request'])
            request.update(request_id='source-native-' + case['id'], limits={'max_candidates': 1, 'max_provider_calls': 0})
            scope = deepcopy(value['scope'])
            ledger = ExecutionLedger(request['limits'], deadline=deadline)
            STEP = 'candidate_search_' + case['id']
            nominations = await candidates.search_candidates(request, scope=scope, dense=qdrant['dense'],
                branch_limits={'dense': 1}, ledger=ledger, deadline=deadline)
            if len(nominations) != 1:
                raise AssertionError('native_source_candidate_count')
            nomination = nominations[0]
            store = PostgresQdrantSourceStore(resource, qdrant['config'])
            handle = None
            record = {'id': case['id'], 'provider_spy_calls': 0}
            try:
                STEP = 'source_initialize_' + case['id']
                await store.initialize(deadline=deadline)
                STEP = 'source_flow_' + case['id']
                if case['id'] == 'metadata':
                    await mutate('metadata')
                    scope['authorization_revision'] = 'auth-2'
                elif case['id'] == 'tombstone':
                    await mutate('tombstone')
                    scope['authorization_revision'] = 'auth-2'
                elif case['id'] == 'superseded':
                    await mutate('supersede')
                elif case['id'] == 'foreign_scope':
                    scope['tenant_id'] = 'foreign'
                handle = store.open_request(request, scope=scope, deadline=deadline)
                if case['id'] == 'forged_binding':
                    await handle.release({}, purpose='final', max_source_bytes=16777216)
                    raise AssertionError('native_forged_binding_accepted')
                if case['id'] == 'malformed':
                    nomination = nomination.model_dump(mode='json')
                    nomination['payload']['source_locator'] = 'injected'
                fetched = await handle.fetch_candidate(nomination, max_source_bytes=12 if case['id'] == 'budget' else 16777216,
                                                       include_source=case['id'] in ('active', 'retained'))
                record['fetch'] = fetched.model_dump(mode='json')
                record['outcome'] = fetched.state
                if fetched.state == 'verified':
                    if fetched.evidence is None or fetched.evidence.text != 'café 雪':
                        raise AssertionError('native_source_exact_excerpt')
                    if case['id'] in ('active', 'retained') and fetched.private_source.canonical_text != 'A café 雪.\n':
                        raise AssertionError('native_private_source_fidelity')
                    if case['id'] in ('revoke_before_provider', 'revoke_after_provider', 'retained', 'active', 'source_outage'):
                        if case['id'] == 'revoke_before_provider':
                            await mutate('revoke')
                        if case['id'] == 'retained':
                            await mutate('supersede')
                        if case['id'] == 'source_outage':
                            await mutate('source_outage')
                        else:
                            released = await handle.release(fetched.binding, purpose='provider', max_source_bytes=16777216)
                            record['provider'] = released.model_dump(mode='json')
                            if released.state == 'verified':
                                # The spy receives bytes only after the fresh provider gate.
                                if released.evidence.text != 'café 雪':
                                    raise AssertionError('native_provider_excerpt')
                                record['provider_spy_calls'] += 1
                            if case['id'] == 'revoke_after_provider':
                                await mutate('revoke')
                        final = await handle.release(fetched.binding, purpose='final', max_source_bytes=16777216)
                        record['final'] = final.model_dump(mode='json')
                        record['outcome'] = final.state
            except CragkitError as error:
                record['outcome'] = type(error).__name__
            finally:
                await store.close()
            STEP = 'source_assert_' + case['id']
            record['ledger'] = ledger.snapshot()
            if (record['outcome'] != case['outcome'] or record['provider_spy_calls'] != case['provider_spy_calls']
                    or record['ledger']['candidates'] != 1 or record['ledger']['provider_calls'] != 0
                    or record['ledger']['pending'] != 0):
                raise SourceCaseMismatch(case['id'], record['outcome'], record['provider_spy_calls'])
            if case['id'] == 'retained' and not (record['provider']['stale'] and record['final']['stale']):
                raise AssertionError('native_retained_not_stale')
            records.append(record)
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for label, owned in (('candidate_close', candidates), ('transport_close', transport), ('reader_pool_close', resource)):
            try:
                await owned.close()
            except BaseException as error:
                failures.append((label, error))
        if failures:
            raise CleanupFailure(failures, primary=primary) from None
    return records
