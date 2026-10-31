"""Synthetic common data for isolated native backend/transport conformance."""
from copy import deepcopy
from hashlib import sha256
import secrets

from qdrant_writer_cases import writer_input,successor_stage
from qdrant_supervisor_cases import supervisor_input


def conformance_input():
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    from cragkit._qdrant_vectors import encode_dense
    inputs=writer_input();base=inputs['stage'];manifest=base['manifest']
    member=manifest['members'][0];member.update(start_byte=0,end_byte=len(base['canonical_text'].encode()),
        text_sha256=sha256(base['canonical_text'].encode()).hexdigest())
    manifest['members']=[member];base['dense_vectors']=base['dense_vectors'][:1];base['sparse_vectors']=base['sparse_vectors'][:1]
    base['intent']['manifest_sha256']=encode_manifest(manifest,base['canonical_text']).sha256
    pending=successor_stage({'stage':base},'conformance-pending',manifest['generation_id'])
    original=deepcopy(pending['manifest']['members'][0])
    pending['manifest']['members']=[dict(original,chunk_id='chunk-pending-'+str(index)) for index in range(1,10)]
    vector=[0.,1.]+[0.]*1534
    pending['dense_vectors']=[vector.copy() for _ in range(9)]
    pending['sparse_vectors']*=9
    foreign=deepcopy(base)
    foreign['manifest'].update(tenant_id='tenant-conformance-foreign',document_id='doc-foreign',revision_id='rev-foreign',generation_id='gen-foreign')
    foreign['intent'].update(tenant_id='tenant-conformance-foreign',document_id='doc-foreign',intent_id='intent-conformance-foreign')
    for stage in (pending,foreign):
        m=stage['manifest']
        for index,item in enumerate(m['members']):
            item['point_id']=point_id(['cragkit.qdrant.point.v1',*[m[key] for key in ('backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id')],item['chunk_id'],m['dense_profile']['profile_id'],m['sparse_profile']['profile_id']])
            item['dense_input_sha256']=encode_dense(stage['dense_vectors'][index],m['dense_profile']).input_sha256
        stage['intent']['manifest_sha256']=encode_manifest(m,stage['canonical_text']).sha256
    return dict(config=inputs['config'],scope=inputs['scope'],instance_id=inputs['instance_id'],
        collection_config=supervisor_input()['collection_config'],base=base,pending=pending,foreign=foreign)


def point(stage,index,authorization):
    m=stage['manifest'];member=m['members'][index]
    payload={key:m[key] for key in ('backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id','source_sha256','dense_profile','sparse_profile')}
    payload.update({key:member[key] for key in ('chunk_id','start_byte','end_byte','text_sha256')})
    payload.update(dense_profile_id=m['dense_profile']['profile_id'],sparse_profile_id=m['sparse_profile']['profile_id'],
        authorization_revision=authorization['authorization_revision'],principal_ids=authorization['principal_ids'],grant_ids=authorization['grant_ids'])
    payload.update({key:authorization[key] for key in ('language','kind','tag') if authorization.get(key) is not None})
    return dict(id=member['point_id'],payload=payload,vector=dict(dense=stage['dense_vectors'][index],sparse=stage['sparse_vectors'][index]))


def cases(inputs):
    base=inputs['base'];m=base['manifest'];query='café'
    anchor=dict(claim_id='source-fact',collection=m['collection'],document_id=m['document_id'],revision_id=m['revision_id'],
        source_sha256=m['source_sha256'],start_byte=0,end_byte=len(base['canonical_text'].encode()),text=base['canonical_text'])
    supported=dict(facet_id='fact',question='What does the source say?',required=True,absence='missing',anchors=[anchor])
    missing=dict(facet_id='missing',question='Unstated detail?',required=True,absence='missing',anchors=[])
    rows=[]
    for name,status,facets,doc,text,providers in [
        ('unknown','partial',None,m['document_id'],query,1),
        ('sufficient','sufficient',[supported],m['document_id'],query,1),
        ('partial','partial',[supported,missing],m['document_id'],query,1),
        ('no_match','insufficient',None,'doc-absent',query,1),
        ('foreign_document','insufficient',None,'doc-foreign',query,1),
        ('partial_generation','insufficient',None,m['document_id'],'pending',1),
        ('provider_budget','partial',None,m['document_id'],query,0),
    ]:
        template=dict(collection=m['collection'],required_filters=[dict(op='eq',field='document_id',value=doc)],
            limits=dict(deadline_ms=30000,max_candidates=1,max_attempts=1,max_provider_calls=providers,max_context_tokens=2000),
            output_profile=dict(renderer='cragkit.context.v2',counting_mode='estimated',envelope_reserve_tokens=128))
        policy=None if facets is None else dict(policy_id='conformance-reviewed',version='1',query_sha256=sha256(text.encode()).hexdigest(),facets=facets)
        rows.append(dict(id=name,query=text,template=template,policy=policy,expected_status=status))
    return rows


