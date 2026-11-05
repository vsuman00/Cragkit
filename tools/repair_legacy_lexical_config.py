"""LCR-r1 explicit, bounded operator repair for the supported legacy lexical alias.

Exit status: 0 repaired/canonical, 2 repair required by --check, 1 failed.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_postgres import LOCK, migrations
from check_postgres_profiles import CATALOG_SHA256, SETUP_IDENTITIES, _registry_guard, _table_guard
from cragkit._postgres_session import EXPECTED_HISTORY, _CATALOG_SQL, _TABLE_COLUMNS
from operator_support import regular_bytes as _regular_bytes

ARTIFACT = ROOT/'storage/postgres/maintenance/0001_lexical_config.sql'
ARTIFACT_SHA256 = '78d3b4c322e1e79c6e8ac012876308abba1724466b61548bad36904478da536c'
MAX_ROWS = 1000
MAX_BYTES = 8 * 1024 * 1024
KEYS = {
    'collections': ('tenant_id','collection_id'),
    'documents': ('tenant_id','collection_id','document_id'),
    'document_revisions': ('tenant_id','collection_id','document_id','revision_id'),
    'index_generations': ('tenant_id','collection_id','document_id','generation_id'),
    'chunks': ('tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id'),
    'chunk_lexical': ('tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id'),
    'document_grants': ('tenant_id','collection_id','document_id','grant_id'),
    'ingestion_jobs': ('tenant_id','collection_id','intent_id'),
    'migration_history': ('version',), 'embedding_profiles': ('profile_id',),
}
LEXICAL_KEYS = KEYS['chunk_lexical']
TRIGGERS = {
    'chunk_lexical': [('canonical_lexical_vector','refresh_lexical_vector',23)],
    'chunks': [('canonical_chunk_span','validate_chunk_span',23),
        ('changed_chunk_lexical_vector','refresh_chunk_lexical',17)],
}


class RepairError(ValueError):
    """Fixed code only; never retain database diagnostics in a report."""


def require(condition, code='lexical_repair_invalid'):
    if not condition:
        raise RepairError(code)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def target_fingerprint(connection,*,expected_database,expected_owner):
    """Read only validated noncredential connection scalars, never a DSN or password."""
    host,port=connection.info.host,connection.info.port
    require(type(host) is str and 0<len(host.encode())<=1024
        and type(port) is int and 1<=port<=65535
        and type(expected_database) is str and type(expected_owner) is str,
        'lexical_repair_target_invalid')
    return sha256(canonical(dict(host=host,port=port,database=expected_database,
        owner=expected_owner))).hexdigest()


def artifacts():
    raw = _regular_bytes(ARTIFACT,131072)
    require(sha256(raw).hexdigest()==ARTIFACT_SHA256,'lexical_repair_artifact_drift')
    lexical = migrations(ROOT/'storage/postgres/migrations')
    setup = migrations(ROOT/'storage/postgres/setup')
    require(tuple((m.version,m.checksum) for m in lexical)==EXPECTED_HISTORY
        and tuple((m.version,m.checksum) for m in setup)==SETUP_IDENTITIES,'lexical_repair_artifact_drift')
    catalog = _regular_bytes(ROOT/'contracts/fixtures/postgres_openai_catalog_v6.json',131072)
    require(sha256(catalog).hexdigest()==CATALOG_SHA256,'lexical_repair_artifact_drift')
    functions = {}
    for item in lexical:
        for match in re.finditer(r'CREATE (?:OR REPLACE )?FUNCTION cragkit\.([a-z_]+)\(\) RETURNS trigger\s+LANGUAGE plpgsql SET search_path = pg_catalog AS \$function\$(.*?)\$function\$;',item.sql,re.S):
            functions[match[1]]=match[2]
    require(all(name in functions for values in TRIGGERS.values() for _,name,_ in values),
        'lexical_repair_artifact_drift')
    return raw.decode(),json.loads(catalog),functions


async def fetch(connection,statement,parameters=None):
    return await (await connection.execute(statement,parameters)).fetchall()


async def lock_and_validate(connection,*,expected_database,expected_owner,catalog,functions):
    target = await fetch(connection,'SELECT current_database(),current_user,session_user')
    require(target==[(expected_database,expected_owner,expected_owner)]
        and connection.pgconn.ssl_in_use is True,'lexical_repair_target_invalid')
    await connection.execute("SET LOCAL search_path=pg_catalog; SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='1s'; SET LOCAL idle_in_transaction_session_timeout='15s'")
    await connection.execute('SELECT '+LOCK)
    optional=await fetch(connection,"SELECT to_regnamespace('cragkit_vector') IS NOT NULL,to_regclass('cragkit_vector.setup_history') IS NOT NULL,to_regclass('cragkit.embedding_profiles') IS NOT NULL")
    setup=()
    if optional!=[(False,False,False)]:
        require(optional[0][:2]==(True,True),'lexical_repair_optional_storage_unmanaged')
        setup=tuple(await fetch(connection,'SELECT version,checksum FROM cragkit_vector.setup_history ORDER BY version'))
        require(setup!=SETUP_IDENTITIES[:1],'lexical_repair_setup_only_unsupported')
        require(setup in (SETUP_IDENTITIES[:2],SETUP_IDENTITIES) and optional[0][2],
            'lexical_repair_history_invalid')
    tables = ['cragkit.'+name for name in KEYS if name!='embedding_profiles']
    if setup:
        tables += ['cragkit.embedding_profiles','cragkit.chunk_vectors_fake_1536','cragkit_vector.setup_history']
    if len(setup)==3:
        tables.append('cragkit.chunk_vectors_openai_te3small_1536')
    tables.sort()
    await connection.execute('LOCK TABLE '+','.join(tables)+' IN SHARE ROW EXCLUSIVE MODE')
    declared=await fetch(connection,"SELECT n.nspname||'.'||c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('cragkit','cragkit_vector') AND c.relkind IN ('r','p') ORDER BY 1")
    require(declared==[(name,) for name in tables],'lexical_repair_catalog_invalid')
    require(tuple(await fetch(connection,'SELECT version,checksum FROM cragkit.migration_history ORDER BY version'))==EXPECTED_HISTORY,
        'lexical_repair_history_invalid')
    if setup:
        require(tuple(await fetch(connection,'SELECT version,checksum FROM cragkit_vector.setup_history ORDER BY version'))==setup,
            'lexical_repair_history_invalid')
    require(await fetch(connection,_CATALOG_SQL)==[(True,)],'lexical_repair_catalog_invalid')
    owners = await fetch(connection,"SELECT nspname,pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname IN ('cragkit','cragkit_vector') ORDER BY nspname")
    require(owners==[('cragkit',expected_owner)]+([('cragkit_vector',expected_owner)] if setup else []),
        'lexical_repair_owner_invalid')
    for table in tables:
        info = await fetch(connection,"SELECT relkind,relrowsecurity,relforcerowsecurity,pg_get_userbyid(relowner) FROM pg_class WHERE oid=to_regclass(%s)",(table,))
        require(info==[('r',True,False,expected_owner)],'lexical_repair_catalog_invalid')
        public=await fetch(connection,"SELECT count(*) FROM pg_class c,LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a WHERE c.oid=to_regclass(%s) AND a.grantee=0",(table,))
        require(public==[(0,)],'lexical_repair_catalog_invalid')
    for table,definition in _TABLE_COLUMNS.items():
        columns=await fetch(connection,"SELECT attname FROM pg_attribute WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped ORDER BY attnum",('cragkit.'+table,))
        require(columns==[(entry.split(':')[0],) for entry in definition.split()],'lexical_repair_catalog_invalid')
    defaults=await fetch(connection,"SELECT a.attname,a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid='cragkit.chunk_lexical'::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum")
    expected_defaults={'language_config':"'pg_catalog.simple'::text",'identifier_tokens':'ARRAY[]::cragkit.identity_text[]'}
    require(all(notnull and identity=='' and generated=='' and default==expected_defaults.get(name)
        for name,notnull,identity,generated,default in defaults),'lexical_repair_catalog_invalid')
    if setup:
        require(await fetch(connection,"SELECT e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'")==[('0.8.0','cragkit_vector')],
            'lexical_repair_catalog_invalid')
        for table,columns,constraints in (
            ('chunk_vectors_fake_1536',catalog['fake_columns'],catalog['fake_constraints']),
            *((('chunk_vectors_openai_te3small_1536',catalog['columns'],catalog['constraints']),) if len(setup)==3 else ())):
            require(await fetch(connection,'SELECT '+_table_guard(table,columns,constraints))==[(True,)],'lexical_repair_catalog_invalid')
        require(await fetch(connection,'SELECT '+_registry_guard(catalog,upgraded=len(setup)==3))==[(True,)],'lexical_repair_catalog_invalid')
    await validate_triggers(connection,functions,expected_owner)
    return tables


async def validate_triggers(connection,functions,owner):
    for table,expected in TRIGGERS.items():
        rows=await fetch(connection,"SELECT t.tgname,p.proname,t.tgtype,t.tgenabled,t.tgnargs,t.tgattr::text,t.tgqual IS NULL,t.tgoldtable,t.tgnewtable,p.prosecdef,p.provolatile,l.lanname,p.proconfig,p.prosrc,pg_get_userbyid(p.proowner),t.tgfoid=to_regprocedure('cragkit.'||p.proname||'()'),p.proisstrict,p.proleakproof,p.proparallel,p.prokind,p.proretset,p.prorettype='trigger'::regtype,p.pronargs,p.proallargtypes,p.proargmodes,p.proargnames,p.procost,p.prorows,p.prosupport=0 FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_language l ON l.oid=p.prolang WHERE t.tgrelid=to_regclass(%s) AND NOT t.tgisinternal ORDER BY t.tgname",('cragkit.'+table,))
        require(len(rows)==len(expected),'lexical_repair_trigger_invalid')
        for row,(name,function,kind) in zip(rows,sorted(expected),strict=True):
            attributes='11' if function=='refresh_chunk_lexical' else ''
            require(row==(name,function,kind,'O',0,attributes,True,None,None,False,'v','plpgsql',
                ['search_path=pg_catalog'],functions[function],owner,True,
                False,False,'u','f',False,True,0,None,None,None,100.0,0.0,True),
                'lexical_repair_trigger_invalid')
    invalid=await fetch(connection,"SELECT count(*) FROM pg_constraint c WHERE c.conrelid IN ('cragkit.chunk_lexical'::regclass,'cragkit.chunks'::regclass) AND (NOT c.convalidated OR (c.contype='f' AND ((SELECT count(*) FROM pg_trigger t WHERE t.tgconstraint=c.oid AND t.tgisinternal)<>4 OR EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgconstraint=c.oid AND (NOT t.tgisinternal OR t.tgenabled<>'O')))))")
    require(invalid==[(0,)],'lexical_repair_trigger_invalid')
    lexical_constraints=await fetch(connection,"""SELECT
      count(*)=4,
      count(*) FILTER (WHERE contype='p' AND conkey=ARRAY[1,2,3,4,5,6]::smallint[])=1,
      count(*) FILTER (WHERE contype='f' AND conkey=ARRAY[1,2,3,4,5,6]::smallint[]
        AND confrelid='cragkit.chunks'::regclass AND confkey=ARRAY[1,2,3,4,5,6]::smallint[]
        AND confupdtype='a' AND confdeltype='c' AND confmatchtype='s')=1,
      bool_and(convalidated AND NOT condeferrable AND NOT condeferred)
      FROM pg_constraint WHERE conrelid='cragkit.chunk_lexical'::regclass""")
    require(lexical_constraints==[(True,True,True,True)],'lexical_repair_catalog_invalid')
    expressions=await fetch(connection,"SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conrelid='cragkit.chunk_lexical'::regclass AND contype='c'")
    normalized={re.sub(r'[\s()]','',row[0]).lower() for row in expressions}
    require(normalized=={'array_positionidentifier_tokens,null::text::cragkit.identity_textisnull',
        'array_ndimsidentifier_tokensisnullorarray_ndimsidentifier_tokens=1'},'lexical_repair_catalog_invalid')


async def state_snapshot(connection,tables):
    state,total_rows,total_bytes={},0,0
    for table in tables:
        projection='to_jsonb(t)'
        if table=='cragkit.chunk_lexical':
            projection+="||jsonb_build_object('_mrr_vector_wire',encode(pg_catalog.tsvectorsend(t.search_vector),'hex'))"
        elif table.startswith('cragkit.chunk_vectors_'):
            projection+="||jsonb_build_object('_mrr_vector_wire',encode(cragkit_vector.vector_send(t.embedding),'hex'))"
        size=await fetch(connection,f'SELECT count(*),coalesce(sum(octet_length(({projection})::text)),0) FROM {table} t')
        total_rows+=size[0][0];total_bytes+=size[0][1]
        require(total_rows<=MAX_ROWS and total_bytes<=MAX_BYTES,'lexical_repair_bound_exceeded')
        rows=await fetch(connection,f'SELECT {projection} FROM {table} t ORDER BY to_jsonb(t)::text LIMIT {MAX_ROWS+1}')
        name=table.split('.')[1]
        keys=KEYS.get(name,LEXICAL_KEYS if name.startswith('chunk_vectors_') else ('version',))
        keyed={}
        for (row,) in rows:
            key=tuple(row[column] for column in keys)
            require(key not in keyed,'lexical_repair_ambiguous_key')
            keyed[key]=row
        state[table]=keyed
    # Bound catalog material before allocating the metadata snapshot in this process.
    catalog_rows=0
    for relation,join,predicate in (
        ('pg_class','JOIN pg_namespace n ON n.oid=t.relnamespace',"n.nspname IN ('cragkit','cragkit_vector')"),
        ('pg_policies','',"t.schemaname IN ('cragkit','cragkit_vector')"),
        ('pg_proc','JOIN pg_namespace n ON n.oid=t.pronamespace',"n.nspname IN ('cragkit','cragkit_vector')"),
        ('pg_constraint','JOIN pg_namespace n ON n.oid=t.connamespace',"n.nspname IN ('cragkit','cragkit_vector')"),
        ('pg_trigger','JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace',"n.nspname IN ('cragkit','cragkit_vector')")):
        size=await fetch(connection,f'SELECT count(*),coalesce(sum(octet_length(to_jsonb(t)::text)),0) FROM {relation} t {join} WHERE {predicate}')
        catalog_rows+=size[0][0];total_bytes+=size[0][1]
        require(total_rows+catalog_rows<=MAX_ROWS and total_bytes<=MAX_BYTES,'lexical_repair_bound_exceeded')
    # Capture current object ACLs, policies, triggers, constraints and function definitions.
    catalog=await fetch(connection,"SELECT jsonb_build_object('relations',(SELECT jsonb_agg(jsonb_build_array(n.nspname,c.relname,c.relkind,c.relowner,c.relrowsecurity,c.relforcerowsecurity,c.relacl) ORDER BY n.nspname,c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('cragkit','cragkit_vector') AND c.relkind IN ('r','p')),'policies',(SELECT jsonb_agg(to_jsonb(p) ORDER BY schemaname,tablename,policyname) FROM pg_policies p WHERE schemaname IN ('cragkit','cragkit_vector')),'functions',(SELECT jsonb_agg(to_jsonb(p) ORDER BY p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('cragkit','cragkit_vector')),'constraints',(SELECT jsonb_agg(jsonb_build_array(c.oid,pg_get_constraintdef(c.oid),c.convalidated,c.condeferrable,c.condeferred) ORDER BY c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname IN ('cragkit','cragkit_vector')),'triggers',(SELECT jsonb_agg(jsonb_build_array(t.oid,pg_get_triggerdef(t.oid),t.tgenabled,t.tgisinternal) ORDER BY t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('cragkit','cragkit_vector')))")
    metadata=catalog[0][0]
    require(total_bytes+len(canonical(metadata))<=MAX_BYTES,'lexical_repair_bound_exceeded')
    return state,metadata


def state_digest(snapshot):
    state,metadata=snapshot
    wire={table:sorted(rows.values(),key=lambda row:canonical(row)) for table,rows in state.items()}
    return sha256(canonical(dict(tables=wire,catalog=metadata))).hexdigest()


def verify_delta(before,after,*,apply):
    old,old_catalog=before;new,new_catalog=after
    require(old.keys()==new.keys() and old_catalog==new_catalog,'lexical_repair_state_changed')
    aliases=0
    for table,rows in old.items():
        require(rows.keys()==new[table].keys(),'lexical_repair_state_changed')
        for key,row in rows.items():
            expected=dict(row)
            if table=='cragkit.chunk_lexical' and row['language_config']=='simple':
                aliases+=1
                if apply:expected['language_config']='pg_catalog.simple'
            require(expected==new[table][key],'lexical_repair_state_changed')
    return aliases


async def validate_rows(connection):
    require(await fetch(connection,"SELECT 'simple'::regconfig='pg_catalog.simple'::regconfig")==[(True,)],'lexical_repair_alias_invalid')
    invalid=await fetch(connection,"SELECT count(*) FROM cragkit.chunk_lexical l LEFT JOIN cragkit.chunks c USING(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id) LEFT JOIN cragkit.index_generations g USING(tenant_id,collection_id,document_id,revision_id,generation_id) LEFT JOIN cragkit.document_revisions r USING(tenant_id,collection_id,document_id,revision_id) WHERE c.chunk_id IS NULL OR g.generation_id IS NULL OR r.revision_id IS NULL OR l.language_config NOT IN ('simple','pg_catalog.simple') OR g.lexical_profile<>'native_fts.v1' OR l.search_vector IS DISTINCT FROM to_tsvector('pg_catalog.simple'::regconfig,c.text) OR c.text_sha256<>encode(sha256(convert_to(c.text,'UTF8')),'hex') OR r.canonical_sha256<>encode(sha256(convert_to(r.canonical_text,'UTF8')),'hex') OR c.start_byte<0 OR c.end_byte<=c.start_byte OR substring(convert_to(r.canonical_text,'UTF8') FROM c.start_byte::integer+1 FOR (c.end_byte-c.start_byte)::integer)<>convert_to(c.text,'UTF8')")
    require(invalid==[(0,)],'lexical_repair_vector_invalid')
    require(await fetch(connection,"SELECT count(*) FROM cragkit.collections WHERE schema_version<>'0.1' OR active_profile<>'native_fts.v1'")==[(0,)],'lexical_repair_profile_invalid')


async def repair_in_transaction(connection,*,expected_database,expected_owner,apply=False):
    """Validate an already-open caller transaction; returned receipt is pending."""
    from psycopg.pq import TransactionStatus
    require(connection.info.transaction_status==TransactionStatus.INTRANS,'lexical_repair_transaction_required')
    require(type(apply) is bool,'lexical_repair_mode_invalid')
    sql,catalog,functions=artifacts()
    tables=await lock_and_validate(connection,expected_database=expected_database,
        expected_owner=expected_owner,catalog=catalog,functions=functions)
    target=target_fingerprint(connection,expected_database=expected_database,expected_owner=expected_owner)
    before=await state_snapshot(connection,tables)
    await validate_rows(connection)
    required=sum(row['language_config']=='simple' for row in before[0]['cragkit.chunk_lexical'].values())
    changed=0
    if apply and required:
        changed=(await connection.execute(sql)).rowcount
        require(changed==required,'lexical_repair_update_count_invalid')
    await validate_rows(connection)
    after=await state_snapshot(connection,tables)
    require(verify_delta(before,after,apply=apply)==required,'lexical_repair_state_changed')
    return dict(revision='LCR-r1',state='repaired' if apply and required else 'repair_required'
        if required else 'already_canonical',commit_state='pending',required_rows=required,
        changed_rows=changed,artifact_sha256=ARTIFACT_SHA256,target_sha256=target,
        before_sha256=state_digest(before),after_sha256=state_digest(after))


async def repair(connection,*,expected_database,expected_owner,apply=False):
    """Own the commit boundary; a committed receipt is issued only after success."""
    from psycopg.pq import TransactionStatus
    require(connection.info.transaction_status==TransactionStatus.IDLE,'lexical_repair_idle_required')
    async with asyncio.timeout(20):
        async with connection.transaction():
            result=await repair_in_transaction(connection,expected_database=expected_database,
                expected_owner=expected_owner,apply=apply)
    return {**result,'commit_state':'committed'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--expected-database',required=True)
    parser.add_argument('--expected-owner',required=True)
    parser.add_argument('--confirm-dedicated-target',action='store_true',required=True)
    async def execute(args):
        from operator_support import load_config, connect
        _regular_bytes(args.config,131072)
        async with await connect(load_config(args.config)) as connection:
            return await repair(connection,expected_database=args.expected_database,
                expected_owner=args.expected_owner,apply=args.apply)
    try:
        result=asyncio.run(execute(parser.parse_args(argv)))
        print(json.dumps(result,sort_keys=True))
        return 2 if result['state']=='repair_required' else 0
    except Exception as error:
        print(json.dumps(dict(revision='LCR-r1',state='failed',
            code=str(error) if type(error) is RepairError else 'lexical_repair_failed')))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
