# Implementation Guide — Groww HDFC MF FAQ Assistant (Simplified)

**Companion to:** `PRD.md` and `architecture.md`
**Scope:** Facts-only FAQ assistant built from the five supplied Groww pages

**Source rule:** Scrape and cite **only the five URLs below**. Do not follow, fetch, or extract links found inside those pages.

| # | Page | URL |
|---|---|---|
| 1 | HDFC Mutual Fund — AMC overview | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| 2 | HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 3 | HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 4 | HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

---

## 0. Stack and Config

**Stack:** Python 3.11 · FastAPI · httpx · BeautifulSoup · sentence-transformers (`all-MiniLM-L6-v2`) · ChromaDB · Groq · vanilla HTML/JS.

`requirements.txt`:

```txt
fastapi
uvicorn
httpx
beautifulsoup4
lxml
tenacity
sentence-transformers
chromadb
numpy
groq
python-dotenv
pyyaml
pytest
```

`config.yaml`:

```yaml
sources:
  urls:
    - https://groww.in/mutual-funds/amc/hdfc-mutual-funds
    - https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
    - https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth
    - https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
    - https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
  crawl_internal_links: false
  timeout_seconds: 30
  delay_seconds: 1.0
  user_agent: "GrowwMFFAQDemo/1.0"

chunking:
  strategy: section_aware
  # MiniLM truncates at 256 tokens (~180 words). Keep chunks below that.
  max_words: 180

embedding:
  model: sentence-transformers/all-MiniLM-L6-v2
  batch_size: 32

vector_db:
  path: data/chroma
  collection: hdfc_faq

retrieval:
  top_k: 4
  over_fetch: 12
  min_score: 0.25

llm:
  provider: groq
  model: ${GROQ_MODEL}
  temperature: 0.0
  max_tokens: 300
```

`.env`:

```dotenv
GROQ_API_KEY=your_key
GROQ_MODEL=verify-an-available-groq-model-id
```

> Verify the Groq model ID with `client.models.list()` before the demo. Never hardcode a model name in source.

`.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.env
data/
.pytest_cache/
```

> The five URLs are also enforced in code: `load_config()` raises if the list does not contain exactly five entries.

---

## 1. Create the Directory

```
nextleap prjt/
├── config.yaml
├── .env
├── .gitignore
├── requirements.txt
├── pytest.ini
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── scrape.py
│   ├── chunk.py
│   ├── embed.py
│   ├── index.py
│   ├── guardrails.py
│   ├── retrieve.py
│   ├── generate.py
│   └── main.py
├── ui/
│   ├── index.html
│   └── app.js
├── data/                     # generated, gitignored
│   ├── raw/
│   ├── pages.json
│   ├── chunks.jsonl
│   ├── embeddings.npy
│   ├── id_map.json
│   ├── chroma/
│   ├── traces/
│   └── manifest.json
└── tests/
    ├── test_scrape.py
    ├── test_chunk.py
    ├── test_guardrails.py
    ├── test_retrieval.py
    └── test_api.py
```

Setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`pytest.ini` puts the project root on `sys.path` so `from app...` imports work without installing the package:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

`app/config.py`:

```python
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")
ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")


def _expand(value):
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: Path | None = None) -> dict:
    path = path or (ROOT / "config.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = _expand(raw)
    urls = cfg["sources"]["urls"]
    if len(urls) != 5:
        raise ValueError(f"Expected exactly 5 source URLs, got {len(urls)}")
    return cfg


CONFIG = load_config()
URLS: list[str] = CONFIG["sources"]["urls"]
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"
```

---

## 2. Scrape the Documents

### Rules

- Iterate **only** over `config.yaml → sources.urls` (exactly five).
- Never parse `<a href="...">` into new requests.
- Do not crawl, queue, or fetch any link discovered in the HTML.
- Save raw HTML plus cleaned text and metadata.
- Retry transient failures; record failures instead of crashing.
- Never store PII from a page. The pages are public scheme facts only.

### `app/scrape.py`

```python
import hashlib
import json
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import CONFIG, DATA, URLS

RAW_DIR = DATA / "raw"
PAGES_FILE = DATA / "pages.json"

REMOVE = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form"}
BLOCKS = ["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "table", "blockquote"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
def fetch(url: str) -> httpx.Response:
    return httpx.get(
        url,
        timeout=CONFIG["sources"]["timeout_seconds"],
        follow_redirects=True,
        headers={"User-Agent": CONFIG["sources"]["user_agent"]},
    )


def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(REMOVE):
        tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body
    if root is None:
        return ""

    lines: list[str] = []
    for el in root.find_all(BLOCKS):
        if el.find_parent("table") and el.name != "table":
            continue
        if el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
        else:
            text = " ".join(el.get_text(" ", strip=True).split())
        if text:
            lines.append(text)
    return "\n".join(lines)


def fetch_all(raw_dir: Path = RAW_DIR) -> list[dict]:
    if len(URLS) != 5:
        raise ValueError("Only the five supplied URLs are allowed")

    raw_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []

    for i, url in enumerate(URLS):
        page_id = url.rstrip("/").split("/")[-1]
        raw_path = raw_dir / f"{page_id}.html"
        try:
            resp = fetch(url)
            resp.raise_for_status()
            html = resp.text
            raw_path.write_text(html, encoding="utf-8")
            soup = BeautifulSoup(html, "lxml")
            pages.append(
                {
                    "url": url,
                    "page_id": page_id,
                    "title": soup.title.get_text(strip=True) if soup.title else page_id,
                    "status": resp.status_code,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "content_hash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                    "raw_path": str(raw_path),
                    "text": clean_text(html),
                }
            )
        except Exception as exc:
            pages.append(
                {
                    "url": url,
                    "page_id": page_id,
                    "title": page_id,
                    "status": 0,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "content_hash": "",
                    "raw_path": str(raw_path) if raw_path.exists() else "",
                    "text": "",
                    "error": type(exc).__name__,
                }
            )
        if i < len(URLS) - 1:
            time.sleep(CONFIG["sources"]["delay_seconds"])

    return pages


def main() -> None:
    pages = fetch_all()
    PAGES_FILE.write_text(
        json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ok = sum(1 for p in pages if p["status"] == 200)
    print(f"[scrape] {len(pages)} pages | {ok} ok | {len(pages) - ok} failed")


if __name__ == "__main__":
    main()
```