async def install_core(database,inputs):
    """Bootstrap only the fresh disposable fixture, before runtime clients."""
    from psycopg import sql
    from check_postgres import migrations,migration_script,ROOT
    admin=database.admin
    await admin.execute(migration_script(migrations(ROOT/'storage/postgres/migrations'),apply=True),prepare=False)
    await admin.execute((ROOT/'storage/postgres/deployment/neon.sql').read_text(),prepare=False)
    role='v5_conformance_reader';password=secrets.token_hex(32)
    tables=('collections','documents','document_revisions','index_generations','chunks','chunk_lexical','document_grants','ingestion_jobs','migration_history')
    async with admin.transaction():
        await admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT CONNECTION LIMIT 1').format(sql.Identifier(role),sql.Literal(password)))
        await admin.execute(sql.SQL('GRANT USAGE ON SCHEMA cragkit TO {}').format(sql.Identifier(role)))
        await admin.execute(sql.SQL('GRANT USAGE ON DOMAIN cragkit.identity_text,cragkit.collection_text,cragkit.sha256_hex,cragkit.safe_count TO {}').format(sql.Identifier(role)))
        for table in tables:
            await admin.execute(sql.SQL('GRANT SELECT ON cragkit.{} TO {}').format(sql.Identifier(table),sql.Identifier(role)))
            predicate=sql.SQL('true') if table=='migration_history' else sql.SQL("tenant_id=current_setting('cragkit.tenant_id',true)")
            await admin.execute(sql.SQL('CREATE POLICY v5_conformance_read ON cragkit.{} FOR SELECT TO {} USING({})').format(sql.Identifier(table),sql.Identifier(role),predicate))
        for name in ('base','foreign','pending'):
            stage=inputs[name];m=stage['manifest'];auth=inputs['base']['intent']['initial_authorization']
            key=(m['tenant_id'],m['collection'],m['document_id']);source=stage['canonical_text']
            await admin.execute('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',key[:2])
            await admin.execute('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(*key,auth['authorization_revision']))
            await admin.execute('INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(*key,m['revision_id'],m['source_sha256'],m['source_locator'],source,m['source_sha256'],m['parser_id']))
            await admin.execute('INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,expected_chunk_count,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(*key,m['revision_id'],m['generation_id'],m['chunker_profile'],'native_fts.v1',len(m['members']),'staging' if name=='pending' else 'ready'))
            for ordinal,member in enumerate(m['members'][:1]):
                chunkkey=(*key,m['revision_id'],m['generation_id'],member['chunk_id'])
                excerpt=source.encode()[member['start_byte']:member['end_byte']].decode()
                await admin.execute('INSERT INTO cragkit.chunks(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(*chunkkey,ordinal,member['start_byte'],member['end_byte'],excerpt,member['text_sha256']))
                await admin.execute("INSERT INTO cragkit.chunk_lexical(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,search_vector) VALUES(%s,%s,%s,%s,%s,%s,''::tsvector)",chunkkey)
            if name!='pending':
                await admin.execute('UPDATE cragkit.documents SET active_generation_id=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',(m['generation_id'],*key))
                await admin.execute('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,principal_id,grant_id,authorization_revision) VALUES(%s,%s,%s,%s,%s,%s)',(*key,inputs['scope']['principal_id'],inputs['scope']['grant_ids'][0],auth['authorization_revision']))
    return database.fixture.reader_config(role,password)
