# Architecture — Groww Mutual Fund FAQ Assistant

**Companion to:** `PRD.md`
**Version:** 1.0
**Date:** 05 Nov 2026
**Architecture style:** Local-first, modular RAG pipeline with persisted stage artifacts

---

## 1. Architectural Goals

The design is driven by five constraints from the PRD:

1. **Small, fixed corpus** — exactly five official Groww pages, no crawling.
2. **Mandatory citations** — every answer carries exactly one official source URL.
3. **Strict refusal + privacy** — advice questions refused; PII never stored or logged.
4. **Transparent RAG** — every stage (load → chunk → embed → store → retrieve → generate) writes inspectable artifacts.
5. **Swappable configuration** — embedding model, vector DB, and LLM provider are config-driven.

The system is split into two independent paths:

- **Offline ingestion pipeline** — run once (or when sources change) to build the vector index.
- **Online query service** — loads the index and answers questions through guardrails + retrieval + grounded generation.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                Browser UI                                │
│  welcome line · 3 example questions · chat box · "Facts-only" note       │
│  citation link · optional "Show retrieval details" panel                │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │ HTTPS / JSON
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Application (app/main.py)                     │
│                                                                          │
│  /api/ask          /api/trace/{id}        /api/stages/{stage}            │
│  /health           /api/corpus            static UI                      │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      QueryOrchestrator (app/query/service.py)            │
│                                                                          │
│  1. Input guard        → size, PII screening, advice/performance intent  │
│  2. Query analysis     → detect scheme + fact type, build metadata filter│
│  3. Retrieval          → embed query, Chroma top-k, threshold/dedupe     │
│  4. Generation         → grounded prompt, structured JSON answer         │
│  5. Post-processing    → enforce ≤3 sentences, exactly 1 citation, date  │
│  6. Trace persistence  → data/04_retrieval + data/05_answers             │
└───────────────┬───────────────────────────────┬──────────────────────────┘
                │                               │
                ▼                               ▼
┌──────────────────────────────┐   ┌───────────────────────────────────────┐
│   Providers (pluggable)      │   │   Persisted artifacts (data/)         │
│                              │   │                                       │
│  EmbeddingProvider           │   │  01_loaded/    raw pages + metadata   │
│   └ all-MiniLM-L6-v2         │   │  02_chunks/    chunks.jsonl           │
│  VectorStoreProvider         │   │  03_embeddings/ vectors + id map      │
│   └ ChromaDB                 │   │  chroma/       persistent collection  │
│  LLMProvider                 │   │  04_retrieval/ per-query trace        │
│   └ Groq (default)           │   │  05_answers/   final answers + trace  │
│   └ Gemini/OpenAI/Anthropic/ │   │  manifest.json corpus + ingest state  │
│     Mistral (optional)       │   │                                       │
└──────────────────────────────┘   └───────────────────────────────────────┘
```

**Key decision:** ingestion and serving are separate processes. The API never scrapes Groww at request time; it only reads the prebuilt index. This keeps answers fast, deterministic, and auditable.

---

## 3. Component Overview

| Component | Responsibility | Key module |
|---|---|---|
| Config loader | Merge `config.yaml` + `.env`, validate with Pydantic, expose typed settings | `app/config.py` |
| Loader | Fetch the 5 URLs, store raw HTML/text + metadata, retry failures | `app/ingestion/loader.py` |
| Chunker | Section-aware splitting with key-value/table preservation | `app/ingestion/chunker.py` |
| Embedder | Batch-embed chunks with configured model | `app/ingestion/embedder.py` |
| Indexer | Upsert vectors + metadata into Chroma | `app/ingestion/indexer.py` |
| Ingestion orchestrator | Run phases in order, write manifest, support `--stage`/`--force` | `app/ingestion/pipeline.py` |
| PII guard | Detect/reject PAN, Aadhaar, account numbers, OTPs, email, phone | `app/query/pii_guard.py` |
| Intent guard | Classify factual vs advice/opinion/performance; refuse safely | `app/query/intent_guard.py` |
| Query analyzer | Detect scheme alias + fact type; choose metadata filter | `app/query/analyzer.py` |
| Retriever | Embed query, search Chroma, threshold, dedupe, rank | `app/query/retriever.py` |
| Generator | Build grounded prompt, call LLM, parse structured output | `app/query/generator.py` |
| Answer post-processor | Enforce 1 citation, ≤3 sentences, date line, banned content | `app/query/postprocess.py` |
| Query orchestrator | Compose guards → retrieval → generation → validation → trace | `app/query/service.py` |
| Trace store | Persist per-query retrieval + prompt + raw response + final answer | `app/trace.py` |
| FastAPI app | JSON API + static UI + read-only artifact inspection | `app/main.py` |
| Providers | Adapters for embeddings, vector DB, LLM | `app/providers/` |
| Prompt templates | Versioned system/user/refusal prompts | `app/prompts/` |

### 3.1 Swappable provider interfaces

```python
# app/providers/embeddings.py
class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...

