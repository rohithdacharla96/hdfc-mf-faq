import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import CONFIG, DATA, MANIFEST, ROOT
from app.generate import BANNED, clean_body, fallback_answer, generate
from app.guardrails import (
    AMC_URL,
    detect_scheme,
    has_pii,
    intent,
    is_scoped_query,
    is_statement_query,
)
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

    # 3. Statement/account questions are documented as out of scope.
    if is_statement_query(q):
        out = final(NOT_FOUND, AMC_URL, refusal=True)
        write_trace(trace_id, q, "statement", [], out)
        return {**out, "trace_id": trace_id, "retrieved": []}

    # 4. Questions unrelated to these five pages get an honest not-found.
    if not is_scoped_query(q):
        out = final(NOT_FOUND, AMC_URL, refusal=True)
        write_trace(trace_id, q, "out_of_scope", [], out)
        return {**out, "trace_id": trace_id, "retrieved": []}

    # 5. Retrieval.
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

    # 6. Generation with deterministic fallback.
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
