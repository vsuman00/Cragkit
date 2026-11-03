"""MRR-r1 opt-in quarantined recovery on one disposable PostgreSQL cluster."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DATABASE = 'cragkit_restore'
IDENTITY = ('tenant_id', 'collection_id', 'document_id')
PHASE = 'arguments'


def require(condition):
    if not condition:
        raise ValueError('backup_recovery_invalid')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def authority_digest(value):
    return sha256(encoded(value)).hexdigest()


def validate_authority(restored, current, expected_digest):
    """Only the separately captured current authority can gate runtime release."""
    require(type(current) is list and bool(current) and len(current) <= 10
            and authority_digest(current) == expected_digest)
    def keyed(rows):
        require(type(rows) is list and bool(rows) and len(rows) <= 10)
        result = {}
        for row in rows:
            require(type(row) is dict and set(row) == {*IDENTITY, 'authorization_revision', 'tombstoned', 'grants'})
            require(all(type(row[name]) is str and bool(row[name]) for name in IDENTITY))
            revision = row['authorization_revision']
            require(type(revision) is str and re.fullmatch(r'0|[1-9][0-9]{0,15}', revision) is not None
                    and type(row['tombstoned']) is bool and type(row['grants']) is list)
            grants = set()
            for grant in row['grants']:
                require(type(grant) is dict and set(grant) == {'grant_id', 'principal_id', 'authorization_revision'}
                        and type(grant['grant_id']) is str and bool(grant['grant_id'])
                        and (grant['principal_id'] is None or type(grant['principal_id']) is str)
                        and grant['authorization_revision'] == revision and grant['grant_id'] not in grants)
                grants.add(grant['grant_id'])
            key = tuple(row[name] for name in IDENTITY)
            require(key not in result)
            result[key] = row
        return result
    old, latest = keyed(restored), keyed(current)
    require(old.keys() == latest.keys())
    for key, row in latest.items():
        require(int(row['authorization_revision']) >= int(old[key]['authorization_revision'])
                and (not old[key]['tombstoned'] or row['tombstoned']))
    return latest


def verify_backup(path, expected_digest):
    """Refuse missing, changed, linked or broadly readable task archives."""
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= 16 * 1024 * 1024)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino))
        with os.fdopen(descriptor, 'rb', closefd=False) as source:
            raw = source.read(16 * 1024 * 1024 + 1)
        require(raw.startswith(b'PGDMP') and sha256(raw).hexdigest() == expected_digest)
        after = os.fstat(descriptor)
        require((opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
    finally:
        os.close(descriptor)


def database_config(configuration):
    """Keep a database-specific passfile inside the fixture's private directory."""
    config = dict(configuration)
    require(config['dbname'] == 'postgres')
    source = Path(config['passfile'])
    require(source.is_file() and not source.is_symlink()
            and stat.S_IMODE(source.stat().st_mode) == 0o600)
    raw = source.read_bytes()
    require(raw.count(b':postgres:') == 1)
    destination = source.with_name(source.name + '.restore')
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as target:
        target.write(raw.replace(b':postgres:', b':' + DATABASE.encode() + b':', 1))
    config.update(dbname=DATABASE, passfile=str(destination))
    return config