# app/providers/vectorstore.py
class VectorStoreProvider(Protocol):
    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...
    def query(self, vector: list[float], top_k: int, where: dict | None) -> list[RetrievedChunk]: ...
    def count(self) -> int: ...

# app/providers/llm.py
class LLMProvider(Protocol):
    def complete(self, messages: list[Message], *, temperature: float, max_tokens: int) -> str: ...
```

Factories select implementations from config:

- `embedding.provider: sentence_transformers` → `all-MiniLM-L6-v2`
- `vector_db.provider: chromadb` → persistent local collection
- `llm.provider: groq | gemini | openai | anthropic | mistral` → provider adapter (Groq via `groq` SDK; others via official SDKs or a thin LiteLLM adapter)

**Invariant:** ingestion and retrieval must resolve the same embedding provider + model and the same vector DB + collection. This is checked at startup by comparing the stored manifest against current config; a mismatch raises a clear error instead of silently returning bad results.

---

## 4. Ingestion Pipeline (Offline)

### 4.1 Data flow

```
config.sources.urls (exactly 5)
        │
        ▼
┌─────────────────┐    data/01_loaded/pages.json
│ 1. Loader       │──▶ data/01_loaded/raw/<page_id>.html
│ httpx + selectolax│   metadata: url, title, fetched_at,
│ retry/backoff   │   http_status, content_hash
└────────┬────────┘
         ▼
┌─────────────────┐    data/02_chunks/chunks.jsonl
│ 2. Chunker      │──▶ one JSON object per chunk
│ section-aware   │   metadata: chunk_id, source_url, page_title,
│ table-preserving│   section, text, token_count, strategy
└────────┬────────┘
         ▼
┌─────────────────┐    data/03_embeddings/embeddings.npy
│ 3. Embedder     │──▶ data/03_embeddings/id_map.json
│ MiniLM-L6-v2    │   data/03_embeddings/manifest.json
└────────┬────────┘
         ▼
