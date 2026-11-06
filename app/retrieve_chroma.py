"""Full retrieval backend: sentence-transformers embeddings + ChromaDB.

Used for local development and any host with enough RAM for PyTorch. The
lightweight deployment backend lives in ``app.retrieve_lite``.
"""

import chromadb
from sentence_transformers import SentenceTransformer

from app.config import CONFIG, DATA
from app.guardrails import SECTION_FOR_FACT, detect_fact, detect_scheme
from app.ranking import best_per_section

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
            client = chromadb.PersistentClient(
                path=str(DATA / "chroma"),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            _collection = client.get_collection(
                name=CONFIG["vector_db"]["collection"],
                embedding_function=None,
            )
        except Exception as exc:
            raise RuntimeError(
                "Vector store not built. Run `python -m app.index` first."
            ) from exc
    return _collection


def retrieve(query: str) -> list[dict]:
    vector = get_model().encode([query], normalize_embeddings=True)[0].tolist()
    collection = get_collection()
    n_results = CONFIG["retrieval"]["over_fetch"]

    scheme = detect_scheme(query)
    fact = detect_fact(query)
    section = (
        f"Fund Details › {SECTION_FOR_FACT[fact]}"
        if fact and fact in SECTION_FOR_FACT
        else None
    )

    def run(where):
        return collection.query(
            query_embeddings=[vector],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    # Prefer the exact structured-fact section for this scheme.
    filters = []
    if scheme:
        filters.append({"source_url": scheme})
    if section:
        filters.append({"section": section})
    where = {"$and": filters} if len(filters) > 1 else (filters[0] if filters else None)
    result = run(where)

    # Narrow filters can miss; relax step by step, then go corpus-wide.
    fallbacks = []
    if section and scheme:
        fallbacks.append({"source_url": scheme})
    fallbacks.extend([None])
    i = 0
    while not result["ids"][0] and i < len(fallbacks):
        result = run(fallbacks[i])
        i += 1

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
