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
    client = chromadb.PersistentClient(
        path=str(persist_path),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )
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
