# Cragkit architecture diagram catalog

Design baseline v0.1. All diagrams describe proposed behavior. SVG overview views are static and self-contained; Mermaid sources are editable. The full contracts and exceptions are in [ARCHITECTURE.md](ARCHITECTURE.md).

## System context and library boundaries

![System context and library boundaries](diagrams/01-system.svg)

[Editable source](diagrams/01-system.mmd)

```mermaid
flowchart TB
    APP[Application: trusted identity and final answers]
    TOOL[Optional framework tool adapter]
    MCP[Optional MCP host]
    APP --> PY[Native Python library]
    APP --> TS[Native TypeScript library]
    TOOL --> PY
    TOOL --> TS
    MCP --> PY
    MCP --> TS
    SPEC[Shared contracts and conformance fixtures] -.-> PY
    SPEC -.-> TS
    PY --> PORTS[Store and model adapter interfaces]
    TS --> PORTS
    PORTS --> PG[(PostgreSQL reference store)]
    PORTS --> QD[(Qdrant alternative profile)]
    PORTS --> MODEL[Configured local or remote model providers]
    PORTS --> OBS[Opt-in redacted telemetry]
    ING[Separate ingestion write path] --> PG
    ING --> QD
    QD --> SRC[SourceStore and publication manifest]
```

## Request state machine

![Request state machine](diagrams/02-retrieval.svg)

[Editable source](diagrams/02-retrieval.mmd)

```mermaid
flowchart TD
    A[Query and trusted scope] --> B[Validate capabilities, limits and profiles]
    B --> C[Preserve original query and plan facets]
    C --> D[Scoped dense, lexical and identifier retrieval]
    D --> E[Stable identity merge and weighted RRF]
    E --> F[Bounded reranking]
    F --> G[Assess evidence per required facet]
    G --> H{Useful correction within budget?}
    H -->|Yes| I[Target missing facets; preserve scope; retain evidence]
    I --> D
    H -->|No| J[Reauthorize source fetch and validate exact spans]
    J --> K[Deduplicate, expand context, pack and count]
    K --> L[Reassess only packed evidence]
    L --> M[Sufficient, partial or insufficient estimate]
    B -.-> X[Typed operational failure or cancellation]
    D -.-> X
    F -.-> X
    J -.-> X
    K -.-> X
    LEDGER[Shared deadline, call and candidate limits] -.-> D
    LEDGER -.-> I
    LEDGER -.-> K
```

## Ingestion, updates and publication

![Ingestion, updates and publication](diagrams/03-ingestion.svg)

[Editable source](diagrams/03-ingestion.mmd)

```mermaid
flowchart TD
    A[Caller text or supported loader] --> B[Validate write scope, metadata and size]
    B --> C[Preserve source digest; extract canonical UTF-8]
    C --> D[Structure-aware chunks with byte spans]
    D --> E[Create immutable revision and staging generation]
    E --> F[Bounded embeddings and lexical indexing]
    F --> G[Validate digests, dimensions and completeness]
    G --> H{Generation ready?}
    H -->|Yes| I[Atomic compare-and-swap publication]
    H -->|No| J[Record failure; retain prior active generation]
    I --> K[New requests see published generation]
    J --> F
    DEL[Authorized delete] --> T[Tombstone immediately]
    T --> P[Purge indexes, source and caches per retention]
    ACL[Authorized permission update] --> R[Change authorization revision and invalidate caches]
```

## Logical data relationships

[Editable source](diagrams/04-data-model.mmd)

```mermaid
erDiagram
    COLLECTION ||--o{ DOCUMENT : contains
    DOCUMENT ||--o{ DOCUMENT_REVISION : versions
    DOCUMENT ||--o{ DOCUMENT_GRANT : permits
    DOCUMENT_REVISION ||--o{ INDEX_GENERATION : indexes
    INDEX_GENERATION ||--o{ CHUNK : contains
    CHUNK ||--o{ CHUNK_VECTOR : embeds
    CHUNK ||--o| CHUNK_LEXICAL : indexes
    INDEX_GENERATION ||--o{ INGESTION_JOB : builds
    DOCUMENT {
        string tenant_id
        string collection_id
        string document_id
        string active_generation_id
        string authorization_revision
        boolean tombstoned
    }
    DOCUMENT_REVISION {
        string revision_id
        string canonical_text_digest
        string parser_profile
        string source_locator
    }
    INDEX_GENERATION {
        string generation_id
        string embedding_profile
        string chunker_profile
        string lexical_profile
        string status
    }
    CHUNK {
        string chunk_id
        int start_byte
        int end_byte
        string text_digest
    }
```

