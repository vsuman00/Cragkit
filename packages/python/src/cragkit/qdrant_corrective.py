"""Optional dense Qdrant backend for the native corrective engine."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .contracts import parse_request,parse_scope
from .corrective import QdrantCandidate,_candidate
from .embeddings import EmbeddingAdapter,EmbeddingLimits,EmbeddingProfile,EmbeddingPolicy,EmbeddingTransport,TokenCounter
from .errors import EmbeddingProfileMismatch,IntegrityViolation,InvalidRequest,UnsupportedCapability
from .execution import ExecutionLedger
from .qdrant import QdrantSearchStore,bind_embedding_batch,compile_filter
from .qdrant_source import PostgresQdrantSourceStore
from ._qdrant_transport import deadline_value


class QdrantCorrectiveBackend:
    """Compose caller-owned initialized stores with an explicit model transport."""

    candidate_accounting='backend'

    def __init__(self,candidates:QdrantSearchStore,sources:PostgresQdrantSourceStore,*,
                 embedding_transport:EmbeddingTransport,token_counter:TokenCounter,
                 policy:EmbeddingPolicy|None=None,mode:str='dense') -> None:
        if mode!='dense':raise UnsupportedCapability()
        if (type(candidates) is not QdrantSearchStore or type(sources) is not PostgresQdrantSourceStore
                or not callable(embedding_transport) or not callable(getattr(token_counter,'count',None))):
            raise InvalidRequest()
        if candidates.config.dense_profile!=sources.config.dense_profile:
            raise EmbeddingProfileMismatch()
        if candidates.config!=sources.config:raise UnsupportedCapability()
        self._candidates,self._sources=candidates,sources
        self._transport,self._counter=embedding_transport,token_counter
        self._profile=EmbeddingProfile.model_validate(candidates.config.dense_profile.model_dump())
        self._policy=EmbeddingAdapter(embedding_transport,token_counter,profile=self._profile,policy=policy).policy

    def capabilities(self) -> Mapping[str,bool]:
        return MappingProxyType(dict(dense=True,lexical=False,hybrid=False,current_source_authority=True,
            publication=False,repair=False,owns_resources=False))

    async def search(self,request:Any,*,scope:Any,deadline:float,limit:int,
                     ledger:ExecutionLedger) -> dict[str,Any]:
        request=parse_request(request.model_dump(mode='json'))
        scope=parse_scope(scope.model_dump(mode='json'))
        if type(ledger) is not ExecutionLedger or type(limit) is not int or not 1<=limit<=min(64,request.limits.max_candidates):
            raise InvalidRequest()
        end=deadline_value(min(deadline,ledger.deadline))
        compile_filter(request,scope)
        token=None;adapter=None;admission_error=None
        async def accounted(body:bytes,*,deadline:float,max_response_bytes:int) -> bytes:
            nonlocal token,admission_error
            assert adapter is not None
            upper=0.0 if self._profile.provider=='fake' else adapter.policy.max_cost_usd
            try:
                token=ledger.reserve(provider_calls=1,cost_upper_usd=upper)
                ledger.dispatch(token)
            except BaseException as error:
                admission_error=error
                raise
            return await self._transport(body,deadline=deadline,max_response_bytes=max_response_bytes)
        adapter=EmbeddingAdapter(accounted,self._counter,profile=self._profile,
            limits=EmbeddingLimits(max_items=1),policy=self._policy)
        try:
            batch=await adapter.embed_query(request.query,deadline=end)
            batch=bind_embedding_batch(batch,self._profile,expected_items=1)
            if token is None:raise IntegrityViolation()
            usage=batch.usage
            output=(usage.total_tokens-usage.prompt_tokens if usage.total_tokens is not None and usage.prompt_tokens is not None else None)
            ledger.reconcile(token,input_tokens=usage.prompt_tokens,output_tokens=output,
                cost_usd=usage.cost_usd if usage.cost_kind=='known' else None)
            token=None
        except BaseException:
            if admission_error is not None:raise admission_error from None
            raise
        finally:
            if token is not None:ledger.abandon(token)
        nominations=await self._candidates.search_candidates(request,scope=scope,dense=batch,
            branch_limits=dict(dense=limit),ledger=ledger,deadline=end)
        fields=('tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','text_sha256')
        values=[]
        for nomination in nominations:
            row=dict(**{key:getattr(nomination.payload,key) for key in fields},backend='qdrant',score=nomination.score,
                nomination=nomination.model_dump(mode='json'))
            values.append(_candidate(row,request,scope))
        return dict(candidates=values,degraded=False)

    async def capture(self,candidates:Any,*,request:Any,scope:Any,deadline:float,
                      max_source_bytes:int,ledger:ExecutionLedger) -> dict[str,Any]:
        request=parse_request(request.model_dump(mode='json'))
        scope=parse_scope(scope.model_dump(mode='json'))
        if (type(ledger) is not ExecutionLedger or type(max_source_bytes) is not int or not 0<=max_source_bytes<=16777216
                or type(candidates) not in (list,tuple) or len(candidates)>64):raise InvalidRequest()
        end=deadline_value(min(deadline,ledger.deadline))
        selected=[]
        for item in candidates:
            parsed=_candidate(item,request,scope)
            if not isinstance(parsed,QdrantCandidate):raise IntegrityViolation()
            selected.append(parsed)
        keys=[item.nomination.point_id for item in selected]
        if len(keys)!=len(set(keys)):raise IntegrityViolation()
        handle=self._sources.open_request(request,scope=scope,deadline=end)
        loaded=0;stale=False;exhausted=False;evidence=[]
        sources:dict[tuple[str,str,str],dict[str,str]]={}
        try:
            for item in selected:
                if loaded>=max_source_bytes:exhausted=True;break
                fetched=await handle.fetch_candidate(item.nomination,max_source_bytes=max_source_bytes-loaded,include_source=False)
                loaded+=fetched.source_bytes
                if fetched.state!='verified':
                    stale=stale or fetched.state=='unavailable';exhausted=exhausted or fetched.state=='budget_exhausted';continue
                released=await handle.release(fetched.binding,purpose='final',max_source_bytes=max_source_bytes-loaded,include_source=True)
                loaded+=released.source_bytes
                if released.state!='verified':
                    stale=stale or released.state=='unavailable';exhausted=exhausted or released.state=='budget_exhausted';continue
                if released.evidence is None or released.private_source is None:raise IntegrityViolation()
                row=released.evidence.model_dump(mode='json')
                source={key:row[key] for key in ('collection','document_id','revision_id','source_sha256')}
                source['text']=released.private_source.canonical_text
                key=(row['collection'],row['document_id'],row['revision_id'])
                if key in sources and sources[key]!=source:raise IntegrityViolation()
                sources[key]=source;evidence.append(row);stale=stale or fetched.stale or released.stale
            deadline_value(end)
            return dict(evidence=evidence,sources=list(sources.values()),source_bytes=loaded,stale=stale,budget_exhausted=exhausted)
        finally:await handle.close()


__all__=['QdrantCorrectiveBackend']