### Output

- `data/raw/<page_id>.html` — raw HTML snapshot
- `data/pages.json` — one object per URL with `url`, `page_id`, `title`, `status`, `fetched_at`, `content_hash`, `raw_path`, `text`

**Check:** `data/pages.json` has exactly five entries, and every network request was made to one of the five configured URLs.

---

## 3. Chunk the Documents

### Strategy

- **Section-aware:** split on `h1`–`h4`, keeping the heading path as section metadata.
- **Preserve labels and values:** convert tables to `label | value` rows so facts like `Expense ratio | 0.62%` stay together.
- **Keep short fact lines:** a short key-value chunk (contains `|` or `:`) is often the exact answer.
- **Stay inside MiniLM's limit:** target ≤180 words per chunk.
- **Embed title + section + text**, but display only the chunk text.

### `app/chunk.py`

```python
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.config import CONFIG, DATA

PAGES_FILE = DATA / "pages.json"
CHUNKS_FILE = DATA / "chunks.jsonl"
MAX_WORDS = CONFIG["chunking"]["max_words"]

HEADINGS = {"h1", "h2", "h3", "h4"}
BLOCKS = ["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "table", "blockquote"]


def table_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def sections_from_html(html: str) -> dict[str, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(
        ["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]
    ):
        tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body
    if root is None:
        return {}

    sections: dict[str, list[str]] = {"General": []}
    stack: list[str] = []
    current = "General"

    for el in root.find_all(BLOCKS):
        if el.find_parent("table") and el.name != "table":
            continue
        if el.name in HEADINGS:
            label = " ".join(el.get_text(" ", strip=True).split())
            if not label:
                continue
            level = int(el.name[1])
            stack = stack[: level - 1]
            stack.append(label)
            current = " › ".join(stack)
            sections.setdefault(current, [])
            continue
        text = (
            table_text(el)
            if el.name == "table"
            else " ".join(el.get_text(" ", strip=True).split())
        )
        if text:
            sections.setdefault(current, []).append(text)

    return {k: v for k, v in sections.items() if v}


def split_text(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """Split on sentence boundaries so facts are never cut mid-sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    buf: list[str] = []
    count = 0

    for sentence in sentences:
        words = len(sentence.split())
        if buf and count + words > max_words:
            pieces.append(" ".join(buf))
            buf, count = [], 0
        buf.append(sentence)
        count += words

    if buf:
        pieces.append(" ".join(buf))
    return [p for p in pieces if p.strip()]


def build_chunks(pages: list[dict] | None = None) -> list[dict]:
    if pages is None:
        pages = json.loads(PAGES_FILE.read_text(encoding="utf-8"))

    chunks: list[dict] = []
    for page in pages:
        raw_path = page.get("raw_path") or ""
        if not raw_path or not Path(raw_path).exists():
            continue

        html = Path(raw_path).read_text(encoding="utf-8")
        for section, parts in sections_from_html(html).items():
            text = "\n".join(parts).strip()
            if not text:
                continue

            # Very short key-value facts are valid answers.
            if len(text.split()) < 4 and "|" not in text and ":" not in text:
                continue

            for piece in split_text(text):
                chunks.append(
                    {
                        "chunk_id": hashlib.sha1(
                            f"{page['url']}|{section}|{piece}".encode("utf-8")
                        ).hexdigest()[:16],
                        "source_url": page["url"],
                        "page_title": page["title"],
                        "section": section,
                        "text": piece,
                        "embed_text": f"{page['title']} › {section}\n{piece}",
                        "fetched_at": page["fetched_at"],
                    }
                )
    return chunks


def main() -> None:
    rows = build_chunks()
    CHUNKS_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"[chunk] {len(rows)} chunks")


if __name__ == "__main__":
    main()
```

### Output

`data/chunks.jsonl`, one JSON object per line:

```json
{
  "chunk_id": "3f9a1c2b7d4e5f60",
  "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
  "page_title": "HDFC Large Cap Fund Direct Growth",
  "section": "Fund Details › Expense Ratio",
  "text": "Expense ratio | 0.62%",
  "embed_text": "HDFC Large Cap Fund Direct Growth › Fund Details › Expense Ratio\nExpense ratio | 0.62%",
  "fetched_at": "2026-11-05T10:15:00Z"
}
```

**Check:** every successful page contributes at least one chunk, chunks map to exactly one URL and section, and tables stay intact.

---

## 4. Embed the Chunks

- Model: `sentence-transformers/all-MiniLM-L6-v2` (**384 dimensions**).
- Embed `embed_text` (title + section + text), not `text`.
- Normalize vectors for cosine similarity.
- Keep row order aligned with `chunks.jsonl`.

