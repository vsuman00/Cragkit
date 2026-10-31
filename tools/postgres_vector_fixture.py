"""Opt-in isolated PG17/pgvector0.8.0 prerequisite; no download or global install."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

from qdrant_source_native import PostgresSourceFixture

ROOT = Path(__file__).resolve().parents[1]
VECTOR_COMMIT = '2627c5ff775ae6d7aef0c430121ccf857842d2f2'


def _output(arguments: list[str]) -> str:
    try:
        result = subprocess.run(arguments, check=True, capture_output=True, timeout=10,
                                env=PostgresSourceFixture._environment())
        return result.stdout.decode().strip()
    except Exception:
        raise RuntimeError('v6_postgres_binary_inspection') from None


def _confined(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise RuntimeError('v6_postgres_relocation_escape')
    return resolved


def prepare_private_postgres(postgres_bin: Path, vector_source: Path, destination: Path) -> Path:
    """Copy approved built source outputs and PG files; never build/install/download.

    Caller must build the pinned source with its explicit serialized resource slot.
    Preserve PostgreSQL's compiled relative executable/share/library layout.
    Refuse reuse rather than mixing files from separate candidate preparations.
    """
    source = vector_source.resolve(strict=True)
    if _output(['git', '-C', str(source), 'rev-parse', 'HEAD']) != VECTOR_COMMIT:
        raise RuntimeError('v6_pgvector_source_revision')
    control = (source / 'vector.control').read_text()
    if "default_version = '0.8.0'" not in control:
        raise RuntimeError('v6_pgvector_control_version')
    built = [source/name for name in ('vector.so','vector.dylib') if (source/name).is_file()]
    if len(built) != 1:
        raise RuntimeError('v6_pgvector_build_missing')
    binary = built[0]
    script = source / 'sql/vector--0.8.0.sql'
    if not binary.is_file() or not script.is_file():
        raise RuntimeError('v6_pgvector_build_missing')
    pg_config = postgres_bin.resolve(strict=True) / 'pg_config'
    if _output([str(pg_config), '--version']) not in ('PostgreSQL 17.11', 'PostgreSQL 17.11 (Homebrew)'):
        raise RuntimeError('v6_postgres_version')
    paths = {name: Path(_output([str(pg_config), '--' + name]))
             for name in ('bindir', 'sharedir', 'pkglibdir')}
    common = Path(os.path.commonpath([str(path) for path in paths.values()]))
    if common == Path('/') or not all(path.is_absolute() for path in paths.values()):
        raise RuntimeError('v6_postgres_layout_unsupported')
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    root = destination.resolve(strict=True)
    private = {name: root / path.relative_to(common) for name, path in paths.items()}
    try:
        for name in ('bindir', 'sharedir', 'pkglibdir'):
            shutil.copytree(paths[name], private[name], symlinks=False)
        for pattern in ('vector*.control', 'vector--*.sql'):
            for old in (private['sharedir'] / 'extension').glob(pattern):
                old.unlink()
        for old in (private['pkglibdir']/name for name in ('vector.so','vector.dylib')):
            if old.exists():
                old.unlink()
        shutil.copy2(binary, private['pkglibdir'] / binary.name)
        shutil.copy2(source / 'vector.control', private['sharedir'] / 'extension/vector.control')
        shutil.copy2(script, private['sharedir'] / 'extension/vector--0.8.0.sql')
        copied_config = private['bindir'] / 'pg_config'
        for name in ('bindir', 'sharedir', 'pkglibdir'):
            observed = Path(_output([str(copied_config), '--' + name]))
            if _confined(observed, root) != private[name].resolve(strict=True):
                raise RuntimeError('v6_postgres_relocation_mismatch')
        manifest = dict(source_commit=VECTOR_COMMIT, postgres_version='17.11', vector_version='0.8.0',
                        binary_sha256=sha256(binary.read_bytes()).hexdigest(), binary_name=binary.name,
                        control_sha256=sha256((source/'vector.control').read_bytes()).hexdigest(),
                        sql_sha256=sha256(script.read_bytes()).hexdigest(),
                        paths={name:str(path.relative_to(root)) for name,path in private.items()})
        (root / 'preparation.json').write_text(json.dumps(manifest, indent=2)+'\n')
        return private['bindir']
    except BaseException:
        # This destination was created above; no process has started from it.
        shutil.rmtree(root)
        raise


@dataclass(frozen=True, repr=False)
class RoleConfigs:
    reader: dict
    writer: dict


class V6PostgresFixture:
    """Own disposable TLS/SCRAM database; prepared binary prefix remains reusable.

    The copied binary tree is an explicit caller-owned prerequisite, not deleted by
    this database fixture. No credentials survive successful fixture close.
    """
    def __init__(self, postgres_bin: Path, artifacts_dir: Path):
        preparation = postgres_bin.resolve(strict=True)
        # Require relocation proof before any native server can be started.
        pg_config = preparation / 'pg_config'
        roots = [preparation, Path(_output([str(pg_config), '--sharedir'])),
                 Path(_output([str(pg_config), '--pkglibdir']))]
        common = Path(os.path.commonpath([str(p) for p in roots]))
        record = common / 'preparation.json'
        if not record.is_file():
            raise RuntimeError('v6_postgres_preparation_required')
        manifest = json.loads(record.read_text())
        if manifest.get('source_commit') != VECTOR_COMMIT or manifest.get('vector_version') != '0.8.0':
            raise RuntimeError('v6_postgres_preparation_identity')
        if manifest.get('binary_name') not in ('vector.so','vector.dylib'):
            raise RuntimeError('v6_pgvector_binary_identity')
        library = _confined(roots[2] / manifest['binary_name'], common)
        if sha256(library.read_bytes()).hexdigest() != manifest.get('binary_sha256'):
            raise RuntimeError('v6_pgvector_binary_drift')
        for file, field in (('vector.control','control_sha256'),('vector--0.8.0.sql','sql_sha256')):
            path = _confined(roots[1] / 'extension' / file, common)
            if sha256(path.read_bytes()).hexdigest() != manifest.get(field):
                raise RuntimeError('v6_pgvector_metadata_drift')
        for name, path in zip(('bindir','sharedir','pkglibdir'),roots):
            if _confined(path,common) != _confined(common/manifest['paths'][name],common):
                raise RuntimeError('v6_postgres_preparation_paths')
        self._server = PostgresSourceFixture(preparation, artifacts_dir, max_connections=6)
        self._roles: RoleConfigs | None = None
        self.checks: list[str] = []

    def __repr__(self):
        return 'V6PostgresFixture()'

    def __enter__(self):
        self._server.__enter__()
        return self

    @property
    def config(self):
        return self._server.config

    async def provision(self, *, tenants: tuple[str, ...], collections: tuple[str, ...],
                        enable_openai_profile: bool = False) -> RoleConfigs:
        """Apply unchanged setup and scope-bounded policies; expose distinct logins.

        The default preserves legacy fake-only storage. Opting into the PGO-r1
        upgrade provisions a separate empty table; it performs no inference.
        """
        import psycopg
        from psycopg import sql
        from cragkit._postgres_pool import PoolConfig, PoolResource
        from cragkit._postgres_session import PostgresSession
        from cragkit.ingestion import _WRITER_ROLE_SQL
        from cragkit.vector_ingestion import _VECTOR_CAPABILITY_SQL
        from check_postgres import migrations, migration_script, vector_setup_script, vector_storage_script
        if (self._roles is not None or not tenants or not collections
                or type(enable_openai_profile) is not bool):
            raise RuntimeError('v6_postgres_provision_state')
        config = self.config
        async with await psycopg.AsyncConnection.connect(
            **{k:v for k,v in config.items() if k!='max_size'}, sslmode='verify-full',
            autocommit=True, connect_timeout=5,
            options='-c statement_timeout=30000 -c lock_timeout=2000') as admin:
            if admin.pgconn.ssl_in_use is not True:
                raise RuntimeError('v6_postgres_tls_required')
            await admin.execute(migration_script(migrations(ROOT/'storage/postgres/migrations'), apply=True))
            # Existing deployment hardening enables ledger RLS required by native role guards.
            await admin.execute((ROOT/'storage/postgres/deployment/neon.sql').read_text())
            setup = migrations(ROOT/'storage/postgres/setup')
            await admin.execute(vector_setup_script(setup[0], apply=True))
            await admin.execute(vector_storage_script(setup[1], apply=True))
            if enable_openai_profile:
                from check_postgres_profiles import profile_upgrade_script
                await admin.execute(profile_upgrade_script(apply=True))
                self.checks.append('explicit_openai_profile_upgrade')
            version = await (await admin.execute("SELECT extversion FROM pg_extension WHERE extname='vector'" )).fetchall()
            if version != [('0.8.0',)]:
                raise RuntimeError('v6_pgvector_native_version')
            binding = await (await admin.execute("SELECT DISTINCT probin FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='cragkit_vector' AND p.probin IS NOT NULL")).fetchall()
            if binding != [('$libdir/vector',)]:
                raise RuntimeError('v6_pgvector_native_binding')
            if await (await admin.execute("SELECT cragkit_vector.vector_dims('[1,0]'::cragkit_vector.vector)")).fetchall() != [(2,)]:
                raise RuntimeError('v6_pgvector_native_execution')
            self.checks.append('genuine_pgvector_0_8_0_native_binding')
            configs = []
            for kind in ('reader', 'writer'):
                role = 'v6_' + kind + '_' + secrets.token_hex(6)
                password = secrets.token_hex(32)
                encrypted = admin.pgconn.encrypt_password(password.encode(), role.encode(), b'scram-sha-256').decode()
                await admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS CONNECTION LIMIT 1 PASSWORD {}').format(sql.Identifier(role),sql.Literal(encrypted)))
                await admin.execute(sql.SQL('GRANT USAGE ON SCHEMA cragkit,cragkit_vector TO {}').format(sql.Identifier(role)))
                await admin.execute(sql.SQL('GRANT USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,cragkit.sha256_hex,cragkit.safe_count TO {}').format(sql.Identifier(role)))
                tables = ('collections','documents','document_revisions','index_generations','chunks','chunk_lexical','document_grants','ingestion_jobs','migration_history','embedding_profiles','chunk_vectors_fake_1536')
                if enable_openai_profile:
                    tables += ('chunk_vectors_openai_te3small_1536',)
                for table in tables:
                    readonly = kind=='reader' or table in ('migration_history','embedding_profiles')
                    permissions = 'SELECT' if readonly else 'SELECT,INSERT,UPDATE'
                    await admin.execute(sql.SQL('GRANT '+permissions+' ON cragkit.{} TO {}').format(sql.Identifier(table),sql.Identifier(role)))
                    predicate = sql.SQL('true') if table in ('migration_history','embedding_profiles') else sql.SQL("tenant_id=current_setting('cragkit.tenant_id',true) AND tenant_id=ANY({}) AND collection_id=ANY({})").format(sql.Literal(list(tenants)),sql.Literal(list(collections)))
                    policy = sql.SQL('CREATE POLICY {} ON cragkit.{} FOR '+('SELECT' if readonly else 'ALL')+' TO {} USING ({})'+('' if readonly else ' WITH CHECK ({})'))
                    args=[sql.Identifier(role),sql.Identifier(table),sql.Identifier(role),predicate]
                    if not readonly:args.append(predicate)
                    await admin.execute(policy.format(*args))
                await admin.execute(sql.SQL('GRANT USAGE ON TYPE cragkit_vector.vector TO {}').format(sql.Identifier(role)))
                for signature in ('vector(cragkit_vector.vector,integer,boolean)',
                                  'vector_dims(cragkit_vector.vector)','vector_norm(cragkit_vector.vector)',
                                  'cosine_distance(cragkit_vector.vector,cragkit_vector.vector)'):
                    await admin.execute(sql.SQL('GRANT EXECUTE ON FUNCTION cragkit_vector.'+signature+' TO {}').format(sql.Identifier(role)))
                await admin.execute(sql.SQL('GRANT SELECT ON cragkit_vector.setup_history TO {}').format(sql.Identifier(role)))
                await admin.execute(sql.SQL('CREATE POLICY {} ON cragkit_vector.setup_history FOR SELECT TO {} USING(true)').format(sql.Identifier(role),sql.Identifier(role)))
                configs.append(self._server.reader_config(role,password))
            # Validate actual least-privilege reader and writer logins, never the admin.
            for kind, raw in zip(('reader','writer'),configs):
                typed = PoolConfig(**{**raw,'sslrootcert':Path(raw['sslrootcert']),'passfile':Path(raw['passfile'])})
                resource=PoolResource(typed)
                await resource.open()
                try:
                    deadline=asyncio.get_running_loop().time()+10
                    if kind=='reader':
                        await PostgresSession(resource).validate(deadline=deadline)
                    else:
                        async with resource.lease(deadline=deadline) as connection:
                            async with connection.transaction():
                                if await (await connection.execute(_WRITER_ROLE_SQL)).fetchall() != [(True,)]:
                                    raise RuntimeError('v6_postgres_writer_guard')
                    async with resource.lease(deadline=deadline) as connection:
                        async with connection.transaction():
                            if await (await connection.execute(_VECTOR_CAPABILITY_SQL)).fetchall() != [(True,)]:
                                raise RuntimeError('v6_postgres_vector_guard')
                            native = await (await connection.execute("SELECT "
                                "cragkit_vector.vector_dims('[1]'::cragkit_vector.vector(1)),"
                                "cragkit_vector.vector_norm('[1]'::cragkit_vector.vector(1)),"
                                "cragkit_vector.cosine_distance('[1]'::cragkit_vector.vector(1),"
                                "'[1]'::cragkit_vector.vector(1))")).fetchall()
                            if native != [(1, 1.0, 0.0)]:
                                raise RuntimeError('v6_postgres_vector_runtime_functions')
                            if enable_openai_profile:
                                from cragkit._postgres_profiles import validate_profile_storage
                                from cragkit.embeddings import FAKE_PROFILE, OPENAI_PROFILE
                                async def query(statement):
                                    return await (await connection.execute(statement)).fetchall()
                                for profile in (FAKE_PROFILE, OPENAI_PROFILE):
                                    await validate_profile_storage(query, profile, _VECTOR_CAPABILITY_SQL)
                finally:
                    await resource.close()
            self._roles=RoleConfigs(*configs)
            self.checks.append('distinct_restricted_native_role_guards')
            self.checks.append('restricted_vector_cast_norm_and_distance')
            return self._roles

    def close(self):
        self._server.close()
        self._roles=None

    def __exit__(self, exc_type, primary, traceback):
        self._server.__exit__(exc_type,primary,traceback)
        self._roles=None
