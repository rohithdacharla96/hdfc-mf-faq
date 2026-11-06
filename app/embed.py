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