def cli(binary, configuration, arguments):
    """Use scalar libpq environment; no password or URI reaches argv/output."""
    from measure_default_resources import SAFE_ENV
    environment = {key: os.environ[key] for key in SAFE_ENV if key in os.environ}
    environment.update(PGHOST=configuration['host'], PGPORT=str(configuration['port']),
        PGDATABASE=configuration['dbname'], PGUSER=configuration['user'],
        PGPASSFILE=str(configuration['passfile']), PGSSLMODE='verify-full',
        PGSSLROOTCERT=str(configuration['sslrootcert']), PGCONNECT_TIMEOUT='5',
        PGOPTIONS='-c statement_timeout=30000 -c lock_timeout=2000')
    result = subprocess.run([str(binary), *arguments], env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
    require(result.returncode == 0)


async def connect(configuration, *, autocommit=False):
    import psycopg
    return await psycopg.AsyncConnection.connect(**{k: v for k, v in configuration.items() if k != 'max_size'},
        sslmode='verify-full', connect_timeout=5, autocommit=autocommit,
        options='-c statement_timeout=30000 -c lock_timeout=2000')


async def rows(connection, query, values=None):
    async with await connection.execute(query, values) as cursor:
        return await cursor.fetchall()


async def authority(connection):
    documents = await rows(connection, 'SELECT tenant_id,collection_id,document_id,authorization_revision,tombstoned '
        'FROM cragkit.documents ORDER BY tenant_id,collection_id,document_id')
    output = []
    for tenant, collection, document, revision, tombstoned in documents:
        grants = await rows(connection, 'SELECT grant_id,principal_id,authorization_revision '
            'FROM cragkit.document_grants WHERE tenant_id=%s AND collection_id=%s AND document_id=%s ORDER BY grant_id',
            (tenant, collection, document))
        output.append(dict(tenant_id=tenant, collection_id=collection, document_id=document,
            authorization_revision=revision, tombstoned=tombstoned,
            grants=[dict(zip(('grant_id', 'principal_id', 'authorization_revision'), grant)) for grant in grants]))
    return output


async def immutable_snapshot(connection):
    result = {}
    for table in ('collections', 'document_revisions', 'index_generations', 'chunks', 'chunk_lexical',
                  'chunk_vectors_fake_1536', 'embedding_profiles', 'migration_history'):
        value = await rows(connection, "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM cragkit." + table + ' t')
        result[table] = sha256(value[0][0].encode()).hexdigest()
    for label, query in {
        'document_content': "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM (SELECT tenant_id,collection_id,document_id,active_generation_id,metadata,created_at FROM cragkit.documents) t",
        'setup_history': "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM cragkit_vector.setup_history t",
        'policies': "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM (SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname IN ('cragkit','cragkit_vector')) t",
        'table_acl': "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM (SELECT n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,a.grantee,a.grantor,a.privilege_type,a.is_grantable FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN LATERAL aclexplode(c.relacl) a ON true WHERE n.nspname IN ('cragkit','cragkit_vector')) t",
        'function_acl': "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM (SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) arguments,a.grantee,a.grantor,a.privilege_type,a.is_grantable FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace LEFT JOIN LATERAL aclexplode(p.proacl) a ON true WHERE n.nspname IN ('cragkit','cragkit_vector')) t",
    }.items():
        value = await rows(connection, query)
        result[label] = sha256(value[0][0].encode()).hexdigest()
    return result


async def assert_quarantine(admin, role_configs, target_configuration=None):
    require(all(config['dbname'] == DATABASE for config in role_configs))
    if target_configuration is not None:
        require(all(all(config[field] == target_configuration[field]
                        for field in ('host', 'port', 'dbname', 'sslrootcert')) for config in role_configs))
        async with await connect(target_configuration) as target_admin:
            require(await rows(target_admin, 'SELECT current_database(),1') == [(DATABASE, 1)])
    else:
        require(await rows(admin, 'SELECT current_database(),1') == [(DATABASE, 1)])
    names = [config['user'] for config in role_configs]
    require(await rows(admin, 'SELECT rolname,rolcanlogin FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname',
        (names,)) == sorted((name, False) for name in names))
    require(await rows(admin, 'SELECT count(*) FROM pg_stat_activity WHERE usename=ANY(%s)', (names,)) == [(0,)])
    for configuration in role_configs:
        observed = await refusal_observation(configuration)
        require(observed['connected'] is False)
        known_authorization = (observed['error_type'] in ('operational_error', 'database_error')
            and observed['sqlstate'] in ('28000', '42501'))
        observed_startup_form = (observed['error_type'] == 'operational_error'
            and observed['sqlstate'] is None and observed['pgconn_present'] is True
            and observed['pgconn_status'] == 1)
        require(known_authorization or observed_startup_form)


async def refusal_observation(configuration):
    """Inspect only fixed type/state fields, never libpq's error message."""
    import psycopg
    try:
        connection = await connect(configuration)
    except Exception as error:
        category = ('operational_error' if isinstance(error, psycopg.OperationalError)
                    else 'database_error' if isinstance(error, psycopg.Error) else 'other_error')
        state = getattr(error, 'sqlstate', None)
        if state is not None and (type(state) is not str or re.fullmatch('[0-9A-Z]{5}', state) is None):
            state = 'unknown'
        pgconn = getattr(error, 'pgconn', None)
        status = getattr(pgconn, 'status', None)
        if status not in (0, 1):
            status = None
        return dict(connected=False, error_type=category, sqlstate=state,
                    pgconn_present=pgconn is not None, pgconn_status=status)
    else:
        try:
            healthy = await rows(connection, 'SELECT 1') == [(1,)]
        finally:
            await connection.close()
        return dict(connected=True, healthy=healthy)


async def quarantine_probe(args):
    """Diagnose the role handshake in an empty isolated database, without data."""
    global PHASE
    from psycopg import sql
    from postgres_vector_fixture import V6PostgresFixture
    from run_release_evaluation import save
    require(sys.flags.isolated and sys.dont_write_bytecode)
    args.output.mkdir(mode=0o700)
    PHASE = 'quarantine_probe'
    with V6PostgresFixture(args.prepared_postgres_bin, args.output/'fixture') as fixture:
        roles = await fixture.provision(tenants=('recovery-tenant',), collections=('recovery-tests',))
        async with await connect(fixture.config, autocommit=True) as admin:
            await admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(DATABASE)))
            restored_admin = database_config(fixture.config)
            restored_roles = (database_config(roles.reader), database_config(roles.writer))
            before = [await refusal_observation(configuration) for configuration in restored_roles]
            require(all(value == dict(connected=True, healthy=True) for value in before))
            for role in restored_roles:
                await admin.execute(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(role['user'])))
            await admin.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(DATABASE)))
            names = [role['user'] for role in restored_roles]
            can_login = await rows(admin, 'SELECT rolcanlogin FROM pg_roles WHERE rolname=ANY(%s)', (names,))
            sessions = await rows(admin, 'SELECT count(*) FROM pg_stat_activity WHERE usename=ANY(%s)', (names,))
            require(can_login == [(False,), (False,)] and sessions == [(0,)])
            async with await connect(restored_admin) as recovered:
                target_admin_healthy = await rows(recovered, 'SELECT 1') == [(1,)]
            after = [await refusal_observation(configuration) for configuration in restored_roles]
            require(all(value['connected'] is False for value in after))
            result = dict(revision='MRR-r1', state='observed', kind='empty_database_quarantine_probe',
                before=before, after=after, disabled_roles=2, runtime_sessions=0,
                target_admin_healthy=target_admin_healthy, provider_http_calls=0)
            address = fixture.config['host'], fixture.config['port']
    try:
        connection = socket.create_connection(address, timeout=.2)
    except ConnectionRefusedError:
        pass
    else:
        connection.close()
        require(False)
    result['cleanup_verified'] = True
    save(args.output/'quarantine-observation.json', result)
    return result