### `app/embed.py`

```python
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import CONFIG, DATA

CHUNKS_FILE = DATA / "chunks.jsonl"
EMBEDDINGS_FILE = DATA / "embeddings.npy"
ID_MAP_FILE = DATA / "id_map.json"


def main() -> None:
    chunks = [
        json.loads(line)
        for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not chunks:
        raise SystemExit("No chunks found. Run `python -m app.chunk` first.")

    model_name = CONFIG["embedding"]["model"]
    model = SentenceTransformer(model_name)
    vectors = model.encode(
        [c["embed_text"] for c in chunks],
        batch_size=CONFIG["embedding"]["batch_size"],
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    np.save(EMBEDDINGS_FILE, vectors)
    ID_MAP_FILE.write_text(
        json.dumps(
            {
                "model": model_name,
                "dimension": int(vectors.shape[1]),
                "count": len(chunks),
                "ids": [c["chunk_id"] for c in chunks],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[embed] {len(chunks)} vectors | dim={vectors.shape[1]}")


if __name__ == "__main__":
    main()
```

### Output

- `data/embeddings.npy` — shape `(chunks, 384)`
- `data/id_map.json` — model, dimension, count, and ordered chunk IDs

**Check:** `vectors.shape[0] == len(chunks)`, all values finite, row norms ≈ 1.0.

---

## 5. Store Data in the Vector DB

Use ChromaDB persistent storage. Store chunk text and citation metadata alongside each vector so retrieval can return a citation without a second lookup.

### `app/index.py`

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import numpy as np

from app.config import CONFIG, DATA

CHUNKS_FILE = DATA / "chunks.jsonl"
EMBEDDINGS_FILE = DATA / "embeddings.npy"
MANIFEST_FILE = DATA / "manifest.json"


def build_index(chunks: list[dict], vectors: np.ndarray, persist_path: Path, collection_name: str):
    if not chunks:
        raise ValueError("No chunks to index. Run the chunk and embed steps first.")
    client = chromadb.PersistentClient(path=str(persist_path))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )

    ids = [c["chunk_id"] for c in chunks]
    collection.upsert(
        ids=ids,
        embeddings=vectors.tolist(),
        documents=[c["text"] for c in chunks],
        metadatas=[
            {
                "source_url": c["source_url"],
                "page_title": c["page_title"],
                "section": c["section"],
                "fetched_at": c["fetched_at"],
            }
            for c in chunks
        ],
    )

    # Remove vectors left over from a previous run.
    stale = set(collection.get(include=[])["ids"]) - set(ids)
    if stale:
        collection.delete(ids=list(stale))

    return collection


