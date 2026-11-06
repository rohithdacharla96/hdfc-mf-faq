# Deployment

The app can run on two very different footprints:

| Path | Cost | Runtime | RAM |
|---|---|---|---|
| **Render — native Python, free** (recommended) | $0 | FastAPI + ONNX MiniLM + flat NumPy index | ~220 MB |
| **Hugging Face Spaces — Docker** | $9/mo PRO | FastAPI + PyTorch + ChromaDB | ~700 MB |

Hugging Face no longer allows Docker or Gradio Spaces on the free `cpu-basic`
hardware; a PRO subscription is required. Render's free web service needs no
credit card and fits the lightweight backend comfortably.

Both backends use the same `sentence-transformers/all-MiniLM-L6-v2` weights and
the same prebuilt 92-chunk index. Retrieval parity was verified across 20
questions (identical chunk IDs and scores to four decimal places).

---

## Option A — Render (free, recommended)

### What you need

- A GitHub account (free).
- A Render account (free, sign up with GitHub).
- Nothing else. No credit card.

### 1. Push the project to GitHub

The repository is already prepared locally with a `render.yaml` blueprint.

```powershell
# One-time, if the remote is not configured yet
git remote add origin https://github.com/<your-username>/hdfc-mf-faq.git
git push -u origin main
```

The repo is safe to make public: `.env` is gitignored, and only the app, UI,
config, and small index files (`manifest.json`, `chunks.jsonl`,
`embeddings.npy`) are committed. The 86 MB ONNX model is downloaded during the
Render build by `scripts/fetch_model.py`, not stored in git.

### 2. Create the service

1. Sign in to <https://dashboard.render.com>.
2. Click **New → Blueprint**.
3. Connect the GitHub repository you just pushed.
4. Render reads `render.yaml`, shows one free web service named `hdfc-mf-faq`,
   and asks for `GROQ_API_KEY`. Leave it blank if you do not have a Groq key —
   the app then uses the deterministic extractive fallback.
5. Click **Apply** (or **Create**).

Render installs `requirements-render.txt`, downloads the ONNX model, and starts
the app. The first deploy takes about 3–5 minutes.

### 3. Get the URL

The service is published at:

```text
https://hdfc-mf-faq.onrender.com
```

If the name is taken, Render appends a suffix; the exact URL is shown at the top
of the service page.

### 4. Verify

```powershell
.\.venv\Scripts\python.exe verify_deploy.py --url https://hdfc-mf-faq.onrender.com --wait 300
```

The script checks the UI, ten factual answers, and five refusal cases (advice,
performance, statement download, out-of-scope, and PII).

### Free-tier behaviour

- The instance **spins down after 15 minutes of inactivity**. The next request
  takes roughly 30–60 seconds to wake it, then answers normally.
- 512 MB RAM, 0.1 CPU. The lite backend peaks around 222 MB, and query embedding
  takes a few milliseconds.
- The filesystem is ephemeral. Answer traces under `data/traces/` disappear on
  restart; the app does not depend on them.
- 750 instance-hours per month is plenty for a single always-available service.

### Updating

Push to the connected branch. Render rebuilds and deploys automatically. To
change the model, re-run ingestion locally, commit the updated `data/*.npy` and
`data/chunks.jsonl`, and push.

---

## Option B — Hugging Face Spaces (PRO)

Hugging Face is a good choice if you already have PRO: 16 GB RAM, no cold
starts, and the full PyTorch + Chroma stack.

1. Confirm the account has PRO at <https://huggingface.co/pro>.
2. Put a **Write** token in `.env`:

   ```dotenv
   HF_TOKEN=hf_...
   ```

3. Deploy:

   ```powershell
   .\.venv\Scripts\python.exe deploy_hf.py
   ```

The script creates `https://huggingface.co/spaces/<user>/hdfc-mf-faq`, uploads a
clean staging folder (no `.env`, raw HTML, traces, or tests), sets
`GROQ_MODEL`/`GROQ_API_KEY`, waits for the Docker build, and prints the public
`*.hf.space` URL.

Useful flags:

```powershell
.\.venv\Scripts\python.exe deploy_hf.py --dry-run    # stage only
.\.venv\Scripts\python.exe deploy_hf.py --no-wait    # upload and exit
.\.venv\Scripts\python.exe deploy_hf.py --space my-hdfc-faq
```

Verify with `verify_deploy.py --url https://<user>-hdfc-mf-faq.hf.space`.

---

## Option C — Any Docker host

The same `Dockerfile` works on Railway, Fly.io, a VPS, or a home server.

```bash
docker build -t hdfc-faq .
docker run --rm -p 7860:7860 \
  -e GROQ_API_KEY=... \
  -e GROQ_MODEL=llama-3.3-70b-versatile \
  hdfc-faq
```

Do **not** use a 512 MB container with the full Docker image: PyTorch alone
will not fit. Use the Render path for 512 MB hosts, or give the container at
least 1 GB.

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `RETRIEVAL_BACKEND` | No | auto | `chroma` or `lite`. Unset auto-detects. |
| `ONNX_MODEL_DIR` | No | `data/model` | Where `model.onnx` and `tokenizer.json` live. |
| `GROQ_API_KEY` | No | empty | Enables Groq generation; otherwise deterministic fallback. |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model ID. |
| `PORT` | No | `7860` (Docker) / `$PORT` (Render) | Listen port. |
| `HF_TOKEN` | HF only | empty | Hugging Face write token for `deploy_hf.py`. |

`config.yaml` remains the source of truth for the five URLs, chunking, and
retrieval settings. `${GROQ_MODEL}` is expanded from the environment.

---

## How the Render runtime stays small

- `requirements-render.txt` omits PyTorch, sentence-transformers, ChromaDB, the
  scraper, and test dependencies.
- `app/retrieve.py` dispatches to `app/retrieve_chroma.py` (full stack) or
  `app/retrieve_lite.py` (ONNX + NumPy). Local development keeps using Chroma.
- `data/embeddings.npy` is the same 92 × 384 matrix the Chroma collection holds,
  so no re-embedding is needed at runtime.
- `scripts/fetch_model.py` downloads the ONNX export during the build.

---

## Security notes

- Both deployments are public and unauthenticated. Add a rate limiter before
  exposing a paid LLM key at scale.
- Chat history lives in the visitor's browser `localStorage`; conversations are
  not stored server-side.
- PII questions are traced without the raw query, but other traces contain the
  generated answer. On Render these files are ephemeral and never served over
  HTTP.
- `GROQ_API_KEY` and `HF_TOKEN` are never committed. `.env` is gitignored and
  excluded from the Hugging Face upload.
- Only the five scoped Groww pages are used; the scraper never follows links
  inside them.

---

## Rollback

- **Render:** open the service → **Deploys** → choose a previous deploy →
  **Redeploy**. Or revert the commit and push.
- **Hugging Face:** Space page → **Files** → **History** → revert to the previous
  commit.