## Database connection and request sequence

[Editable source](diagrams/05-request-sequence.mmd)

```mermaid
sequenceDiagram
    participant App as Application
    participant Lib as Native library
    participant Pool as PostgreSQL pool
    participant DB as PostgreSQL
    participant Model as Model adapter
    App->>Lib: retrieve(request, trusted scope)
    Lib->>Lib: Validate and establish shared deadline
    Lib->>Model: Embed query under budget
    Model-->>Lib: Vector and profile
    Lib->>Pool: Acquire before deadline
    Pool-->>Lib: Connection
    Lib->>DB: Begin read transaction; bind scoped context
    Lib->>DB: Scoped candidate query, active generation snapshot
    DB-->>Lib: Ranked lists and immutable revision IDs
    Lib->>DB: End read transaction
    Lib->>Pool: Release connection
    Lib->>Lib: Merge and fuse
    Lib->>Model: Bounded rerank and optional assessment
    Model-->>Lib: Scores and facet estimates
    opt Useful correction with remaining budget
        Lib->>Lib: Rewrite missing facet; repeat bounded search
    end
    Lib->>Pool: Acquire for authorized source fetch
    Lib->>DB: Recheck grants/tombstones; fetch exact revision spans
    DB-->>Lib: Allowed evidence or revocation
    Lib->>Pool: Release in finally
    Lib->>Lib: Verify spans; pack; count; reassess
    Lib-->>App: Evidence result, limitations and usage
```

## Trust boundaries and provider disclosure

[Editable source](diagrams/06-authorization.mmd)

```mermaid
flowchart LR
    USER[Untrusted user or agent query] --> APP[Application authentication]
    APP --> SCOPE[Trusted tenant and principal scope]
    USER --> REQ[Validated query and allowlisted filters]
    SCOPE --> ENGINE[Native engine]
    REQ --> ENGINE
    ENGINE --> FILTER[Scope AND required filters]
    FILTER --> SEARCH[Filtered database candidate search]
    SEARCH --> CHECK[Authorize candidate content]
    CHECK --> PROVIDER[Explicitly allowed model provider]
    PROVIDER --> FETCH[Final source authorization and integrity check]
    FETCH --> OUT[Evidence to caller]
    DOC[Untrusted document instructions] -.-> DATA[Handled only as source data]
    DATA -.-> CHECK
    ENGINE --> TRACE[Redacted metadata; raw content off by default]
```

## Native runtime conformance

[Editable source](diagrams/07-parity.mmd)

```mermaid
flowchart TB
    CONTRACT[Normative schemas and behavior specification] --> FIX[Shared deterministic fixtures]
    FIX --> PY[Python engine tests]
    FIX --> TS[TypeScript engine tests]
    PY --> COMP[Compare outputs, ordering, spans and error codes]
    TS --> COMP
    COMP --> DB[Cross-runtime shared database integration tests]
    DB --> LIVE[Separate live-provider quality and performance tests]
    LIVE --> PKG[Clean wheel, sdist and npm tarball install tests]
    PKG --> RELEASE[Versioned release evidence]
```

## Build dependency map

[Editable source](diagrams/08-phases.mmd)

```mermaid
flowchart LR
    P0[0: Contracts and corpus] --> P1[1: Two-runtime lexical vertical slice]
    P1 --> P2[2: Hybrid retrieval]
    P2 --> P3[3: Rerank, pack and assess]
    P3 --> P4[4: Bounded correction]
    P4 --> P5[5: Usable alpha packages]
    P5 --> P6[6: Qdrant and MCP extensions]
    P6 --> P7[7: Evaluated release candidate]
    P7 -.-> L[Later: OCR, multi-hop, answer verification, telemetry UI]
```

## Evidence quality and execution outcome

[Editable source](diagrams/09-result-policy.mmd)

```mermaid
flowchart TD
    A[Completed packed evidence] --> B{Any usable evidence?}
    B -->|No| I[Insufficient]
    B -->|Yes| C{All required facets supported?}
    C -->|No or unknown| P[Partial]
    C -->|Yes| D{Unresolved required conflict?}
    D -->|Yes| P
    D -->|No| S[Sufficient estimate]
    I --> EXEC[Attach independent complete or degraded execution state]
    P --> EXEC
    S --> EXEC
    EXEC --> OUT[Return limitations, provenance and accounting]
    FAIL[Operational failure or cancellation] --> ERR[Typed error; never disguise as absent evidence]
```