┌─────────────────┐    data/chroma/  (persistent collection)
│ 4. Indexer      │──▶ data/manifest.json
│ Chroma upsert   │   corpus version, ingest time, hashes, config hash
└─────────────────┘
```

### 4.2 Stage contracts

| Stage | Input | Output | Idempotency rule |
|---|---|---|---|
| Load | 5 URLs from config | `pages.json` + raw files | Skip URL if `content_hash` unchanged unless `--force` |
| Chunk | `pages.json` | `chunks.jsonl` | Rebuild chunks for changed pages only |
| Embed | `chunks.jsonl` | `embeddings.npy` + `id_map.json` | Re-embed only chunk IDs without vectors |
| Index | chunks + vectors | Chroma collection + manifest | `upsert` by `chunk_id`; delete stale IDs |

### 4.3 Chunking strategy

`section_aware` is the default and is replaceable via `chunking.strategy`:

1. Parse the page into a heading hierarchy (`h1`–`h4`) and key-value fact blocks.
2. Emit one chunk per logical section, splitting long sections at sentence boundaries with overlap.
3. Keep fact tables (expense ratio, exit load, minimum SIP, lock-in, riskometer, benchmark, fund details) intact in a single chunk where possible.
4. Prepend a retrieval header to the embedded text: `"<page title> › <section>"` — stored separately from the display text so answers remain clean.
5. Target 300–600 tokens per chunk, 60–100 token overlap.

Chunk IDs are deterministic: `sha1(source_url + section_path + normalized_text)[:16]`, so re-ingestion is stable and citations remain reproducible.

### 4.4 Manifest (source of truth for freshness)

```json
{
  "corpus_version": "2026-11-05T10:15:00Z",
  "ingested_at": "2026-11-05",
  "config_hash": "…",
  "embedding": { "provider": "sentence_transformers", "model": "sentence-transformers/all-MiniLM-L6-v2", "dimension": 384 },
  "vector_db": { "provider": "chromadb", "collection": "groww_hdfc_mf", "count": 87 },
  "pages": [
    { "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth", "title": "…", "fetched_at": "…", "content_hash": "…", "status": 200 }
  ]
}
```

`ingested_at` supplies the `Last updated from sources:` value in every answer.

---

## 5. Query Pipeline (Online)

### 5.1 End-to-end sequence

```
User question
    │
    ▼
[0] Request validation ── too long / empty ──▶ 400
    │
    ▼
[1] PII guard ── PII detected ──▶ polite privacy refusal + educational link
    │                                (no retrieval, no raw query logging)
    ▼
[2] Intent guard
    ├─ advice / opinion / portfolio / performance ──▶ refusal template + link
    └─ factual ───────────────────────────────────────┐
                                                       ▼
[3] Query analyzer ── scheme alias + fact type ──▶ metadata filter
    │
    ▼
[4] Retriever ── embed query (same model) ──▶ Chroma top-k
    ├─ no chunk above threshold ──▶ "not in scoped sources" + page link
    └─ chunks ─────────────────────────────────────┐
                                                    ▼
[5] Generator ── grounded prompt ──▶ JSON {answer, citation_url}
    │
    ▼
[6] Validator / post-processor
    ├─ citation ∈ retrieved sources? exactly one URL?
    ├─ ≤3 sentences? no performance claims?
    ├─ append "Last updated from sources: <date>"
    └─ fail ──▶ one repair attempt ──▶ deterministic fallback from top chunk
    │
    ▼
