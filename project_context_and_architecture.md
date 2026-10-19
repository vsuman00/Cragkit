# Project Context & Architectural Specification: Agentic Retrieval Tool (CRAG SDK & MCP Server)

## 1. Executive Summary & Core Vision
We are building an **Autonomous Retrieval Sub-Agent packaged as a drop-in Tool and MCP Server** for Python and TypeScript/Node.js.
- **What we are NOT building:** Another generic "RAG-in-a-box" document loader or broad LLM framework wrapper (which is already commoditized by LlamaIndex, LangChain, etc.).
- **What we ARE building:** A stateful, self-correcting **Agentic Retrieval Loop** exposed as a single callable tool. When a parent AI agent calls this tool with a high-level question or intent, our engine autonomously handles query decomposition, hybrid search (Dense Vector + BM25 Sparse Keyword), Cross-Encoder reranking, relevance grading (Corrective RAG), automatic query rewriting on low confidence, and token-budgeted context compression before returning a clean, citation-backed payload to the parent agent.

## 2. Target Audience & Developer Experience (DX)
- **Target Users:** AI Engineers and Backend Developers building autonomous agents using LangGraph, Pydantic AI, OpenAI Agents SDK, Vercel AI SDK, Mastra, or MCP-compatible clients (Claude, Cursor).
- **Core Value Proposition:** Replace 400+ lines of brittle retrieval/reranking/retry boilerplate with a 5-line declarative tool initialization that guarantees high-signal, token-capped context and prevents main-agent context window pollution.

## 3. Core Engine Architecture (The 4-Stage State Machine)
Every time an agent invokes the retrieval tool, the engine executes a fast, deterministic 4-stage pipeline:

1. **Stage 1: Intent & Query Decomposition (Fast Router)**
   - Takes the parent agent's raw query/intent.
   - Uses a fast micro-LLM or lightweight classifier to break complex multi-part questions into parallel sub-queries, extract exact keywords (error codes, function names, IDs), and infer metadata filters.
2. **Stage 2: Parallel Hybrid Retrieval (Dense + Sparse + RRF)**
   - Executes concurrent **Dense Vector Search** (semantic similarity) and **BM25 / Full-Text Search** (exact keyword match) against the underlying storage (initially Postgres via `pgvector` + `pg_search`/TSVector, and Qdrant).
   - Merges results using **Reciprocal Rank Fusion (RRF)**.
3. **Stage 3: Cross-Encoder Reranking & Relevance Grading (The CRAG Loop)**
   - Scores the top merged candidates ($0.0$ to $1.0$) using a local reranker (e.g., FlashRank / ONNX cross-encoder) or API reranker (Cohere / Jina).
   - **Happy Path ($\text{score} \ge \text{min\_relevance\_score}$):** Passes verified chunks to Stage 4.
   - **Self-Correction Loop ($\text{score} < \text{min\_relevance\_score}$):** Triggers an internal Query Rewriter (up to `max_retries`, default $2$) that broadens search terms or relaxes metadata filters and re-runs Stage 2 without interrupting or billing the parent agent's main loop.
   - **Knowledge Gap Telemetry:** If all retries fail to cross the relevance threshold, logs a structured `KnowledgeGapEvent` (capturing the unanswered agent intent, attempted sub-queries, and max score achieved) and returns a clean "insufficient verified context" signal so the parent agent doesn't hallucinate.
4. **Stage 4: Token-Budgeted Context Compression**
   - Deduplicates overlapping chunks, strips boilerplate, attaches strict source citations (`doc_id`, `chunk_id`, `line_range`/`metadata`), and packs the output to strictly respect `max_context_tokens` (e.g., $2000$ tokens).

## 4. Dual-Language Strategy (Python + TypeScript) Without Duplicate Tech Debt
To support both Python and JS/TS ecosystems without maintaining complex retrieval math and ONNX rerankers twice:

- **Shared Storage Contract (Database Layer):**
  - Standardized schema in PostgreSQL (`pgvector` + full-text search) and Qdrant so data ingested via Python can be queried identically by either Python or TypeScript.
