"""Rollback-only recovery dispatch permission probes using synthetic SQL metadata.

No request is sent and no opaque native proof or completed HTTP ACK is created.
The caller installs exact migrations and owns the final transaction rollback.
"""
from hashlib import sha256

from qdrant_attestation_schema import (AttestationProbeState, OWNER_OLD, _command,
    _intent_where, _role, _settings, _snapshot, _where)
from qdrant_authority_schema import literal
from qdrant_publication_schema import assert_sql, insert_sql, rejected_sql
from runtime_diagnostics import CleanupFailure

CHECKS = (
    'read_committed_exact_three_migration_fixture',
    'supervisor_blocks_backend_and_advances_same_owner',
    'writer_recovery_insert_denied_under_same_tuple',
    'supervisor_reserves_recovery_journal_and_exact_claim_membership',
    'supervisor_reads_metadata_hash_but_not_request_bytes',
    'supervisor_marks_dispatched_with_fixed_identity',
    'supervisor_sql_synthetic_completion_can_settle_recovery_dispatch',
    'supervisor_cannot_change_request_identity_or_settled_outcome',
    'supervisor_cannot_read_source_revision_or_vector_replay',
    'source_generation_original_preparation_preserved',
)
PROOF_SCOPE = 'recovery_dispatch_sql_synthetic_metadata_only'


def recovery_record(state: AttestationProbeState, **changes):
    """Build a bounded, explicitly non-HTTP recovery journal fixture."""
    if type(state) is not AttestationProbeState:
        raise ValueError('recovery_dispatch_probe_state')
    records = state.records
    request = b'{"synthetic_sql_only":"recovery_dispatch_permission_probe"}'
    row = dict((key, records['document'][key]) for key in ('tenant_id', 'collection', 'document_id'))
    row.update(intent_id=records['intent']['intent_id'], dispatch_id='g1b-sql-recovery',
        instance_id=records['backend']['instance_id'], sequence=2, owner_token=OWNER_OLD,
        backend_epoch=2, credential_generation='synthetic-sql-recovery-credential-2',
        operation='complete_point_upsert', recovery=True, request_bytes=request,
        request_sha256=sha256(request).hexdigest())
    if set(changes) - set(row):
        raise ValueError('recovery_dispatch_probe_field')
    row.update(changes)
    return row


