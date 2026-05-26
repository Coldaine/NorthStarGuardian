---
{
  "version": 1,
  "project_name": "LumenScout",
  "identity_statement": "LumenScout is an LLM-powered, local-first research assistant that helps knowledge workers surface, connect, and annotate information from their own document libraries. It is not a cloud sync tool, a general-purpose search engine, or a data pipeline that touches external APIs without explicit user consent. Every insight it produces must be traceable to a source the user controls.",
  "approved_architecture": "Python 3.11+, Pydantic v2 models for all domain objects, LlamaIndex for document ingestion and retrieval, Anthropic SDK (claude-sonnet-4-6) for reasoning and synthesis, SQLite via aiosqlite for local persistence, FastAPI for the optional local HTTP interface, Jinja2 for report templating. No hosted vector databases — embeddings live in a local FAISS index under ~/.lumenscout/index/.",
  "created_at": "2026-01-15T09:00:00+00:00",
  "principles": [
    {
      "id": "p1",
      "rank": 1,
      "text": "All information synthesis must flow through the LLM reasoning layer — no raw keyword extraction or regex-only summarisation shipped to the user.",
      "rationale": "The core value proposition is reasoned synthesis, not search. Bypassing the LLM collapses LumenScout into a glorified grep.",
      "tags": ["[OWNER]", "{LOCKED}", "«CORE»"]
    },
    {
      "id": "p2",
      "rank": 2,
      "text": "Local-first always: all document storage, indexing, and retrieval must operate without a network connection. No user content may be transmitted to a third-party service without an explicit opt-in confirmation dialog.",
      "rationale": "Privacy is a first-class feature. Users trust LumenScout with sensitive research; that trust requires a credible local-only default.",
      "tags": ["[OWNER]", "{LOCKED}", "«CORE»"]
    },
    {
      "id": "p3",
      "rank": 3,
      "text": "Use LlamaIndex for all document ingestion, chunking, and retrieval — do not hand-roll a retrieval pipeline or introduce a competing RAG library.",
      "rationale": "LlamaIndex is the declared retrieval substrate. Parallel pipelines create maintenance burden and make debugging retrieval quality nearly impossible.",
      "tags": ["[OWNER]", "{LOCKED}", "«CORE»"]
    },
    {
      "id": "p4",
      "rank": 4,
      "text": "Every response shown to the user must include at least one source citation linking back to a document and page in the user's library.",
      "rationale": "Traceability is non-negotiable. Ungrounded synthesis undermines user trust and makes error correction impossible.",
      "tags": ["[INFERRED]", "{DRAFT}", "«SECONDARY»"]
    },
    {
      "id": "p5",
      "rank": 5,
      "text": "The optional FastAPI interface is a convenience layer only — all business logic must be accessible as plain Python calls without running the server.",
      "rationale": "CLI and library consumers are first-class users. Coupling logic to the HTTP layer makes testing and scripting harder than it needs to be.",
      "tags": ["[INFERRED]", "{DRAFT}", "«OPTIONAL»"]
    }
  ],
  "anti_patterns": [
    {
      "id": "ap1",
      "description": "Standalone scripts that read documents and produce output without invoking the LLM reasoning layer.",
      "example": "A scripts/extract_keywords.py that runs spaCy NER directly and writes a CSV — this bypasses Principle 1 entirely.",
      "detect": "scripts/*.py"
    },
    {
      "id": "ap2",
      "description": "Outbound HTTP calls to external embedding or inference APIs without a user-visible opt-in prompt.",
      "example": "Silently sending document chunks to OpenAI Embeddings API during ingestion — violates Principle 2 regardless of perceived benefit.",
      "detect": "openai|cohere|voyage|huggingface.co"
    },
    {
      "id": "ap3",
      "description": "Introducing a second retrieval library (e.g. Haystack, LangChain retrievers) alongside LlamaIndex, even for a single feature.",
      "example": "Adding langchain.retrievers.MultiQueryRetriever for an experimental re-ranking feature — creates a parallel pipeline that violates Principle 3.",
      "detect": "from langchain|import haystack"
    }
  ]
}
---

# LumenScout — North Star

## Identity

LumenScout is an LLM-powered, local-first research assistant that helps knowledge workers surface, connect, and annotate information from their own document libraries. It is not a cloud sync tool, a general-purpose search engine, or a data pipeline that touches external APIs without explicit user consent. Every insight it produces must be traceable to a source the user controls.

## Principles

### 1. All information synthesis must flow through the LLM reasoning layer — no raw keyword extraction or regex-only summarisation shipped to the user.

`[OWNER]` `{LOCKED}` `«CORE»`

The core value proposition is reasoned synthesis, not search. Bypassing the LLM collapses LumenScout into a glorified grep.

### 2. Local-first always: all document storage, indexing, and retrieval must operate without a network connection. No user content may be transmitted to a third-party service without an explicit opt-in confirmation dialog.

`[OWNER]` `{LOCKED}` `«CORE»`

Privacy is a first-class feature. Users trust LumenScout with sensitive research; that trust requires a credible local-only default.

### 3. Use LlamaIndex for all document ingestion, chunking, and retrieval — do not hand-roll a retrieval pipeline or introduce a competing RAG library.

`[OWNER]` `{LOCKED}` `«CORE»`

LlamaIndex is the declared retrieval substrate. Parallel pipelines create maintenance burden and make debugging retrieval quality nearly impossible.

### 4. Every response shown to the user must include at least one source citation linking back to a document and page in the user's library.

`[INFERRED]` `{DRAFT}` `«SECONDARY»`

Traceability is non-negotiable. Ungrounded synthesis undermines user trust and makes error correction impossible.

### 5. The optional FastAPI interface is a convenience layer only — all business logic must be accessible as plain Python calls without running the server.

`[INFERRED]` `{DRAFT}` `«OPTIONAL»`

CLI and library consumers are first-class users. Coupling logic to the HTTP layer makes testing and scripting harder than it needs to be.

## Approved Architecture

Python 3.11+, Pydantic v2 models for all domain objects, LlamaIndex for document ingestion and retrieval, Anthropic SDK (claude-sonnet-4-6) for reasoning and synthesis, SQLite via aiosqlite for local persistence, FastAPI for the optional local HTTP interface, Jinja2 for report templating. No hosted vector databases — embeddings live in a local FAISS index under ~/.lumenscout/index/.

## Anti-Patterns

### ap1

Standalone scripts that read documents and produce output without invoking the LLM reasoning layer.

*Example:* A scripts/extract_keywords.py that runs spaCy NER directly and writes a CSV — this bypasses Principle 1 entirely.

*Detect:* `scripts/*.py`

### ap2

Outbound HTTP calls to external embedding or inference APIs without a user-visible opt-in prompt.

*Example:* Silently sending document chunks to OpenAI Embeddings API during ingestion — violates Principle 2 regardless of perceived benefit.

*Detect:* `openai|cohere|voyage|huggingface.co`

### ap3

Introducing a second retrieval library (e.g. Haystack, LangChain retrievers) alongside LlamaIndex, even for a single feature.

*Example:* Adding langchain.retrievers.MultiQueryRetriever for an experimental re-ranking feature — creates a parallel pipeline that violates Principle 3.

*Detect:* `from langchain|import haystack`