- **Core Engine + Universal MCP Server:**
  - The core retrieval state machine can run natively in Python or as a lightweight local/containerized service exposing both a **Model Context Protocol (MCP) Server** (`stdio` and `SSE`/`HTTP`) and a fast REST/gRPC endpoint.
- **Native SDK Wrappers:**
  - **Python Package (`pip`):** Full native engine + 1-line tool exporters: `.to_pydantic_tool()`, `.to_langchain_tool()`, `.to_openai_tool()`.
  - **TypeScript Package (`npm`):** Lightweight client + native direct DB query adapter with 1-line Zod tool exporters: `.toVercelTool()`, `.toLangChainTool()`, `.toMcpTool()`.

## 5. Target Code Interfaces (API Contract)

### Python SDK Target Interface
```python
from agentic_rag_tool import AgenticRetriever

retriever = AgenticRetriever(
    db_url="postgresql://user:pass@localhost:5432/mydb",
    collection="engineering_docs",
    hybrid_search=True,          # Auto-combines pgvector + BM25 via RRF
    reranker="flashrank-local",  # Local cross-encoder or API (cohere/jina)
    min_relevance_score=0.72,    # Threshold for CRAG self-correction loop
    max_retries=2,               # Max internal query rewrites before gap logging
    max_context_tokens=2000      # Strict ceiling on returned context
)

# Export directly as a schema-validated tool for any agent framework
rag_tool = retriever.as_tool(
    name="search_engineering_knowledge",
    description="Search architecture docs, API specs, and postmortems with verified citations."
)
```

### TypeScript SDK Target Interface
```typescript
import { AgenticRetriever } from 'agentic-rag-tool';
import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';

const retriever = new AgenticRetriever({
  connectionString: process.env.DATABASE_URL,
  collection: 'engineering_docs',
  hybridSearch: true,
  minRelevanceScore: 0.72,
  maxRetries: 2,
  tokenBudget: 2000,
});

const { text } = await generateText({
  model: openai('gpt-4o'),
  tools: {
    searchDocs: retriever.toVercelTool(),
  },
  prompt: 'Why did the payment webhook fail when scaling above 500 RPS?',
});
```

## 6. Monetization & Differentiator Strategy
- **Open-Source Core (MIT):** Python/TS SDKs, pgvector/Qdrant hybrid connectors, local reranking, CRAG retry loop, and MCP server.
- **Killer Differentiator / Commercial Layer:** **Retrieval Telemetry & Knowledge Gap Detection**. Automatically tracks every time an AI agent searches for information that is missing or outdated in the vector DB, surfacing actionable "Documentation Gap Reports" and retrieval precision metrics for engineering teams.

## 7. Instructions for AI Coding Assistants (ChatGPT / Codex)
When collaborating on this project:
1. **Prioritize Modularity & Strict Typing:** Use `Pydantic v2` and `asyncio` in Python; use strict `TypeScript` and `Zod` schemas in Node.js.
2. **Keep Dependencies Lean:** Avoid heavy framework lock-in inside the core package. Framework adapters (`langchain`, `vercel-ai`, `pydantic-ai`, `mcp`) should be modular or optional extras.
3. **Focus on Latency & Determinism:** Every stage in the retrieval state machine must track execution latency (ms) and token usage, returning structured telemetry metadata alongside the compressed context.

## 8. Suggested Phase 1 Implementation Roadmap
- **Step 1:** Define core `Pydantic v2` state models (`RetrievalRequest`, `SubQueryPlan`, `CandidateChunk`, `GradedChunk`, `KnowledgeGapEvent`, `CompressedContextPayload`).
- **Step 2:** Implement the PostgreSQL Hybrid Search connector combining `pgvector` cosine distance and `tsvector` BM25/full-text ranking via a single Reciprocal Rank Fusion (RRF) SQL query.
- **Step 3:** Build the 4-stage async state machine with local `FlashRank` cross-encoder grading and retry loop.
- **Step 4:** Expose the engine via `.as_tool()` and a FastMCP / standard MCP server entrypoint.