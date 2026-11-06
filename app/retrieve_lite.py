"""Lightweight retrieval backend: ONNX MiniLM + a NumPy cosine index.

This exists so the app can run on hosts with 512 MB of RAM (Render free tier)
where PyTorch and ChromaDB do not fit. It uses the same ``all-MiniLM-L6-v2``
weights as the full backend, exported to ONNX, so query vectors and ranking are
identical to ``app.retrieve_chroma`` (verified to ~1e-7).

The index is the prebuilt ``data/embeddings.npy`` matrix, one row per chunk in
``data/chunks.jsonl``. With 92 chunks a flat NumPy index is exact and costs
almost no memory.
"""

import json
import os
from pathlib import Path

import numpy as np

from app.config import CONFIG, DATA
from app.guardrails import SECTION_FOR_FACT, detect_fact, detect_scheme
from app.ranking import best_per_section

MODEL_DIR = Path(os.getenv("ONNX_MODEL_DIR", str(DATA / "model")))
MAX_TOKENS = 256

_session = None
_tokenizer = None
_chunks: list[dict] | None = None
_embeddings: np.ndarray | None = None
_sources: np.ndarray | None = None
_sections: np.ndarray | None = None


def get_session():
    global _session
    if _session is None:
        import onnxruntime as ort

        path = MODEL_DIR / "model.onnx"
        if not path.exists():
            raise RuntimeError(
                f"ONNX embedding model not found at {path}. "
                "Set ONNX_MODEL_DIR or download onnx/model.onnx and tokenizer.json."
            )
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        _session = ort.InferenceSession(
            str(path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
    return _session


def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        from tokenizers import Tokenizer

        path = MODEL_DIR / "tokenizer.json"
        if not path.exists():
            raise RuntimeError(
                f"Tokenizer not found at {path}. Set ONNX_MODEL_DIR or download tokenizer.json."
            )
        _tokenizer = Tokenizer.from_file(str(path))
        _tokenizer.enable_truncation(max_length=MAX_TOKENS)
    return _tokenizer


def encode(texts: list[str]) -> np.ndarray:
    """Mean-pooled, L2-normalised MiniLM embeddings (same as sentence-transformers)."""
    tokenizer = get_tokenizer()
    tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
    encoded = tokenizer.encode_batch(texts)

    ids = np.array([e.ids for e in encoded], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)

    session = get_session()
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in {i.name for i in session.get_inputs()}:
        feed["token_type_ids"] = np.zeros_like(ids)

    hidden = session.run(None, feed)[0]
    weights = mask[..., None].astype(np.float32)
    pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)


def get_index() -> tuple[list[dict], np.ndarray]:
    global _chunks, _embeddings, _sources, _sections
    if _chunks is None or _embeddings is None:
        chunks_file = DATA / "chunks.jsonl"
        embeddings_file = DATA / "embeddings.npy"
        if not chunks_file.exists() or not embeddings_file.exists():
            raise RuntimeError(
                "Vector store not built. Run `python -m app.index` first."
            )
        _chunks = [
            json.loads(line)
            for line in chunks_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        _embeddings = np.load(embeddings_file).astype(np.float32)
        if _embeddings.shape[0] != len(_chunks):
            raise RuntimeError(
                "Embeddings and chunks are out of sync; rebuild with `python -m app.index`."
            )
        _sources = np.array([c["source_url"] for c in _chunks])
        _sections = np.array([c["section"] for c in _chunks])
    return _chunks, _embeddings


def _top(indices: np.ndarray, scores: np.ndarray, n_results: int) -> list[tuple[int, float]]:
    if len(indices) == 0:
        return []
    order = indices[np.argsort(-scores[indices], kind="stable")][:n_results]
    return [(int(i), float(scores[i])) for i in order]


def retrieve(query: str) -> list[dict]:
    vector = encode([query])[0]
    chunks, embeddings = get_index()
    scores = embeddings @ vector
    n_results = int(CONFIG["retrieval"]["over_fetch"])

    scheme = detect_scheme(query)
    fact = detect_fact(query)
    section = (
        f"Fund Details › {SECTION_FOR_FACT[fact]}"
        if fact and fact in SECTION_FOR_FACT
        else None
    )

    everything = np.arange(len(chunks))

    def run(source_url: str | None, section_name: str | None) -> list[tuple[int, float]]:
        indices = everything
        if source_url is not None:
            indices = indices[_sources[indices] == source_url]
        if section_name is not None:
            indices = indices[_sections[indices] == section_name]
        return _top(indices, scores, n_results)

    # Mirror the Chroma backend's filter relaxation order.
    attempts: list[tuple[str | None, str | None]] = []
    if scheme or section:
        attempts.append((scheme, section))
    if section and scheme:
        attempts.append((scheme, None))
    attempts.append((None, None))

    result: list[tuple[int, float]] = []
    for source_url, section_name in attempts:
        result = run(source_url, section_name)
        if result:
            break

    rows: list[dict] = []
    for index, raw_score in result:
        score = min(1.0, max(0.0, raw_score))
        if score < CONFIG["retrieval"]["min_score"]:
            continue
        chunk = chunks[index]
        rows.append(
            {
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "score": round(max(0.0, score), 4),
                "source_url": chunk["source_url"],
                "page_title": chunk["page_title"],
                "section": chunk["section"],
            }
        )

    return best_per_section(rows)[: CONFIG["retrieval"]["top_k"]]
