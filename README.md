# Groww HDFC Mutual Fund FAQ Assistant

Facts-only RAG prototype that answers questions about five HDFC Mutual Fund pages on Groww. It never gives investment advice, never compares funds or predicts returns, and rejects personal information.

**Live demo:** https://hdfc-mf-faq-376o.onrender.com

> Free Render instances sleep after 15 minutes of inactivity; the first request after that may take 30–60 seconds to wake the app.

## Scope

The corpus is fixed at these five official Groww pages. The scraper never follows, queues, or fetches links found inside them.

| Page | URL |
|---|---|
| HDFC Mutual Fund — AMC overview | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

Covered facts: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and scheme metadata such as AUM, NAV date, fund manager, and registrar.

> The supplied AMC page does not contain capital-gains-statement download instructions. Statement questions are routed to the AMC page and answered as "not available in the scoped official pages" rather than inventing a fact.

## Stack

Python 3.11 · FastAPI · httpx · BeautifulSoup · sentence-transformers (`all-MiniLM-L6-v2`, 384-d) · ChromaDB · Groq · vanilla HTML/JS.

Versions are pinned in `requirements.txt` because they were verified together on Windows 11 / Python 3.11. The important pins are:

| Component | Pin | Why |
|---|---|---|
| `sentence-transformers` | 3.3.1 | compatible with `transformers` 4.46.3 and `tokenizers` 0.20.3 |
| `transformers` / `tokenizers` | 4.46.3 / 0.20.3 | satisfies both `sentence-transformers` and `chromadb` 0.5.23 |
| `chromadb` | 0.5.23 | C++ hnswlib backend; 1.5.x crashed with an access violation on this machine |
| `numpy` | 1.26.4 | Chroma 0.5.23 does not support NumPy 2.x |
| `torch` | 2.15.0 | CPU wheel from PyPI; no GPU needed |

The embedding model, vector-DB path/collection, retrieval parameters, and LLM model are all set in `config.yaml`; the model ID is read from `GROQ_MODEL` in `.env`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Windows notes

- Python is not always on `PATH` in this environment; the direct interpreter path is `.\.venv\Scripts\python.exe`.
- If `torch` fails with `OSError: [WinError 126] ... shm.dll`, install the Microsoft VC++ 2015–2022 x64 redistributable. When elevation is unavailable, the `msvc-runtime` wheel's DLLs can be placed in `.venv\Lib\site-packages\torch\lib`, `.venv\Lib\site-packages\onnxruntime\capi`, and `.venv\Scripts`.
- Keep `chromadb` at 0.5.23. Chroma 1.5.x's Rust backend crashed even on a single-vector `add` on this machine.
- Telemetry is disabled with `chromadb.Settings(anonymized_telemetry=False)` to avoid noisy `posthog` warnings.

Create `.env` in the project root:

```dotenv
GROQ_API_KEY=your_key
GROQ_MODEL=llama-3.3-70b-versatile
```

Verify the model ID before the demo:

```powershell
python -c "from groq import Groq; import os; print([m.id for m in Groq(api_key=os.environ['GROQ_API_KEY']).models.list().data])"
```

If `GROQ_API_KEY` is empty or the Groq call fails, the API still answers from the top retrieved official chunk using a deterministic fallback. The UI and all guardrails work without a key.

## Build the index

```powershell
python -m app.scrape
python -m app.chunk
python -m app.embed
python -m app.index
```

| Step | Command | Artifact |
|---|---|---|
| Scrape | `python -m app.scrape` | `data/raw/`, `data/pages.json` |
| Chunk | `python -m app.chunk` | `data/chunks.jsonl` |
| Embed | `python -m app.embed` | `data/embeddings.npy`, `data/id_map.json` |
| Store | `python -m app.index` | `data/chroma/`, `data/manifest.json` |

The scraper also reads the page's own embedded `__NEXT_DATA__` metadata and turns parsed scheme facts into one section per fact. This keeps expense ratio, exit load, minimum SIP, benchmark, lock-in, and riskometer values together with their labels.

### Phase-wise artifacts (verified)

Each RAG stage writes an inspectable artifact, so the demo can show the pipeline instead of only the final answer:

