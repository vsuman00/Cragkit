"""Map a small caller-owned lexical index to native Cragkit evidence contracts."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import math
import time

from cragkit.contracts import Evidence, parse_request, parse_result, parse_scope
from cragkit.evidence import pack_and_assess
from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability


CAPABILITIES = dict(search='lexical_substring', dense=False, source_resolution='synchronous_immutable_utf8',
    required_filters='string equality: document_id, revision_id, language, kind, tag', counting='estimated')
FIELDS = ('document_id','revision_id','language','kind','tag')
digest = lambda value: sha256(value).hexdigest()


class ExistingIndexAdapter:
    """Example boundary, not a universal existing-index compatibility layer."""

    def __init__(self, records, resolve_source, *, scope, collection, required_filters=(), mode='lexical'):
        if mode != 'lexical' or not callable(resolve_source):
            raise UnsupportedCapability()
        if type(records) not in (list,tuple) or len(records)>16 or any(type(row) is not dict for row in records):
            raise InvalidRequest()
        self.scope = parse_scope(scope)
        self.template = parse_request(dict(request_id='existing-index-example',query='validate',collection=collection,
            required_filters=list(required_filters),limits=dict(max_candidates=16,max_attempts=1,max_provider_calls=0,
                max_context_tokens=2000,deadline_ms=5000),output_profile=dict(renderer='cragkit.context.v2',
                counting_mode='estimated',tokenizer=None,envelope_reserve_tokens=64)))
        for item in self.template.required_filters:
            value=item.model_dump(mode='json')
            if value.get('op')!='eq' or value.get('field') not in FIELDS or type(value.get('value')) is not str:
                raise UnsupportedCapability()
        self._records = deepcopy(records)
        self._resolve = resolve_source

    def _authorized(self,row):
        return (row.get('tenant_id')==self.scope.tenant_id and row.get('collection')==self.template.collection
            and row.get('authorization_revision')==self.scope.authorization_revision
            and type(row.get('principal_ids')) is list and type(row.get('grant_ids')) is list
            and len(row['principal_ids'])<=64 and len(row['grant_ids'])<=64
            and all(type(value) is str for value in row['principal_ids']+row['grant_ids'])
            and (self.scope.principal_id in row['principal_ids'] or bool(set(self.scope.grant_ids)&set(row['grant_ids']))))

    def _filtered(self,row):
        return all(row.get(item.field)==item.value for item in self.template.required_filters)

    async def retrieve(self, query, *, deadline):
        if type(deadline) not in (int,float) or not math.isfinite(deadline):
            raise InvalidRequest()
        deadline=min(deadline,time.monotonic()+5)
        def check():
            if time.monotonic()>=deadline:raise DeadlineExceeded()
        check()
        request=parse_request({**self.template.model_dump(mode='json'),'query':query})
        evidence,sources,seen,release_rows=[],[],set(),[]
        for row in self._records:
            check()
            if not self._authorized(row):continue
            try:
                for key in ('document_id','revision_id','chunk_id','source_locator','source_sha256','text_sha256'):
                    if type(row[key]) is not str or not row[key] or len(row[key].encode())>256:raise ValueError()
                for key in ('source_sha256','text_sha256'):
                    if len(row[key])!=64 or any(char not in '0123456789abcdef' for char in row[key]):raise ValueError()
                if type(row['search_text']) is not str or len(row['search_text'].encode())>8192:raise ValueError()
                if type(row['start_byte']) is not int or type(row['end_byte']) is not int:raise ValueError()
            except (KeyError,TypeError,ValueError,UnicodeError):
                raise IntegrityViolation() from None
            if not self._filtered(row) or not all(term.lower() in row['search_text'].lower() for term in request.query.split()):continue
            try:source=self._resolve(row['tenant_id'],row['collection'],row['document_id'],row['revision_id'])
            except Exception:raise ProviderUnavailable() from None
            if source is None:raise ProviderUnavailable()
            if type(source) is not dict:raise UnsupportedCapability()
            source=deepcopy(source)
            check()
            if not self._authorized(source) or not self._filtered(source):raise UnauthorizedScope()
            try:
                if any(source[key]!=row[key] for key in ('document_id','revision_id','source_sha256')):raise ValueError()
                if type(source['text']) is not str or len(source['text'])>65536:raise ValueError()
                raw=source['text'].encode('utf-8')
                if not 1<=len(raw)<=65536 or digest(raw)!=row['source_sha256']:raise ValueError()
                start,end=row['start_byte'],row['end_byte']
                if not 0<=start<end<=len(raw):raise ValueError()
                excerpt=raw[start:end].decode('utf-8',errors='strict')
                if digest(raw[start:end])!=row['text_sha256']:raise ValueError()
                identity=[row[key] for key in ('tenant_id','collection','document_id','revision_id','chunk_id')]+[start,end,row['text_sha256']]
                item=Evidence.model_validate(dict(evidence_id='existing-'+digest(json.dumps(identity,ensure_ascii=False,
                    separators=(',',':')).encode()),**{key:row[key] for key in ('collection','document_id','revision_id','chunk_id',
                    'source_locator','start_byte','end_byte','source_sha256','text_sha256')},text=excerpt))
            except (KeyError,TypeError,ValueError,UnicodeError):
                raise IntegrityViolation() from None
            evidence.append(item.model_dump(mode='json'))
            release_rows.append(row)
            key=(row['collection'],row['document_id'],row['revision_id'])
            if key not in seen:
                seen.add(key);sources.append({name:source[name] for name in ('collection','document_id','revision_id','source_sha256','text')})
        packed=await pack_and_assess(request.query,evidence,sources,deadline=deadline,max_tokens=2000,reserve=64,
            counting_mode='estimated',surrounding_bytes=0)
        check()
        # Packing yields: reauthorize against the caller's current source authority.
        for row in release_rows:
            try:fresh=self._resolve(row['tenant_id'],row['collection'],row['document_id'],row['revision_id'])
            except Exception:raise ProviderUnavailable() from None
            if fresh is None:raise ProviderUnavailable()
            if type(fresh) is not dict:raise UnsupportedCapability()
            if not self._authorized(fresh) or not self._filtered(fresh):raise UnauthorizedScope()
            try:
                if any(fresh[key]!=row[key] for key in ('document_id','revision_id','source_sha256')):raise ValueError()
                if type(fresh['text']) is not str or len(fresh['text'])>65536:raise ValueError()
                raw=fresh['text'].encode()
                if len(raw)>65536 or digest(raw)!=row['source_sha256']:raise ValueError()
            except (KeyError,TypeError,ValueError,UnicodeError):raise IntegrityViolation() from None
            check()
        limitations=[dict(code='coverage_unknown')]
        if packed['omitted_count']:limitations.append(dict(code='truncated_evidence'))
        return parse_result(dict(request_id=request.request_id,status=packed['status'],execution='complete',
            evidence=packed['evidence'],facets=packed['facets'],context=packed['context'],limitations=limitations,
            usage=dict(attempt_count=1,provider_calls=0,provider_input_tokens=0,provider_output_tokens=0,cost_usd=0,
                cost_kind='known',context_tokens=packed['context_tokens'],context_counting='estimated'),
            versions=dict(engine='0.0.0',policy='unassessed.v0',index='existing_index_example.v1')))


def demo_data():
    text='Café retries: at most three.\n';excerpt=text[:-1]
    source=dict(tenant_id='tenant-a',collection='docs',document_id='retry',revision_id='r1',authorization_revision='auth-1',
        principal_ids=['reader-a'],grant_ids=[],language='en',kind='guide',tag='public',text=text,source_sha256=digest(text.encode()))
    record={key:value for key,value in source.items() if key!='text'}
    record.update(chunk_id='c1',source_locator='synthetic:caller-owned/retry@r1',start_byte=0,end_byte=len(excerpt.encode()),
        text_sha256=digest(excerpt.encode()),search_text=excerpt)
    scope=dict(tenant_id='tenant-a',principal_id='reader-a',grant_ids=[],authorization_revision='auth-1')
    return [record],source,scope


async def demo():
    records,source,scope=demo_data()
    resolver=lambda tenant,collection,document,revision:dict(source)
    adapter=ExistingIndexAdapter(records,resolver,scope=scope,collection='docs',required_filters=[dict(op='eq',field='tag',value='public')])
    return await adapter.retrieve('retries',deadline=time.monotonic()+5)


if __name__=='__main__':
    print(json.dumps(asyncio.run(demo()).model_dump(mode='json'),ensure_ascii=False,separators=(',',':')))
