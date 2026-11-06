# PRD — Groww Mutual Fund FAQ Assistant

**Product:** Facts-only FAQ assistant for HDFC Mutual Fund schemes on Groww
**Type:** Working RAG prototype (demo)
**Version:** 1.0
**Source document:** `problemstatment.txt`
**Date:** 05 Nov 2026

---

## 1. Overview

A small, self-contained FAQ assistant that answers **factual** questions about a fixed set of HDFC Mutual Fund schemes using only official public Groww pages. Every answer must carry exactly **one clear source link**. The assistant must refuse opinionated or portfolio-advice questions with a polite, facts-only message and an educational link.

The product is a **demonstration of a RAG pipeline**, so each stage — loading, chunking, embedding, storage, retrieval, and generation — must persist and expose its data explicitly so it can be inspected during a demo.

---

## 2. Problem Statement

Retail users comparing mutual fund schemes, and support/content teams answering repetitive mutual fund questions, need fast, trustworthy answers to factual queries (expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, statement downloads). Existing chat experiences mix facts with advice, omit citations, or pull from unofficial sources.

This product solves that with a narrow-scope RAG assistant grounded **only** in a small corpus of official Groww pages, with mandatory citations, strict refusal behavior, and no PII handling.

---

## 3. Goals & Non-Goals

### Goals
- Answer factual queries about the five scoped HDFC pages accurately and concisely.
- Cite exactly one official source link in **every** answer.
- Refuse advice/opinion/portfolio questions with a safe, polite response.
- Keep answers to **≤3 sentences** and append `Last updated from sources: <date>`.
- Expose each RAG stage (load → chunk → embed → store → retrieve → generate) for demo purposes.
- Make embedding model, vector DB, LLM, and generation parameters configurable.
- Ship with the required deliverables: prototype, source list, README, sample Q&A, disclaimer snippet.

### Non-Goals
- No investment advice, recommendations, buy/sell/hold guidance, or portfolio construction.
- No return computation, comparison, prediction, or performance claims.
- No scraping of links internal to the five scoped pages.
- No handling or storage of PII (PAN, Aadhaar, account numbers, OTPs, emails, phone numbers).
- No third-party blogs, screenshots, or unofficial sources.
- No multi-AMC or full-universe mutual fund coverage in this version.
- No live NAV tracking, transactions, or account integration.

---

## 4. Target Users

| Persona | Need |
|---|---|
| Retail investor comparing schemes | Quick, citable facts (expense ratio, exit load, lock-in, minimum SIP, riskometer) without advice. |
| Support / content team | Consistent, source-backed answers to repetitive mutual fund questions. |
| Demo reviewer / evaluator | Visibility into each RAG stage and correct citation/refusal behavior. |

---

## 5. Scope

### 5.1 In-Scope Corpus (exactly 5 pages)

| # | Page | URL |
|---|---|---|
| 1 | AMC overview — HDFC Mutual Fund | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| 2 | Large Cap — HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 3 | Flexi Cap — HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 4 | ELSS (tax saver) — HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | Mid Cap — HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

**Collection rule:** Scrape only these five pages. Do **not** crawl or scrape links internal to these pages.

### 5.2 Supported Query Types
- Expense ratio (total expense ratio / TER)
- Exit load
- Minimum SIP / minimum investment
- ELSS lock-in period
- Riskometer / risk level
- Benchmark / benchmark index
- How to download statements (capital gains / account statement)
- Fund category, plan type, and other facts present on the scoped pages

### 5.3 Out-of-Scope Query Types
- "Should I buy/sell/hold…?"
- "Which fund is better…?"
- "Will this give me X% returns…?"
- Return comparisons, forecasting, portfolio allocation, tax advice
- Any request involving PAN, Aadhaar, account numbers, OTPs, email, or phone numbers

---

## 6. Functional Requirements

### FR-1 Data Loading
- Fetch each of the five URLs through a defined loader stage.
- Persist the raw fetched content per page with metadata: `source_url`, `page_title`, `fetched_at`, `http_status`, `content_hash`.
- Store raw artifacts in a dedicated stage directory (e.g., `data/01_loaded/`).
- Handle fetch failures with retries and record failure status; do not silently drop a page.

### FR-2 Data Chunking
- Use a chunking strategy appropriate to the page structure (e.g., section-aware/hierarchical splitting around headings and key-value fact blocks, with token overlap).
- The chunking strategy is configurable and documented; an AI coding agent may select/refine it based on the corpus.
- Each chunk must persist metadata: `chunk_id`, `source_url`, `page_title`, `section`, `chunk_text`, `token_count`, `chunk_strategy`.
- Store chunks explicitly (e.g., `data/02_chunks/chunks.jsonl`) for demo inspection.

### FR-3 Data Embedding
- Embed chunks with `sentence-transformers/all-MiniLM-L6-v2` by default.
- Embedding model must be set in a config file and swappable.
- Persist embeddings and their mapping to `chunk_id` (e.g., `data/03_embeddings/`).