async def reconcile(admin, current, expected_digest):
    # Validate inside the transaction and before deleting or updating anything.
    async with admin.transaction():
        admitted = validate_authority(await authority(admin), current, expected_digest)
        for key, row in admitted.items():
            await admin.execute('DELETE FROM cragkit.document_grants WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', key)
            await admin.execute('UPDATE cragkit.documents SET authorization_revision=%s,tombstoned=%s '
                'WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                (row['authorization_revision'], row['tombstoned'], *key))
            for grant in row['grants']:
                await admin.execute('INSERT INTO cragkit.document_grants '
                    '(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES (%s,%s,%s,%s,%s,%s)',
                    (*key, grant['grant_id'], grant['principal_id'], grant['authorization_revision']))
        require(await authority(admin) == current)


async def seed(configuration):
    from cragkit._postgres_pool import PoolResource
    from cragkit.contracts import parse_scope
    from cragkit.vector_ingestion import PostgresVectorIndexer
    from cragkit.embeddings import FAKE_PROFILE
    from resource_workload import _pool_config, _embedder
    writer, reader = PoolResource(_pool_config(configuration)), PoolResource(_pool_config(configuration))
    scope = parse_scope(dict(tenant_id='recovery-tenant', principal_id='recovery-reader',
        authorization_revision='1', grant_ids=[]))
    async def authorize(candidate, collection, document):
        return candidate == scope and collection == 'recovery-tests' and document in ('allowed', 'revoked', 'deleted')
    receipts = {}
    try:
        indexer = PostgresVectorIndexer(writer, authorize_write=authorize,
            embedder=_embedder(reader, writer), embedding_profile=FAKE_PROFILE)
        await writer.open()
        for document in ('allowed', 'revoked', 'deleted'):
            source = f'Recovery handbook {document}. The support route is queue {document}.'
            receipt = await indexer.ingest(source, scope=scope, collection='recovery-tests', document_id=document,
                intent_id='recovery-ingest-' + document, source_locator='synthetic:recovery-' + document,
                deadline=asyncio.get_running_loop().time() + 25,
                canonical_options=dict(target_bytes=2048, max_chunk_bytes=4096))
            require(receipt.canonical_sha256 == sha256(source.encode()).hexdigest() and receipt.chunk_count == 1)
            receipts[document] = dict(source=source, revision_id=receipt.revision_id)
    finally:
        await writer.close()
        await reader.close()
    return receipts


async def python_sources(configuration, tokenizer, expected):
    from cragkit._postgres_pool import PoolResource
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.context import Cl100kCounter
    from cragkit.retrieval import PostgresRetriever
    from resource_workload import _pool_config
    resource = PoolResource(_pool_config(configuration))
    checks = {}
    try:
        counter = Cl100kCounter.from_file(tokenizer)
        await resource.open()
        retriever = PostgresRetriever(resource, mode='lexical', evidence_options=dict(counter=counter))
        for name, document, tenant, revision, allowed in (
            ('allowed_exact_source', 'allowed', 'recovery-tenant', '2', True),
            ('revoked_denied', 'revoked', 'recovery-tenant', '2', False),
            ('foreign_tenant_denied', 'allowed', 'recovery-foreign', '2', False),
            ('tombstone_denied', 'deleted', 'recovery-tenant', '2', False),
            ('held_old_scope_denied', 'allowed', 'recovery-tenant', '1', False),
        ):
            request = parse_request(dict(request_id='recovery-' + name, query='support route',
                collection='recovery-tests', required_filters=[dict(op='eq', field='document_id', value=document)],
                limits=dict(deadline_ms=10000, max_candidates=5, max_context_tokens=2000),
                output_profile=dict(renderer='cragkit.context.v2', tokenizer='cl100k_base',
                    counting_mode='strict', envelope_reserve_tokens=128)))
            scope = parse_scope(dict(tenant_id=tenant, principal_id='recovery-reader',
                authorization_revision=revision, grant_ids=[]))
            result = await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time() + 10)
            require(result.execution == 'complete' and result.usage.provider_calls == 0)
            if allowed:
                require(len(result.evidence) == 1)
                evidence = result.evidence[0]
                raw = expected['source'].encode()
                require(evidence.document_id == 'allowed' and evidence.collection == 'recovery-tests'
                    and evidence.revision_id == expected['revision_id'] and evidence.source_sha256 == sha256(raw).hexdigest()
                    and evidence.start_byte == 0 and evidence.end_byte == len(raw)
                    and evidence.text.encode() == raw and evidence.text_sha256 == sha256(raw).hexdigest())
            else:
                require(not result.evidence and result.context == '[]')
            checks[name] = True
    finally:
        await resource.close()
    return dict(revision='MRR-r1', runtime='python', checks=checks, provider_http_calls=0)