[7] Trace persisted + JSON response to UI
```

### 5.2 Guardrail layers

| Layer | Mechanism | Failure behavior |
|---|---|---|
| Size/format | Max 500 characters, non-empty | 400 with guidance |
| PII | Regex + checksum/heuristic rules for PAN, Aadhaar, account numbers, OTP, email, phone | Refuse; store only `pii_redacted: true` flag, never the raw input |
| Intent | Rule-based patterns first (deterministic), optional LLM classifier as tie-breaker | Refuse with facts-only template + relevant official link |
| Retrieval grounding | `score_threshold`; allowed-source whitelist | "Not available in scoped official pages" + page link |
| Generation | Strict system prompt, temperature 0, JSON output, context-only instruction | Validation failure → repair once |
| Output | Citation whitelist, sentence count, banned phrases (`guaranteed`, `best`, `recommend`, `will give`) | Strip body URLs; use top chunk's `source_url`; truncate to 3 sentences |
| Source | Citation must be one of the five scoped URLs | Replace with best retrieved source or fallback page |

**Citation enforcement design:** the LLM never writes free-form links. It returns structured JSON:

```json
{ "answer": "The expense ratio is 0.62% for the direct plan.", "citation_url": "https://groww.in/..." }
```

The post-processor validates `citation_url` against the retrieved chunk set and then renders the final message as `answer + "\n\nSource: " + citation_url + "\nLast updated from sources: " + date`. Any URL appearing inside `answer` is stripped, guaranteeing exactly one link.

### 5.3 Query analysis (scheme + fact routing)

A deterministic alias map derived from the five page titles/slugs:

| Scheme alias | Source URL |
|---|---|
| amc, hdfc mutual fund, statement, capital gains | `.../amc/hdfc-mutual-funds` |
| large cap | `.../hdfc-large-cap-fund-direct-growth` |
| flexi cap, equity fund | `.../hdfc-equity-fund-direct-growth` |
| elss, tax saver, lock-in | `.../hdfc-elss-tax-saver-fund-direct-plan-growth` |
| mid cap | `.../hdfc-mid-cap-fund-direct-growth` |

Fact-type keywords (`expense ratio`, `exit load`, `minimum sip`, `lock-in`, `riskometer`, `benchmark`) select the query expansion terms and, when a scheme is identified, a Chroma `where: {"source_url": ...}` filter. If the filtered search returns nothing, the retriever retries unfiltered and prefers the AMC page for AMC-level questions.

### 5.4 Retrieval parameters

- Same embedding provider/model as ingestion (enforced).
- `top_k: 4` after over-fetching 12 and filtering by `score_threshold: 0.25`.
- Deduplicate near-identical chunks; keep the highest-scoring chunk per `(source_url, section)`.
- Deterministic ordering by score, then `chunk_id`.
- LRU cache for repeated query embeddings (process-local, no PII because only non-PII queries reach this stage).

### 5.5 Prompt structure

```
SYSTEM
You are a facts-only mutual fund FAQ assistant.
Use ONLY the provided context from official Groww pages.
Never give investment advice, recommendations, opinions, comparisons, or return predictions.
Answer in at most 3 sentences.
If the context does not contain the answer, say it is not available in the scoped official pages.
Return JSON only: {"answer": "...", "citation_url": "..."}
citation_url MUST be one of the context source URLs.
Do not include URLs inside "answer".

USER
Question: <non-PII user question>

Context:
[1] source_url: <url> | title: <page title> | section: <section>
<chunk text>

[2] ...

Return JSON only.
```

Prompt templates are versioned files under `app/prompts/` and the version string is recorded in each trace for auditability.

---

## 6. Data Model

### 6.1 Core entities

```python
class LoadedPage(BaseModel):
    page_id: str
    url: str
    title: str
    fetched_at: datetime
    http_status: int
    content_hash: str
    raw_path: str
    text: str

class Chunk(BaseModel):
    chunk_id: str
    source_url: str
    page_title: str
    section: str
    text: str
    token_count: int
    chunk_strategy: str
    fetched_at: datetime

class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float

class LLMAnswer(BaseModel):
    answer: str
    citation_url: str

class FinalAnswer(BaseModel):
    answer: str
    citation_url: str
    updated_at: date
    refusal: bool = False
    trace_id: str

class QueryTrace(BaseModel):
    trace_id: str
    created_at: datetime
    query: str | None              # omitted when PII was detected
    pii_redacted: bool
    intent: str                    # factual | advice | performance | pii
    filter: dict | None
    retrieved: list[RetrievedChunk]
    prompt_version: str
    prompt: str
    raw_llm_response: str
    final: FinalAnswer
    latency_ms: int
    model: str
```

### 6.2 Chroma collection metadata

Each vector record carries:

```
id: chunk_id
document: display text
embedding: 384-dim normalized vector
metadata: {
  source_url, page_title, section, content_type,
  chunk_strategy, token_count, fetched_at, ingested_at
}
```

`source_url` is the citation whitelist key. `fetched_at` feeds freshness displays; `ingested_at` feeds `Last updated from sources:`.

---

## 7. API Design

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/ask` | `{ "query": "..." }` → `FinalAnswer` + `trace_id` |
| `GET` | `/api/trace/{trace_id}` | Full trace for the demo panel |
| `GET` | `/api/corpus` | Manifest summary: pages, chunk count, ingest date, models |
| `GET` | `/api/stages/{stage}` | Read-only artifact inspection (`loaded`, `chunks`, `embeddings`, `retrieval`, `answers`) |
| `GET` | `/health` | Liveness + index loaded + collection count |
| `GET` | `/` | Static UI |