### FR-4 Vector Store
- Store embeddings in **ChromaDB** by default.
- Vector DB type, path, collection name, and distance metric must be configurable via config.
- Persist collection contents so they can be queried/inspected during the demo.

### FR-5 Retrieval
- Retrieve top-k chunks for the user query using the **same embedding model** and **same vector DB** used at ingestion.
- `k`, similarity metric, and score threshold configurable.
- Optionally expose retrieval scores and returned chunks in a debug/demo panel.
- Prefer chunks that directly contain the requested fact; deduplicate by source where useful.

### FR-6 Answer Generation
- Use an LLM via **Groq API** by default.
- Model ID is read from `.env` / config (default per problem statement: `qwen/qwen3.8-27b`; exact available Groq model ID to be verified at setup).
- Provider and model must be configurable to allow Gemini, OpenAI, Anthropic, or Mistral.
- The LLM must be grounded strictly in retrieved context.
- If the retrieved context does not contain the answer, respond that the information is not available in the scoped official pages, with a link to the relevant scoped page.

### FR-7 Citation
- Every answer includes **exactly one** clear source link.
- Citation must be the official scoped page URL from which the fact was derived.
- Citation wording must be explicit (e.g., `Source: <url>`).
- No answer may be returned without a citation.

### FR-8 Refusal Behavior
- Detect advice/opinion/portfolio/performance-comparison intent before or during generation.
- Respond politely, facts-only, with a relevant educational link (official source).
- Must not partially answer the advice request or imply a recommendation.
- Example refusal: "I can only share factual scheme information and can't offer investment advice. You can review the official scheme page here: <link>."

### FR-9 Answer Constraints
- Maximum **3 sentences** per answer (excluding citation and timestamp line).
- Append `Last updated from sources: <YYYY-MM-DD>` derived from ingestion date.
- No performance claims, no computed/comparative returns.
- If returns are asked, link to the official factsheet/scheme page instead of computing.

### FR-10 Privacy / PII
- Do not accept, echo, log, or store PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers.
- Add input screening that rejects or scrubs PII before retrieval/generation.
- Keep application logs free of PII.

### FR-11 UI
- Tiny single-page UI with:
  - Welcome line
  - Three example questions (clickable)
  - Note: **"Facts-only. No investment advice."**
  - Input box and answer area
  - Visible citation link in each answer
- Optional demo panel showing retrieved chunks, scores, and stage artifacts.

### FR-12 Observability / Demo Trace
- For each query, persist or display: query, retrieved chunk IDs, similarity scores, prompt sent, raw LLM response, final answer, citation, and timestamp.
- Stage artifacts must be inspectable without re-running the pipeline.

---

## 7. RAG Pipeline & Phase Plan

Implementation is **phase-wise**, with explicit persisted outputs at every stage.

| Phase | Stage | Key Output | Stored Artifact |
|---|---|---|---|
| 1 | Data Loading | Raw page content + metadata | `data/01_loaded/*.json` |
| 2 | Data Chunking | Section-aware chunks + metadata | `data/02_chunks/chunks.jsonl` |
| 3 | Data Embedding | Vectors mapped to chunk IDs | `data/03_embeddings/*` |
| 4 | Vector Store | ChromaDB collection | `data/chroma/` |
| 5 | Retrieval | Top-k chunks + scores | `data/04_retrieval/` (per query) |
| 6 | Generation | Grounded answer + citation | `data/05_answers/` (per query) |

**Phase acceptance:** each phase must be independently runnable, idempotent where practical, and produce human-inspectable output before the next phase begins.

---

## 8. Configuration

All tunable settings live in a config file (e.g., `config.yaml`) with secrets in `.env`.

```yaml
app:
  name: "Groww MF FAQ Assistant"
  max_answer_sentences: 3
  refusal_enabled: true

sources:
  urls:
    - https://groww.in/mutual-funds/amc/hdfc-mutual-funds
    - https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
    - https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth
    - https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
    - https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
  crawl_internal_links: false

chunking:
  strategy: "section_aware"   # changeable by the AI coding agent based on corpus
  chunk_size: 500
  chunk_overlap: 80
  preserve_tables: true

embedding:
  model: "sentence-transformers/all-MiniLM-L6-v2"
  normalize: true

vector_db:
  provider: "chromadb"
  persist_directory: "./data/chroma"
  collection_name: "groww_hdfc_mf"
  distance_metric: "cosine"

retrieval:
  top_k: 4
  score_threshold: 0.25

llm:
  provider: "groq"            # groq | gemini | openai | anthropic | mistral
  model: "${GROQ_MODEL}"      # set in .env, e.g. qwen/qwen3.8-27b
  temperature: 0.0
  max_tokens: 300

privacy:
  reject_pii: true
```

**`.env` (never committed):**
```
GROQ_API_KEY=...
GROQ_MODEL=qwen/qwen3.8-27b
# Optional alternates
GEMINI_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
MISTRAL_API_KEY=...
```