def main() -> None:
    chunks = [
        json.loads(line)
        for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    vectors = np.load(EMBEDDINGS_FILE)
    if len(chunks) != len(vectors):
        raise SystemExit("Chunk/vector count mismatch. Re-run embed.")

    collection = build_index(
        chunks,
        vectors,
        DATA / "chroma",
        CONFIG["vector_db"]["collection"],
    )

    manifest = {
        "ingested_at": datetime.now(timezone.utc).date().isoformat(),
        "collection": CONFIG["vector_db"]["collection"],
        "embedding_model": CONFIG["embedding"]["model"],
        "count": collection.count(),
        "pages": sorted({c["source_url"] for c in chunks}),
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[index] collection={manifest['collection']} | count={manifest['count']}")


if __name__ == "__main__":
    main()
```

### Output

- `data/chroma/` — persistent collection
- `data/manifest.json` — ingest date, model, count, page URLs

`ingested_at` supplies the `Last updated from sources:` line.

**Check:** collection count equals chunk count; metadata includes `source_url`, `section`, and `fetched_at`; re-running removes stale IDs.

---

## 6. Retrieval Logic and UI

### 6.1 Order of operations

```
question
  → PII guard (reject; no retrieval, no prompt, no stored query)
  → intent guard (refuse advice/performance)
  → detect scheme (for page filtering)
  → embed query
  → Chroma top-k
  → Groq generation from retrieved context
  → validate citation + sentence count
  → UI
```

### 6.2 Guardrails

`app/guardrails.py`:

```python
import re

PII_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone": r"(?:\+91[\s-]?)?[6-9]\d{9}\b",
    "pan": r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b",
    "aadhaar": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "account": r"\b(?:account|a/c|acct)\s*(?:number|no\.?)?\s*[:#-]?\s*\d{9,18}\b",
    "otp": r"\b(?:otp|one[\s-]?time\s?password)\b.{0,20}\b\d{4,8}\b",
}

ADVICE = (
    "should i", "should we", "buy", "sell", "hold", "recommend",
    "better", "best", "worst", "worth it", "good", "bad", "safe",
    "risky", "suitable", "invest in", "portfolio", "allocate",
    "suggest", "advice", "which fund", "compare", "switch", "redeem",
)

PERFORMANCE = (
    "return", "returns", "cagr", "xirr", "profit", "loss",
    "performance", "outperform", "beat the market", "will it give",
    "will this", "will give", "expected return", "future value",
)

AMC_URL = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"

SCHEMES = [
    # Statement / capital-gains questions belong to the AMC page.
    (
        AMC_URL,
        ("capital gain", "capital gains", "statement", "account statement"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        ("elss", "tax saver", "lock-in", "lock in", "lockin"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        ("large cap", "large-cap"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
        ("flexi cap", "flexi", "equity fund"),
    ),
    (
        "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        ("mid cap", "mid-cap"),
    ),
    # Generic AMC aliases come last so scheme names win.
    (AMC_URL, ("hdfc mutual fund", "hdfc mf", "amc")),
]


def _contains(term: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def has_pii(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in PII_PATTERNS.values())


def intent(text: str) -> str:
    q = " ".join(text.lower().split())
    if any(_contains(t, q) for t in PERFORMANCE):
        return "performance"
    if any(_contains(t, q) for t in ADVICE):
        return "advice"
    return "factual"


def detect_scheme(query: str) -> str | None:
    q = " ".join(query.lower().split())
    for url, aliases in SCHEMES:
        if any(_contains(alias, q) for alias in aliases):
            return url
    return None
```

- **PII:** return a privacy refusal. Do not retrieve, prompt, or store the raw query.
- **Advice/performance:** return a facts-only refusal citing a supplied URL.
- **Never** quote or log the PII value.
- **No comparisons:** comparison and "which is better" questions are refused before retrieval.

### 6.3 Retrieval

`app/retrieve.py`:

```python
import chromadb
from sentence_transformers import SentenceTransformer

from app.config import CONFIG, DATA
from app.guardrails import detect_scheme

_model = None
_collection = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(CONFIG["embedding"]["model"])
    return _model


def get_collection():
    global _collection
    if _collection is None:
        try:
            client = chromadb.PersistentClient(path=str(DATA / "chroma"))
            _collection = client.get_collection(
                name=CONFIG["vector_db"]["collection"],
                embedding_function=None,
            )
        except Exception as exc:
            raise RuntimeError(
                "Vector store not built. Run `python -m app.index` first."
            ) from exc
    return _collection


def best_per_section(rows: list[dict]) -> list[dict]:
    """Keep the highest-scoring chunk per (source_url, section)."""
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["source_url"], row["section"])
        if key not in best or row["score"] > best[key]["score"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: (-r["score"], r["chunk_id"]))


def retrieve(query: str) -> list[dict]:
    vector = get_model().encode([query], normalize_embeddings=True)[0].tolist()
    collection = get_collection()

    scheme = detect_scheme(query)
    where = {"source_url": scheme} if scheme else None
    result = collection.query(
        query_embeddings=[vector],
        n_results=CONFIG["retrieval"]["over_fetch"],
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    # A scheme filter can be too narrow; retry once across all five pages.
    if scheme and not result["ids"][0]:
        result = collection.query(
            query_embeddings=[vector],
            n_results=CONFIG["retrieval"]["over_fetch"],
            include=["documents", "metadatas", "distances"],
        )

    rows: list[dict] = []
    for i, chunk_id in enumerate(result["ids"][0]):
        score = min(1.0, max(0.0, 1.0 - float(result["distances"][0][i])))
        if score < CONFIG["retrieval"]["min_score"]:
            continue
        meta = result["metadatas"][0][i]
        rows.append(
            {
                "chunk_id": chunk_id,
                "text": result["documents"][0][i],
                "score": round(max(0.0, score), 4),
                "source_url": meta["source_url"],
                "page_title": meta["page_title"],
                "section": meta["section"],
            }
        )

    return best_per_section(rows)[: CONFIG["retrieval"]["top_k"]]
```

- Query embedding uses the **same model** as ingestion.
- Chroma cosine distance is converted with `score = 1 - distance`.
- Results below `min_score` are dropped and duplicates are collapsed per section.
- If a scheme filter returns nothing, retrieval retries across all five pages.

### 6.4 Generation and citation enforcement

`app/generate.py`:

```python
import json
import os
import re

from app.config import CONFIG

BANNED = (
    "recommend", "guaranteed", "guarantee", "best fund", "will give",
    "outperform", "beat the market", "sure shot", "risk-free", "assured return",
)


def _client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set in .env")
    from groq import Groq

    return Groq(api_key=key)


def build_context(rows: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] source_url: {r['source_url']}\n"
        f"section: {r['section']}\n{r['text']}"
        for i, r in enumerate(rows, 1)
    )


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object in model response")
    return json.loads(text[start : end + 1])


def clean_body(text: str) -> str:
    """Remove URLs/source lines and cap the factual body at 3 sentences."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?im)^\s*(source|last updated from sources)\s*:.*$", "", text)
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:3]).strip()


def fallback_answer(rows: list[dict]) -> dict:
    body = clean_body(rows[0]["text"]) if rows else ""
    if not body:
        body = "That fact is not available in the scoped official pages."
    return {"answer": body, "citation_url": rows[0]["source_url"] if rows else ""}


def generate(question: str, rows: list[dict]) -> dict:
    model = CONFIG["llm"]["model"].strip()
    if not model:
        raise RuntimeError("GROQ_MODEL is not set in .env")

    prompt = f"""You are a facts-only mutual fund FAQ assistant.
Use ONLY the context below. Do not use outside knowledge.
Answer the exact fact asked, in at most 3 sentences.
Never give advice, recommendations, opinions, comparisons, or return predictions.
If the context does not contain the answer, say it is not available in the scoped official pages.
Do not put URLs in the answer.
Return JSON only: {{"answer": "...", "citation_url": "..."}}.
citation_url must be one of the context source URLs.

Context:
{build_context(rows)}

Question: {question}"""

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": CONFIG["llm"]["temperature"],
        "max_tokens": CONFIG["llm"]["max_tokens"],
    }

    try:
        response = _client().chat.completions.create(
            **kwargs, response_format={"type": "json_object"}
        )
    except Exception as exc:
        # Some Groq models do not support JSON mode; retry once without it.
        if "response_format" not in str(exc).lower() and "json" not in str(exc).lower():
            raise
        response = _client().chat.completions.create(**kwargs)

    data = _parse_json(response.choices[0].message.content or "")
    answer = str(data.get("answer", "")).strip()
    if not answer:
        raise ValueError("Empty answer from model")

    allowed = {r["source_url"].rstrip("/") for r in rows}
    citation = str(data.get("citation_url", "")).strip().rstrip("/")
    if citation not in allowed:
        citation = rows[0]["source_url"]

    return {
        "answer": answer,
        "citation_url": citation,
        "prompt": prompt,
        "raw_llm_response": response.choices[0].message.content or "",
    }
```

The API layer does the final wrapping:

```python
answer = clean_body(body)
if not answer or any(term in answer.lower() for term in BANNED):
    answer = fallback_answer(rows)["answer"]

message = (
    f"{answer}\n\nSource: {citation}\n"
    f"Last updated from sources: {manifest['ingested_at']}"
)
```

This guarantees **exactly one URL** in every response.

### 6.5 FastAPI API

`app/main.py`:

```python
import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import CONFIG, DATA, MANIFEST, ROOT
from app.generate import BANNED, clean_body, fallback_answer, generate
from app.guardrails import AMC_URL, detect_scheme, has_pii, intent
from app.retrieve import retrieve

app = FastAPI(title="HDFC MF FAQ Assistant")
app.mount("/static", StaticFiles(directory=str(ROOT / "ui")), name="static")

REFUSAL_ADVICE = (
    "I can only share factual scheme information and can't offer investment advice. "
    "You can review the official page linked below."
)
REFUSAL_PERFORMANCE = (
    "I can't compare, predict, or compute returns. "
    "For official scheme facts, review the page linked below."
)
REFUSAL_PII = (
    "I can't accept or store personal information such as PAN, Aadhaar, account numbers, "
    "OTPs, emails, or phone numbers. You can review the official page linked below."
)
NOT_FOUND = (
    "That fact is not available in the scoped official pages. "
    "You can review the page linked below."
)


class Ask(BaseModel):
    query: str


def manifest() -> dict:
    if not MANIFEST.exists():
        raise HTTPException(500, "Index not built. Run `python -m app.index`.")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def final(body: str, url: str, refusal: bool = False) -> dict:
    m = manifest()
    return {
        "answer": (
            f"{body}\n\nSource: {url}\n"
            f"Last updated from sources: {m['ingested_at']}"
        ),
        "citation_url": url,
        "updated_at": m["ingested_at"],
        "refusal": refusal,
    }


def write_trace(
    trace_id: str,
    query: str | None,
    kind: str,
    rows: list[dict],
    out: dict,
    *,
    prompt: str = "",
    raw_llm_response: str = "",
) -> None:
    folder = DATA / "traces"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "trace_id": trace_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intent": kind,
        "retrieved": [
            {
                "chunk_id": r["chunk_id"],
                "score": r["score"],
                "source_url": r["source_url"],
                "section": r["section"],
            }
            for r in rows
        ],
        "prompt": prompt,
        "raw_llm_response": raw_llm_response,
        "answer": out["answer"],
        "citation_url": out["citation_url"],
        "refusal": out["refusal"],
        "model": CONFIG["llm"]["model"] or None,
    }
    # PII queries are stored without the raw query.
    if query is not None:
        payload["query"] = query
    (folder / f"{trace_id}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@app.post("/api/ask")
def ask(req: Ask):
    q = " ".join(req.query.split())
    if not q or len(q) > 500:
        raise HTTPException(400, "Question must be 1–500 characters.")

    trace_id = "q_" + uuid.uuid4().hex[:12]

    # 1. PII: no retrieval, no prompt, no raw query stored.
    if has_pii(q):
        out = final(REFUSAL_PII, AMC_URL, refusal=True)
        write_trace(trace_id, None, "pii", [], out)
        return {**out, "trace_id": trace_id, "retrieved": []}

    # 2. Advice/performance: refuse before retrieval.
    kind = intent(q)
    if kind in ("advice", "performance"):
        url = detect_scheme(q) or AMC_URL
        body = REFUSAL_ADVICE if kind == "advice" else REFUSAL_PERFORMANCE
        out = final(body, url, refusal=True)
        write_trace(trace_id, q, kind, [], out)
        return {**out, "trace_id": trace_id, "retrieved": []}

    # 3. Retrieval.
    try:
        rows = retrieve(q)
    except RuntimeError as exc:
        # Vector store missing or unreadable.
        raise HTTPException(503, "Run `python -m app.index` first.") from exc
    if not rows:
        url = detect_scheme(q) or AMC_URL
        out = final(NOT_FOUND, url, refusal=True)
        write_trace(trace_id, q, "factual", [], out)
        return {**out, "trace_id": trace_id, "retrieved": []}

    # 4. Generation with deterministic fallback.
    try:
        result = generate(q, rows)
        body = clean_body(result["answer"])
        citation = result["citation_url"]
    except Exception:
        result = fallback_answer(rows)
        body = clean_body(result["answer"])
        citation = result["citation_url"]

    if not body or any(term in body.lower() for term in BANNED):
        body = clean_body(fallback_answer(rows)["answer"])
    if not body:
        body = NOT_FOUND
    if citation not in {r["source_url"] for r in rows}:
        citation = rows[0]["source_url"]

    out = final(body, citation)
    write_trace(
        trace_id,
        q,
        "factual",
        rows,
        out,
        prompt=result.get("prompt", ""),
        raw_llm_response=result.get("raw_llm_response", ""),
    )
    return {
        **out,
        "trace_id": trace_id,
        "retrieved": [
            {
                "chunk_id": r["chunk_id"],
                "score": r["score"],
                "source_url": r["source_url"],
                "section": r["section"],
            }
            for r in rows
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(str(ROOT / "ui" / "index.html"))
```

### 6.6 UI

`ui/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HDFC MF FAQ</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; }
    h1 { margin-bottom: 4px; }
    .muted { color: #666; font-size: 0.9rem; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
    .chips button { padding: 8px 12px; border: 1px solid #ccc; border-radius: 999px; background: #fff; cursor: pointer; }
    form { display: flex; gap: 8px; }
    input { flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 6px; }
    button[type="submit"] { padding: 10px 18px; }
    #answer { margin-top: 24px; line-height: 1.5; }
    #answer a { word-break: break-all; }
    #trace { background: #f6f6f6; padding: 12px; overflow: auto; font-size: 0.85rem; }
    table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
    th, td { text-align: left; border-bottom: 1px solid #ddd; padding: 6px; }
    .note { margin-top: 32px; }
  </style>
</head>
<body>
  <main>
    <h1>HDFC Mutual Fund FAQ</h1>
    <p>Ask factual questions about the scoped HDFC Mutual Fund schemes.</p>

    <div class="chips">
      <button class="example">What is the expense ratio of HDFC Large Cap Fund?</button>
      <button class="example">What is the ELSS lock-in period?</button>
      <button class="example">How do I download my capital gains statement?</button>
    </div>

    <form id="form">
      <input id="query" maxlength="500" placeholder="Ask a factual question…" autocomplete="off" />
      <button type="submit">Ask</button>
    </form>

    <section id="answer" aria-live="polite"></section>

    <details id="trace-panel" hidden>
      <summary>Show retrieval details</summary>
      <pre id="trace"></pre>
    </details>

    <p class="note"><strong>Facts-only. No investment advice.</strong></p>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

`ui/app.js`:

```javascript
const examples = [
  "What is the expense ratio of HDFC Large Cap Fund?",
  "What is the ELSS lock-in period?",
  "How do I download my capital gains statement?",
];

document.querySelectorAll(".example").forEach((button, i) => {
  button.addEventListener("click", () => ask(examples[i]));
});

document.getElementById("form").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = document.getElementById("query").value.trim();
  if (query) ask(query);
});

function render(data) {
  const box = document.getElementById("answer");
  box.replaceChildren();

  const body = document.createElement("p");
  body.textContent = data.answer.split("\n\nSource:")[0];
  box.appendChild(body);

  const source = document.createElement("p");
  source.className = "muted";
  source.append("Source: ");
  const link = document.createElement("a");
  link.href = data.citation_url;
  link.textContent = data.citation_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  source.appendChild(link);
  box.appendChild(source);

  const updated = document.createElement("p");
  updated.className = "muted";
  updated.textContent = `Last updated from sources: ${data.updated_at}`;
  box.appendChild(updated);

  const panel = document.getElementById("trace-panel");
  const trace = document.getElementById("trace");
  if (data.retrieved && data.retrieved.length) {
    const table = document.createElement("table");
    const head = document.createElement("tr");
    ["Chunk", "Score", "Section", "Source"].forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      head.appendChild(th);
    });
    table.appendChild(head);

    data.retrieved.forEach((row) => {
      const tr = document.createElement("tr");
      [row.chunk_id, row.score.toFixed(3), row.section, row.source_url].forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });

    trace.replaceChildren(table);
    panel.hidden = false;
    panel.open = false;
  } else {
    trace.replaceChildren();
    panel.hidden = true;
  }
}

async function ask(query) {
  const box = document.getElementById("answer");
  box.textContent = "Looking up the official pages…";
  document.getElementById("trace-panel").hidden = true;

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error("Request failed");
    render(await res.json());
  } catch {
    box.textContent = "Something went wrong. Please try a factual question.";
  }
}
```

Run:

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

**UI requirements met:** welcome line, three clickable examples, input + Ask button, answer with exactly one clickable source, last-updated line, retrieval details panel, and **“Facts-only. No investment advice.”**

---

## 7. Edge Cases and Guardrail Tests

### 7.1 Required behavior

| Case | Expected behavior |
|---|---|
| “Should I buy/sell/hold…?” | Polite refusal, no advice, one supplied URL. |
| “Which fund is better / compare…” | Refusal; comparisons are out of scope. |
| “What returns / CAGR / best fund?” | Refusal; no performance claims. |
| PAN, Aadhaar, account number, OTP, email, phone | Privacy refusal; no retrieval, no LLM, no raw query stored. |
| Fact not present in the five pages | “Not available in scoped official pages” + supplied URL. |
| No chunk above score threshold | Same “not available” response. |
| Question names a scheme | Filter Chroma to that page; retry unfiltered if empty. |
| Question names no scheme | Search all five pages and return top chunks. |
| ELSS lock-in / tax saver | Route to ELSS page. |
| Statement / capital gains | Route to AMC page. |
| Multiple schemes in one question | No comparison answer; refused or answered from the first match only. |
| LLM timeout / rate limit | Deterministic fallback from the top retrieved chunk. |
| LLM invalid JSON | Parse failure → fallback from the top retrieved chunk. |
| LLM returns multiple URLs | Strip all body URLs; append exactly one `Source:` line. |
| LLM returns more than 3 sentences | Truncate the factual body to 3 sentences. |
| LLM invents a citation | Replace with the top retrieved chunk’s URL. |
| Empty or over-500-character question | HTTP 400 with guidance. |
| Page fetch fails | Record `status: 0` and continue; do not crash. |
| Page contains internal links | Ignore them; never request them. |
| Duplicate chunks in results | Keep the highest score per `(source_url, section)`. |
| Prompt-injection text on a page | Treat as untrusted context; output validation still enforces citation and advice rules. |

### 7.2 `tests/test_guardrails.py`

```python
from app.guardrails import (
    AMC_URL,
    detect_scheme,
    has_pii,
    intent,
)

ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
LARGE_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
MID_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"


def test_pii_rejected():
    assert has_pii("My PAN is ABCDE1234F")
    assert has_pii("email me at test@example.com")
    assert has_pii("call me on 9876543210")
    assert has_pii("aadhaar 1234 5678 9012")
    assert has_pii("account number 123456789012")
    assert has_pii("OTP is 123456")


def test_normal_factual_query_is_not_pii():
    assert not has_pii("What is the ELSS lock-in period?")
    assert not has_pii("What is the expense ratio of HDFC Mid Cap Fund?")


def test_normal_factual_query_passes_intent_guard():
    assert intent("What is the ELSS lock-in period?") == "factual"
    assert intent("What is the expense ratio of HDFC Large Cap Fund?") == "factual"


def test_advice_refused():
    assert intent("Should I buy HDFC Mid Cap Fund?") == "advice"
    assert intent("Which fund is better?") == "advice"
    assert intent("Is this fund good for me?") == "advice"


def test_performance_refused():
    assert intent("What returns will this fund give?") == "performance"
    assert intent("What is the 3-year CAGR?") == "performance"


def test_statement_routes_to_amc():
    assert detect_scheme("How do I download my capital gains statement?") == AMC_URL


def test_elss_lock_in_routes_to_elss():
    assert detect_scheme("What is the ELSS lock-in period?") == ELSS_URL


def test_scheme_names_beat_generic_amc_alias():
    assert detect_scheme("HDFC Mutual Fund large cap expense ratio") == LARGE_URL
    assert detect_scheme("HDFC mid cap exit load") == MID_URL
```

### 7.3 `tests/test_chunk.py`

```python
from app.chunk import sections_from_html, split_text


def test_table_is_preserved():
    html = (
        "<main><h2>Facts</h2>"
        "<table><tr><td>Exit load</td><td>1%</td></tr></table></main>"
    )
    sections = sections_from_html(html)
    assert "Facts" in sections
    assert "Exit load | 1%" in "\n".join(sections["Facts"])


def test_heading_path_is_kept():
    html = (
        "<main><h2>Fund Details</h2><h3>Expense Ratio</h3>"
        "<p>Expense ratio | 0.62%</p></main>"
    )
    sections = sections_from_html(html)
    assert any("Fund Details" in key and "Expense Ratio" in key for key in sections)


def test_split_text_keeps_sentences_and_limit():
    text = " ".join(f"Sentence {i} is here." for i in range(40))
    pieces = split_text(text, max_words=20)
    assert all(len(piece.split()) <= 20 for piece in pieces)
    assert " ".join(pieces).count("Sentence") == 40
```

### 7.4 `tests/test_scrape.py`

```python
import httpx

from app import scrape
from app.config import URLS


class FakeResponse:
    status_code = 200
    text = "<html><head><title>Page</title></head><body><main><p>Fact</p></main></body></html>"

    def raise_for_status(self):
        return None


def test_only_the_five_urls_are_requested(monkeypatch, tmp_path):
    called = []

    def fake_fetch(url):
        called.append(url)
        return FakeResponse()

    monkeypatch.setattr(scrape.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scrape, "fetch", fake_fetch)
    pages = scrape.fetch_all(raw_dir=tmp_path)

    assert len(pages) == 5
    assert called == URLS
    assert set(called) == set(URLS)


def test_internal_links_are_never_followed(monkeypatch, tmp_path):
    class LinkResponse(FakeResponse):
        text = (
            "<html><body><main>"
            "<a href='https://groww.in/some-internal-page'>Internal</a>"
            "<p>Fact</p></main></body></html>"
        )

    called = []

    def fake_fetch(url):
        called.append(url)
        return LinkResponse()

    monkeypatch.setattr(scrape.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scrape, "fetch", fake_fetch)
    scrape.fetch_all(raw_dir=tmp_path)

    assert "https://groww.in/some-internal-page" not in called


def test_clean_text_removes_navigation():
    html = (
        "<html><body><nav>Menu</nav><main><p>Expense ratio | 0.62%</p></main>"
        "<script>alert(1)</script></body></html>"
    )
    text = scrape.clean_text(html)
    assert "Expense ratio | 0.62%" in text
    assert "Menu" not in text
```

### 7.5 `tests/test_retrieval.py`

```python
from app.retrieve import best_per_section


def row(chunk_id, section, score, url="https://example.com/a"):
    return {
        "chunk_id": chunk_id,
        "section": section,
        "score": score,
        "source_url": url,
    }


def test_best_per_section_keeps_highest_score():
    rows = [
        row("a", "Expense Ratio", 0.40),
        row("b", "Expense Ratio", 0.60),
        row("c", "Exit Load", 0.30),
    ]
    result = best_per_section(rows)
    assert [r["chunk_id"] for r in result] == ["b", "c"]


def test_scores_are_sorted_descending():
    rows = [row("a", "A", 0.2), row("b", "B", 0.9)]
    assert [r["chunk_id"] for r in best_per_section(rows)] == ["b", "a"]
```

### 7.6 `tests/test_api.py`

```python
import pytest
from fastapi.testclient import TestClient

from app import main

ROWS = [
    {
        "chunk_id": "abc123",
        "text": "Expense ratio | 0.62%. This is the total expense ratio.",
        "score": 0.82,
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "page_title": "HDFC Large Cap Fund Direct Growth",
        "section": "Expense Ratio",
    }
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "manifest", lambda: {"ingested_at": "2026-11-05"})
    monkeypatch.setattr(main, "write_trace", lambda *args, **kwargs: None)
    return TestClient(main.app)


def test_pii_is_refused_without_retrieval(client, monkeypatch):
    def boom(_query):
        raise AssertionError("retrieval must not run for PII")

    monkeypatch.setattr(main, "retrieve", boom)
    res = client.post("/api/ask", json={"query": "My PAN is ABCDE1234F"})
    assert res.status_code == 200
    assert res.json()["refusal"] is True


def test_advice_is_refused(client, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda _q: ROWS)
    res = client.post("/api/ask", json={"query": "Should I buy HDFC Mid Cap?"})
    assert res.json()["refusal"] is True


def test_no_context_returns_not_found(client, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda _q: [])
    res = client.post("/api/ask", json={"query": "What is the AUM?"})
    assert res.json()["refusal"] is True


def test_missing_index_returns_503(client, monkeypatch):
    def missing(_query):
        raise RuntimeError("Vector store not built.")

    monkeypatch.setattr(main, "retrieve", missing)
    res = client.post(
        "/api/ask",
        json={"query": "What is the expense ratio of HDFC Large Cap Fund?"},
    )
    assert res.status_code == 503
    assert "app.index" in res.json()["detail"]


def test_answer_has_exactly_one_url_and_three_sentences(client, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda _q: ROWS)
    monkeypatch.setattr(
        main,
        "generate",
        lambda _q, _rows: {
            "answer": (
                "One. Two. Three. Four. "
                "https://evil.example/other-link"
            ),
            "citation_url": ROWS[0]["source_url"],
        },
    )
    res = client.post(
        "/api/ask",
        json={"query": "What is the expense ratio of HDFC Large Cap Fund?"},
    )
    data = res.json()
    assert data["answer"].count("http") == 1
    body = data["answer"].split("\n\nSource:")[0]
    assert len([s for s in body.split(".") if s.strip()]) <= 3
    assert "Source:" in data["answer"]
    assert "Last updated from sources: 2026-11-05" in data["answer"]


def test_empty_query_rejected(client):
    assert client.post("/api/ask", json={"query": "   "}).status_code == 400
```

### 7.7 Manual demo checks

1. Ask all three example questions → cited answers.
2. Ask “Should I buy HDFC Mid Cap?” → refusal.
3. Ask “Which fund gives the best returns?” → refusal.
4. Enter a PAN/email/phone → privacy refusal; confirm it does not appear in `data/traces/` or logs.
5. Ask a fact not on the pages → “not available” + supplied link.
6. Confirm every answer has exactly one `Source:` URL and `Last updated from sources:`.
7. Confirm no answer exceeds three sentences.
8. Open “Show retrieval details” → chunk IDs, scores, sections, source URLs.
9. Inspect `data/` → raw pages, chunks, embeddings, Chroma, manifest, traces.

---

## 8. Run Order and Artifacts

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python -m app.scrape
python -m app.chunk
python -m app.embed
python -m app.index

uvicorn app.main:app --reload
```

| Step | Command | Artifact |
|---|---|---|
| Scrape | `python -m app.scrape` | `data/raw/`, `data/pages.json` |
| Chunk | `python -m app.chunk` | `data/chunks.jsonl` |
| Embed | `python -m app.embed` | `data/embeddings.npy`, `data/id_map.json` |
| Store | `python -m app.index` | `data/chroma/`, `data/manifest.json` |
| Serve | `uvicorn app.main:app` | UI at `localhost:8000` |
| Query | `POST /api/ask` | `data/traces/<trace_id>.json` |

Expected console output:

```
[scrape] 5 pages | 5 ok | 0 failed
[chunk] 87 chunks
[embed] 87 vectors | dim=384
[index] collection=hdfc_faq | count=87
```

---

## 9. Definition of Done

- [ ] Directory structure and config are in place.
- [ ] Exactly five supplied URLs are scraped; no internal links are followed.
- [ ] Chunks preserve headings, tables, and short key-value facts.
- [ ] All chunks are embedded with MiniLM and stored in Chroma.
- [ ] Retrieval uses the same model and collection as ingestion.
- [ ] Every answer has exactly one supplied source URL and a last-updated date.
- [ ] Answers are at most three sentences.
- [ ] Advice, comparison, return, and PII inputs are refused safely.
- [ ] No PII is stored or logged; PII traces omit the query.
- [ ] UI includes the welcome line, three examples, retrieval details, and the facts-only note.
- [ ] Guardrail tests pass (`pytest tests/`).
- [ ] Demo link or ≤3-minute video is ready.