Example response:

```json
{
  "answer": "The expense ratio for the direct plan is listed in the scheme's key facts. Please refer to the official page for the current figure.\n\nSource: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth\nLast updated from sources: 2026-11-05",
  "citation_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
  "updated_at": "2026-11-05",
  "refusal": false,
  "trace_id": "q_01J..."
}
```

**No ingestion endpoint is exposed.** Index rebuilds run via CLI only, preventing public write access to the corpus.

---

## 8. UI Architecture

Single-page static UI served by FastAPI (`ui/index.html`, `app.js`, `styles.css`).

```
┌──────────────────────────────────────────────────────────────┐
│  HDFC Mutual Fund FAQ                                        │
│  Ask factual questions about the scoped HDFC schemes.        │
│                                                              │
│  [Expense ratio of HDFC Large Cap?]                          │
│  [ELSS lock-in period?]                                      │
│  [How to download capital gains statement?]                  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Ask a factual question…                        [Ask]   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Answer                                                      │
│  • answer text (≤3 sentences)                                │
│  • Source: <official link>                                   │
│  • Last updated from sources: 2026-11-05                     │
│                                                              │
│  ▸ Show retrieval details (demo)                             │
│     chunk_id · score · source_url · section                  │
│                                                              │
│  Facts-only. No investment advice.                           │
└──────────────────────────────────────────────────────────────┘
```

- Example-question chips submit directly.
- Citation renders as a real link with the official URL visible.
- Demo panel is collapsed by default and calls `/api/trace/{id}`.
- No analytics, cookies, or persistence in the browser.

---

## 9. Repository Layout

```
nextleap prjt/
├── PRD.md
├── architecture.md
├── README.md
├── config.yaml
├── .env.example
├── .gitignore
├── requirements.txt
├── app/
│   ├── main.py                 # FastAPI app + static UI mounting
│   ├── config.py               # YAML + .env → typed settings
│   ├── models.py               # Pydantic data models
│   ├── trace.py                # trace persistence
│   ├── ingestion/
│   │   ├── loader.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── indexer.py
│   │   └── pipeline.py
│   ├── query/
│   │   ├── pii_guard.py
│   │   ├── intent_guard.py
│   │   ├── analyzer.py
│   │   ├── retriever.py
│   │   ├── generator.py
│   │   ├── postprocess.py
│   │   └── service.py
│   ├── providers/
│   │   ├── embeddings.py
│   │   ├── vectorstore.py
│   │   └── llm.py
│   ├── prompts/
│   │   ├── answer.txt
│   │   ├── refuse_advice.txt
│   │   └── refuse_pii.txt
│   └── utils/
│       ├── logging.py
│       ├── text.py
│       └── tokens.py
├── ui/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── data/                       # gitignored artifacts
│   ├── 01_loaded/
│   ├── 02_chunks/chunks.jsonl
│   ├── 03_embeddings/
│   ├── 04_retrieval/
│   ├── 05_answers/
│   ├── chroma/
│   └── manifest.json
├── scripts/
│   ├── ingest.py               # phase runner: --stage load|chunk|embed|index|all
│   └── evaluate.py             # golden-set evaluation
├── docs/
│   ├── sources.md              # 15–25 official URLs
│   ├── sample_qa.md            # 5–10 Q&A with links
│   └── disclaimer.md
└── tests/
    ├── fixtures/               # saved HTML snapshots
    ├── test_loader.py
    ├── test_chunker.py
    ├── test_pii_guard.py
    ├── test_intent_guard.py
    ├── test_postprocess.py
    └── test_e2e.py
```

---

## 10. Configuration & Startup

### 10.1 Layered configuration

```
config.yaml (non-secret defaults)
      +
.env (secrets + model override)
      ↓
Pydantic Settings (validation, typed access)
      ↓
app.config.settings (singleton)
```