async def run_probes(connection, state: AttestationProbeState) -> list[str]:
    """Exercise real role/constraint mechanics inside one rollback savepoint."""
    if type(state) is not AttestationProbeState or not state.legacy_snapshot:
        raise ValueError('recovery_dispatch_probe_preupgrade_state')
    claims = state.records['claims']
    if not 1 <= len(claims) <= 8 or len({claim['point_id'] for claim in claims}) != len(claims):
        raise ValueError('recovery_dispatch_probe_membership_bound')
    checks = []
    row = recovery_record(state)
    where = _where(state.records)
    intent_where = _intent_where(state.records)
    journal_where = intent_where + ' AND dispatch_id=' + literal(row['dispatch_id'])
    backend_where = 'instance_id=' + literal(row['instance_id'])
    completion = sha256(b'G1b SQL-only synthetic completion, no HTTP acknowledgment').hexdigest()

    async def command(query):
        return await _command(connection, query)

    async def check(condition, label):
        await command(assert_sql(condition, label))

    async def reject(statement, code):
        await command(rejected_sql(statement.rstrip(';') + ';', code))

    await command('SAVEPOINT qa_recovery_dispatch')
    primary = None
    try:
        await _role(connection, state, 'admin')
        await check("current_setting('transaction_isolation')='read committed'", 'recovery_dispatch_read_committed')
        await check('(SELECT count(*)=3 FROM cragkit_qdrant.schema_migrations)', 'recovery_dispatch_three_migrations')
        checks.append(CHECKS[0])
        await _settings(connection, state, writer_owner_token=OWNER_OLD)
        await _role(connection, state, 'supervisor')
        await command("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',epoch=2,recovery_id='g1b-sql-recovery' WHERE " + backend_where)
        await command('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE ' + where)
        await check("(SELECT state='recovery_blocked' AND epoch=2 AND recovery_id='g1b-sql-recovery' FROM cragkit_qdrant.backend_instances WHERE " + backend_where + ')', 'recovery_dispatch_blocked')
        await check('(SELECT backend_epoch=2 AND owner_token=' + literal(OWNER_OLD)
            + '::uuid AND intent_id=' + literal(row['intent_id']) + ' FROM cragkit_qdrant.document_owners WHERE ' + where + ')', 'recovery_dispatch_same_owner')
        checks.append(CHECKS[1])

        await _role(connection, state, 'writer')
        await reject(insert_sql('dispatch_journal', row), '23514')
        checks.append(CHECKS[2])
        await _role(connection, state, 'supervisor')
        await command(insert_sql('dispatch_journal', row))
        for claim in claims:
            point = {key: row[key] for key in ('tenant_id', 'collection', 'document_id', 'intent_id', 'dispatch_id')}
            point.update({key: claim[key] for key in ('backend_namespace', 'physical_collection', 'collection_incarnation', 'point_id')})
            await command(insert_sql('dispatch_points', point))
        # Deferred events are checked inside the same transaction. This is not
        # a separate COMMIT or evidence of a native physical recovery.
        await command('SET CONSTRAINTS ALL IMMEDIATE')
        await command('SET CONSTRAINTS ALL DEFERRED')
        await check('(SELECT count(*)=' + str(len(claims)) + ' FROM cragkit_qdrant.dispatch_points WHERE ' + journal_where + ')', 'recovery_dispatch_exact_membership_count')
        ids = ','.join(literal(claim['point_id']) + '::uuid' for claim in claims)
        await check('(SELECT bool_and(point_id=ANY(ARRAY[' + ids + '])) FROM cragkit_qdrant.dispatch_points WHERE ' + journal_where + ')', 'recovery_dispatch_exact_claims')
        checks.append(CHECKS[3])

        await check('(SELECT recovery AND state=\'reserved\' AND backend_epoch=2 AND request_sha256='
            + literal(row['request_sha256']) + ' FROM cragkit_qdrant.dispatch_journal WHERE ' + journal_where + ')', 'recovery_dispatch_metadata_hash')
        await reject('SELECT request_bytes FROM cragkit_qdrant.dispatch_journal WHERE ' + journal_where, '42501')
        checks.append(CHECKS[4])
        await command("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched' WHERE " + journal_where)
        await check("(SELECT state='dispatched' AND completion_sha256 IS NULL FROM cragkit_qdrant.dispatch_journal WHERE " + journal_where + ')', 'recovery_dispatch_dispatched')
        checks.append(CHECKS[5])
        await command("UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=" + literal(completion) + ' WHERE ' + journal_where)
        await check("(SELECT state='settled' AND completion_sha256=" + literal(completion)
            + ' FROM cragkit_qdrant.dispatch_journal WHERE ' + journal_where + ')', 'recovery_dispatch_synthetic_settled')
        checks.append(CHECKS[6])
        await reject('UPDATE cragkit_qdrant.dispatch_journal SET request_sha256=' + literal('a'*64) + ' WHERE ' + journal_where, '42501')
        await reject("UPDATE cragkit_qdrant.dispatch_journal SET state='dispatched',completion_sha256=NULL WHERE " + journal_where, '23514')
        checks.append(CHECKS[7])
        for table, column in (('document_revisions', 'canonical_utf8'), ('vector_replays', 'dense_blob')):
            await reject('SELECT ' + column + ' FROM cragkit_qdrant.' + table + ' WHERE ' + where, '42501')
        checks.append(CHECKS[8])
        await _role(connection, state, 'admin')
        if await _snapshot(connection, state) != state.legacy_snapshot:
            raise RuntimeError('recovery_dispatch_changed_legacy_facts')
        checks.append(CHECKS[9])
        return checks
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for operation, query in (('probe_rollback', 'ROLLBACK TO SAVEPOINT qa_recovery_dispatch'),
                ('probe_release', 'RELEASE SAVEPOINT qa_recovery_dispatch'), ('probe_reset_role', 'RESET ROLE')):
            try:
                await command(query)
            except BaseException as error:
                failures.append((operation, error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='fixture_setup') from None