| Phase | Artifact | Verified value |
|---|---|---|
| Loading | `data/pages.json`, `data/raw/*.html` | 5 pages, 5 fetched successfully |
| Chunking | `data/chunks.jsonl` | 92 section-aware chunks, max 173 words, 0 performance chunks |
| Embedding | `data/embeddings.npy`, `data/id_map.json` | 92 × 384 float32 vectors, row norms = 1.0 |
| Vector DB | `data/chroma/`, `data/manifest.json` | collection `hdfc_faq`, count 92, 5 distinct source URLs |
| Retrieval | `data/traces/*.json` | query, intent, retrieved chunks/scores/sections, answer, citation |
| Generation | response body + trace | one whitelisted citation, ≤3 sentences, fallback on LLM failure |

Quick inspection:

```powershell
Get-Content data\manifest.json
(Get-Content data\chunks.jsonl).Count
.\.venv\Scripts\python.exe -c "import numpy as np; print(np.load('data/embeddings.npy').shape)"
```

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open <http://localhost:8000>.

API:

- `POST /api/ask` with `{"query": "What is the ELSS lock-in period?"}`
- `GET /health`
- `GET /` serves the UI

Every answer contains exactly one official `Source:` URL and a `Last updated from sources: YYYY-MM-DD` line, and is capped at three sentences.

## Deploy

Two deployment paths are included:

| Host | Cost | Runtime | Notes |
|---|---|---|---|
| **Render** (recommended) | Free | ONNX MiniLM + NumPy index | 512 MB instance, no PyTorch/Chroma. `render.yaml` defines the service. |
| Hugging Face Spaces | $9/mo (PRO) | Docker + PyTorch + Chroma | `deploy_hf.py` creates the Docker Space in one command. |

The Render deployment uses the same `all-MiniLM-L6-v2` weights exported to ONNX, so retrieval results are identical to the local Chroma backend (verified across 20 queries). The lightweight backend peaks at ~222 MB of RAM.

```powershell
# Local sanity check of the lightweight backend
$env:RETRIEVAL_BACKEND="lite"
.\.venv\Scripts\python.exe scripts\fetch_model.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

See `DEPLOYMENT.md` for the full Render walkthrough, Hugging Face PRO path, environment variables, verification, and rollback.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite (32 tests) covers PII and advice/performance refusals, off-topic and statement not-found paths, source URL enforcement, sentence capping, table-preserving chunking, section deduplication, fact detection, internal-link avoidance, the Groq JSON/citation/fallback path, and the 503 path for a missing index.

## Guardrails

- PAN, Aadhaar, account number, OTP, email, and phone inputs are refused before retrieval. The raw PII query is never written to traces or logs.
- Buy/sell/hold, recommendation, comparison, portfolio, and return/CAGR questions are refused before retrieval.
- Statement and capital-gains questions are short-circuited to an honest "not available in the scoped official pages" response, because the five allowed pages do not document statement downloads.
- Questions with no recognised scheme/fact and no `HDFC` mention are treated as out of scope and answered without retrieval, instead of returning an unrelated chunk.
- Output validation strips body URLs, caps the body at three sentences, whitelists exactly one retrieved source URL, and falls back to the top retrieved chunk if the model fails or returns banned text.
- No performance claims, return predictions, or computed/comparative returns are produced.

## Known limits

- Statement download and capital-gains instructions are not documented on the five allowed pages, so that question returns an honest not-found with the AMC link.
- Answers are only as current as the last ingestion; `data/manifest.json` stores the ingest date.
- The Groq LLM path requires a valid API key and model. Without one, answers are deterministic extractive fact lines (for example `Expense ratio: 1.02%.`), not generated prose. The citation and format are identical either way.
- The corpus is English-only and limited to five Groww pages, so questions outside those facts return a refusal or "not available".
- `SOURCE_LIST.md` lists the five ingested/citable URLs first. The brief's 15–25 URL count is met with ten official reference pages that are explicitly not scraped, indexed, or cited, because the stricter five-page rule takes precedence.
- The performance/return sections of the source pages are intentionally excluded from the corpus, so the assistant cannot quote return figures even accidentally.
- This is an educational prototype, not investment advice.

## Deliverables

- `README.md` — setup, scope, stack, run order, guardrails, and limits
- `SOURCE_LIST.md` — five primary sources plus official reference URLs
- `SAMPLE_QA.md` — 10 real queries with the assistant's answers and links
- `DISCLAIMER.md` — the exact UI snippet and an expanded disclaimer