- Secrets never enter YAML or logs.
- `${VAR}` references in YAML are resolved from the environment.
- A config hash is stored in the manifest; ingest refuses to mix embeddings produced under different models/dimensions.

### 10.2 Startup checks

On FastAPI startup:

1. Load config; fail fast on missing `GROQ_API_KEY` when `llm.provider=groq`.
2. Load the embedding model once (singleton) — no per-request model loading.
3. Open the Chroma collection read-only.
4. Verify manifest's embedding model/dimension and collection name match config.
5. Load the alias map and prompt templates.
6. Expose `/health` with index count and ingest date.

### 10.3 Runbook

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env            # add GROQ_API_KEY
python scripts/ingest.py --all    # load → chunk → embed → index
uvicorn app.main:app --reload     # UI at http://localhost:8000
```

---

## 11. Error Handling & Fallbacks

| Failure | Handling | User sees |
|---|---|---|
| Source fetch fails after retries | Record status in `pages.json`; continue other pages | Ingest report warns; missing page excluded from index |
| Chroma collection missing/empty | `/health` degraded; `/api/ask` returns setup message | "Index not built. Run ingestion." |
| LLM timeout/rate limit | One retry with backoff; then fallback | Deterministic answer built from best chunk + citation |
| LLM invalid JSON | One repair prompt; then fallback | Fallback as above |
| Citation not in retrieved set | Replace with best retrieved source | Valid cited answer |
| No retrieval above threshold | No generation | "Not available in scoped official pages" + relevant link |
| PII detected | No retrieval, no prompt, no raw log | Privacy refusal + official link |
| Config/manifest mismatch | Refuse to serve | Startup error with remediation steps |

**Deterministic fallback:** extract the best matching sentence(s) from the top-scoring chunk, cap at 3 sentences, cite that chunk's `source_url`. This guarantees the system never returns an uncited answer or a 500 for a normal query.

---

## 12. Security, Privacy & Compliance

- **PII:** screened at input, never passed to retrieval/LLM, never written to traces or logs. Only a boolean flag and a redacted placeholder are stored.
- **Logging:** structured JSON logs with `trace_id`, latency, intent, and status only. No raw queries for PII cases. Log retention is local and short-lived.
- **Secrets:** `.env` is gitignored; `.env.example` documents keys without values.
- **Source integrity:** citation whitelist is exactly the five scoped URLs; the validator rejects anything else.
- **Prompt injection:** retrieved text is treated as untrusted context, wrapped and labeled; output validator still enforces refusal/answer rules. Corpus is fixed official pages, limiting exposure.
- **No advice:** refusal is enforced at intent detection *and* output validation, not just in the prompt.
- **No performance claims:** banned-phrase and numeric-return checks in post-processing; returns questions route to the official page.
- **No public write path:** ingestion is CLI-only; `/api/stages/*` is read-only.
- **Transport:** HTTPS in any hosted deployment; localhost for demo.

---

## 13. Testing & Evaluation

### 13.1 Test layers

| Layer | What is tested |
|---|---|
| Unit | Chunker section boundaries + table preservation; chunk ID stability; PII detectors; intent patterns; sentence limiter; citation parser |
| Contract | Provider adapters satisfy the same interface; embedding dimension consistency |
| Integration | Fixture HTML → load → chunk → embed (small model) → index → query → cited answer |
| End-to-end | Running app + golden questions; trace artifacts written and readable via API |
| Negative | Advice questions, returns questions, PII inputs, unknown facts, empty index, LLM timeout |

### 13.2 Golden evaluation set

15–20 queries covering:

- 7 fact types across 4 schemes + AMC page (expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, statement download)
- 3 advice/opinion refusals
- 2 performance-comparison refusals
- 2 PII rejections
- 2 unsupported-fact queries

Metrics recorded in `docs/eval_report.md`:

- Citation validity (must be 100%)
- Exactly-one-link compliance (must be 100%)
- Sentence-limit compliance (must be 100%)
- Refusal accuracy
- Fact groundedness (manual review against source)
- P50/P95 latency

---

## 14. Deployment

### Local demo (primary)

- Python 3.11 virtualenv, `uvicorn` on port 8000.
- Chroma persisted on disk; embedding model cached in the local HF cache.
- Suitable for the ≤3-minute demo video.

### Hosted demo (optional)

- Single container: build-time `python scripts/ingest.py --all` **or** a start-up script that ingests if `data/manifest.json` is absent.
- Mount a small persistent volume for `data/chroma` (avoids re-embedding on every restart).
- Set `GROQ_API_KEY` / `GROQ_MODEL` as platform secrets.
- Static UI served by the same FastAPI process — one service, no CORS.
- If free-tier memory is tight, pin `top_k` and run MiniLM on CPU; avoid loading multiple provider SDKs at once.

---

## 15. Phase-Wise Build Plan

| Phase | Deliverable | Verification gate |
|---|---|---|
| 0 | Config loader, models, repo skeleton, `.env.example` | `config.yaml` parses; startup check fails clearly on missing key |
| 1 | Loader + `data/01_loaded` | 5 pages fetched with metadata and hashes; internal links untouched |
| 2 | Chunker + `data/02_chunks` | Chunks align to sections; fact tables intact; stable IDs |
| 3 | Embedder + `data/03_embeddings` | 384-dim normalized vectors for every chunk |
| 4 | Chroma indexer + manifest | Collection count equals chunk count; manifest records model + date |
| 5 | Guards + retriever + `data/04_retrieval` | Top-k chunks with scores; PII/advice blocked pre-retrieval |
| 6 | Generator + post-processor + `data/05_answers` | 100% one-citation, ≤3-sentence, dated answers |
| 7 | UI + trace demo panel | Example chips work; citation visible; trace panel loads |
| 8 | README, source list, sample Q&A, disclaimer, eval report | All PRD deliverables present; acceptance checklist passes |

Each phase is independently runnable and writes its artifact before the next phase is started, matching the PRD's demo requirement.

---

## 16. Architecture Decisions (ADR Summary)

| # | Decision | Rationale |
|---|---|---|
| 1 | Offline ingestion, online serving | Fast, deterministic answers; no live scraping risk |
| 2 | Persist every stage to disk | Core demo requirement; auditability |
| 3 | Structured JSON LLM output with separate `citation_url` | Makes exactly-one-citation enforceable, not prompt-dependent |
| 4 | Deterministic guards before LLM | Reliable PII/advice refusal; cheaper and testable |
| 5 | Whitelist citations to 5 URLs | Guarantees official sourcing |
| 6 | Section-aware chunking with fact-table preservation | Mutual fund facts are key-value; generic fixed-size chunks split them |
| 7 | Single embedding model instance at startup | Matches ingestion/retrieval invariant; avoids latency spikes |
| 8 | FastAPI + static HTML (one service) | Minimal moving parts for a demo; no CORS or separate frontend build |
| 9 | Local Chroma over hosted vector DB | Zero cost, offline demo, config-swappable later |
| 10 | Deterministic fallback answer from top chunk | Guarantees citation + graceful degradation on LLM failure |

---

## 17. Known Limits

- Only five Groww pages are indexed; questions outside them return a "not available" response with a link.
- Groww page HTML changes can break the parser until fixtures are updated.
- No live NAV, transactions, or account data.
- LLM provider availability/rate limits affect latency; fallback answers are less fluent than generated ones.
- Rule-based intent detection may need tuning for unusual phrasings; an optional LLM classifier is a tie-breaker, not the primary guard.
- The demo is single-user/local; no auth, quotas, or multi-tenant isolation.

---

## 18. Open Questions (from PRD)

1. Confirm the exact Groq model ID available for `qwen/qwen3.8-27b`.
2. Hosted prototype vs. ≤3-minute demo video.
3. Final list of official AMC/SEBI/AMFI educational URLs for the 15–25 URL source list.
4. Whether the retrieval-trace panel stays as a demo toggle or is hidden in the final submission.