async def run(args):
    global PHASE
    require(sys.flags.isolated and sys.dont_write_bytecode)
    require(not any(os.environ.get(name) for name in ('PYTHONPATH', 'PYTHONHOME', 'NODE_PATH', 'NODE_OPTIONS')))
    from psycopg import sql
    from check_postgres import migrations, migration_script
    from measure_default_resources import pressure_guard
    from measure_native_resources import child
    from postgres_vector_fixture import V6PostgresFixture
    from run_release_evaluation import save
    import cragkit
    require(Path(cragkit.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
            and not Path(cragkit.__file__).resolve().is_relative_to(ROOT/'packages/python/src'))
    args.output.mkdir(mode=0o700)
    pressures = []
    pressure_guard(pressures)
    PHASE = 'fixture'
    with V6PostgresFixture(args.prepared_postgres_bin, args.output/'fixture') as fixture:
        roles = await fixture.provision(tenants=('recovery-tenant', 'recovery-foreign'), collections=('recovery-tests',))
        PHASE = 'seed'
        receipts = await seed(roles.writer)
        async with await connect(fixture.config, autocommit=True) as admin:
            # A valid empty foreign collection exercises actual scoped search,
            # rather than failing early because collection metadata is absent.
            await admin.execute('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES (%s,%s)',
                ('recovery-foreign', 'recovery-tests'))
            baseline = await immutable_snapshot(admin)
            old_authority = await authority(admin)
            PHASE = 'backup'
            archive = args.output/'source.dump'
            descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            cli(args.prepared_postgres_bin/'pg_dump', fixture.config, ['--format=custom', '--file', str(archive)])
            digest = sha256(archive.read_bytes()).hexdigest()
            verify_backup(archive, digest)
            PHASE = 'current_authority'
            async with admin.transaction():
                await admin.execute("UPDATE cragkit.documents SET authorization_revision='2',tombstoned=(document_id='deleted')")
                await admin.execute("UPDATE cragkit.document_grants SET authorization_revision='2'")
                # Retain the deleted document's current grant: its denial must
                # depend on the tombstone, independently of grant revocation.
                await admin.execute("DELETE FROM cragkit.document_grants WHERE document_id='revoked'")
            current = await authority(admin)
            current_digest = authority_digest(current)
            validate_authority(old_authority, current, current_digest)
            require(await immutable_snapshot(admin) == baseline)
            PHASE = 'quarantine'
            for role in (roles.reader, roles.writer):
                await admin.execute(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(role['user'])))
            require(await rows(admin, 'SELECT count(*) FROM pg_database WHERE datname=%s', (DATABASE,)) == [(0,)])
            await admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(DATABASE)))
            await admin.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(DATABASE)))
            restored_admin = database_config(fixture.config)
            restored_roles = (database_config(roles.reader), database_config(roles.writer))
            await assert_quarantine(admin, restored_roles, restored_admin)
            try:
                verify_backup(archive, '0' * 64)
            except ValueError:
                pass
            else:
                require(False)
            await assert_quarantine(admin, restored_roles, restored_admin)
            PHASE = 'restore'
            verify_backup(archive, digest)
            cli(args.prepared_postgres_bin/'pg_restore', restored_admin,
                ['--no-owner', '--single-transaction', '--exit-on-error', '--dbname', DATABASE, str(archive)])
            async with await connect(restored_admin, autocommit=True) as recovered:
                require(await authority(recovered) == old_authority)
                require(await immutable_snapshot(recovered) == baseline)
                PHASE = 'refusal_gates'
                refused = 0
                for invalid in (None, current[:-1]):
                    try:
                        await reconcile(recovered, invalid, current_digest)
                    except ValueError:
                        refused += 1
                    else:
                        require(False)
                    await assert_quarantine(recovered, restored_roles)
                    require(await authority(recovered) == old_authority)
                require(refused == 2)
                PHASE = 'reconcile'
                await reconcile(recovered, current, current_digest)
                require(await immutable_snapshot(recovered) == baseline)
                await recovered.execute(migration_script(migrations(ROOT/'storage/postgres/migrations'), apply=False))
                await assert_quarantine(recovered, restored_roles)
                PHASE = 'release'
                await recovered.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(DATABASE),
                    sql.Identifier(roles.reader['user']), sql.Identifier(roles.writer['user'])))
                for role in (roles.reader, roles.writer):
                    await recovered.execute(sql.SQL('ALTER ROLE {} LOGIN').format(sql.Identifier(role['user'])))
                PHASE = 'python_sources'
                tokenizer = args.sdk_root.resolve().parents[1]/'artifacts/tokenizers/cl100k_base.tiktoken'
                python = await python_sources(restored_roles[0], tokenizer, receipts['allowed'])
                PHASE = 'node_sources'
                script = "import{pathToFileURL}from'node:url';const{runSourceChecks}=await import(pathToFileURL(process.argv[1]));let data='';for await(const p of process.stdin){data+=p;if(data.length>32768)throw Error('input_limit');}try{console.log(JSON.stringify(await runSourceChecks(JSON.parse(data))));}catch{process.exitCode=1;}"
                node = await child(['node', '--input-type=module', '-e', script, str(ROOT/'tools/recovery_source_checks.mjs')],
                    dict(reader_config=restored_roles[0], sdk_root=str(args.sdk_root.resolve()),
                        tokenizer_path=str(tokenizer), expected=receipts['allowed']), timeout=60)
                require(node['checks'] == python['checks'] and node['provider_http_calls'] == 0)
                require(await authority(recovered) == current and await immutable_snapshot(recovered) == baseline)
                require(await rows(recovered, 'SELECT count(*) FROM pg_stat_activity WHERE usename=ANY(%s)',
                    ([role['user'] for role in restored_roles],)) == [(0,)])
            address = fixture.config['host'], fixture.config['port']
        pressure_guard(pressures)
    PHASE = 'cleanup'
    try:
        connection = socket.create_connection(address, timeout=.2)
    except ConnectionRefusedError:
        pass
    else:
        connection.close()
        require(False)
    result = dict(revision='MRR-r1', state='passed', evidence_kind='local_disposable_backup_recovery',
        backup_sha256=digest, backup_bytes=archive.stat().st_size, authority_sha256=current_digest,
        restored_documents=len(current), immutable_snapshot=baseline, checks=dict(
            runtime_quarantine=True, backup_hash_refused=True,
            missing_authority_refused=True, incomplete_authority_refused=True,
            restore_acl_policies_preserved=True, current_authority_reconciled=True,
            immutable_content_profiles_history_preserved=True, runtime_guards_passed=True,
            revoked_access_not_restored=True, cleanup_verified=True),
        python=python, node=node, pressure=pressures, provider_http_calls=0,
        limitations=['Same-cluster synthetic restore with existing global roles only.',
                    'Requires a separately trusted complete current authority snapshot; no production PITR claim.'])
    save(args.output/'results.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sdk-root', 'prepared-postgres-bin', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--allow-local-processes', required=True, action='store_true')
    parser.add_argument('--quarantine-probe', action='store_true')
    try:
        args = parser.parse_args(argv)
        result = asyncio.run(quarantine_probe(args) if args.quarantine_probe else run(args))
        print(json.dumps(dict(revision=result['revision'], state=result['state'])))
        return 0
    except Exception:
        print(json.dumps(dict(revision='MRR-r1', state='failed', phase=PHASE, code='backup_recovery_invalid')))
        return 1


if __name__ == '__main__':
    # Isolated interpreter: explicitly add only tools, never checkout package source.
    sys.path.insert(0, str(ROOT/'tools'))
    raise SystemExit(main())