---

## 9. Non-Functional Requirements

- **Source integrity:** Only the five scoped Groww pages may be used as sources; no third-party blogs.
- **Determinism:** Temperature 0.0 for reproducible demo answers.
- **Resilience:** Loader retries and records failures; missing pages are surfaced, not hidden.
- **Transparency:** Every answer exposes its source URL and last-updated date.
- **Privacy:** No PII in UI, logs, traces, or stored artifacts.
- **Portability:** Runs locally from a documented setup; configurable provider/model.
- **Performance (demo target):** Query-to-answer under ~10 seconds on a typical laptop with Groq; ingestion of five pages under a few minutes.
- **Auditability:** Persisted stage artifacts allow reconstructing how any answer was produced.

---

## 10. Deliverables

| # | Deliverable | Description |
|---|---|---|
| 1 | Working prototype | Hosted app link **or** a ≤3-minute demo video if hosting isn't possible. |
| 2 | Source list | CSV/MD list of the 15–25 URLs used, with official-only sourcing. |
| 3 | README | Setup steps, scope (AMC + schemes), known limits. |
| 4 | Sample Q&A file | 5–10 queries with the assistant's answers and links. |
| 5 | Disclaimer snippet | The facts-only / no-advice text used in the UI. |

**Note on source count:** The corpus for scraping is fixed at the five pages above. The 15–25 URL source list deliverable may include the five scoped pages plus official AMC/SEBI/AMFI educational links used for refusal/education responses. No internal links of the five pages are scraped.

---

## 11. Sample Q&A (Illustrative)

| Query | Expected Answer (≤3 sentences) | Citation |
|---|---|---|
| What is the expense ratio of HDFC Large Cap Fund Direct Growth? | The expense ratio is stated on the official scheme page. | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| What is the lock-in period for HDFC ELSS Tax Saver Fund? | ELSS schemes have a statutory lock-in; confirm the exact period on the official scheme page. | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| What is the minimum SIP for HDFC Mid Cap Fund Direct Growth? | The minimum SIP amount is listed in the scheme's investment details. | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| What is the exit load? | The exit load is listed on the official scheme page. | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| How do I download my capital gains statement? | Steps are available on the official AMC/scheme page. | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| Should I buy this fund? | I can only share factual scheme information and can't offer investment advice. You can review the official scheme page here: `<link>`. | Relevant scoped page |
| Which fund will give the best returns? | I can't compare or predict returns. For official facts, see the scheme page here: `<link>`. | Relevant scoped page |

Answers in the final prototype must be generated from scraped content, not from these placeholders.

---

## 12. Disclaimer Snippet (UI)

> **Facts-only. No investment advice.**
> Answers are sourced from official Groww pages for HDFC Mutual Fund schemes and are for informational purposes only. This assistant does not recommend buying, selling, or holding any scheme. Always read official scheme documents before investing.

---

## 13. Success Metrics / Acceptance Criteria

- [ ] Exactly the five scoped pages are loaded; no internal links are crawled.
- [ ] Each pipeline stage produces persisted, inspectable artifacts.
- [ ] Embedding model, vector DB, and LLM provider/model are configurable.
- [ ] Retrieval uses the same embedding model and vector DB as ingestion.
- [ ] Every factual answer includes exactly one official source link.
- [ ] Every answer is ≤3 sentences and includes `Last updated from sources:`.
- [ ] Advice/opinion/portfolio questions are refused politely with an educational link.
- [ ] No PII is accepted, stored, or logged.
- [ ] No performance claims or computed/comparative returns appear.
- [ ] UI shows welcome line, three example questions, and the facts-only note.
- [ ] README, source list, sample Q&A, and disclaimer snippet are delivered.
- [ ] Demo prototype link or ≤3-minute video is provided.

---

## 14. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Groww page structure changes | Loader/chunker breaks | Store raw HTML, add parser tests, fail loudly with status. |
| Fact absent from scoped pages | Unsupported answer | Return "not available in scoped sources" + relevant page link. |
| LLM hallucinates a fact | Trust loss | Strict grounding prompt, temperature 0, answer validated against retrieved context. |
| Model ID mismatch on Groq | Generation fails | Read model from `.env`; verify available model at setup; provider fallback config. |
| Multiple citations slip in | Violates requirement | Post-process to enforce exactly one citation. |
| PII entered by user | Privacy violation | Input screening and rejection before retrieval/logging. |
| Advice question misclassified as factual | Policy violation | Intent classifier/prompt guard plus refusal template review. |

---

## 15. Open Questions

1. Confirm the exact Groq model identifier available for `qwen/qwen3.8-27b` (may differ from the label in the problem statement).
2. Should the app be hosted, or is a ≤3-minute demo video acceptable for submission?
3. Which official AMC/SEBI/AMFI educational URLs should populate the 15–25 URL source list beyond the five scraped pages?
4. Should the demo panel exposing retrieval chunks be visible to end users or behind a toggle?
