"""Retrieval backend dispatcher.

``RETRIEVAL_BACKEND`` selects the implementation:

- ``chroma`` (default when available): sentence-transformers + ChromaDB.
- ``lite``: ONNX MiniLM + a flat NumPy cosine index (512 MB hosts).
- unset: prefer Chroma when its packages and index are present, else lite.

Both backends return identical ``retrieve(query)`` results.
"""

import importlib.util
import os

from app.config import DATA
from app.ranking import best_per_section

_FORCED = os.getenv("RETRIEVAL_BACKEND", "").strip().lower()


def _select() -> str:
    if _FORCED in {"lite", "onnx", "numpy"}:
        return "lite"
    if _FORCED in {"chroma", "vector_db"}:
        return "chroma"
    has_packages = (
        importlib.util.find_spec("chromadb") is not None
        and importlib.util.find_spec("sentence_transformers") is not None
    )
    if has_packages and (DATA / "chroma" / "chroma.sqlite3").exists():
        return "chroma"
    return "lite"


if _select() == "chroma":
    from app.retrieve_chroma import retrieve
else:
    from app.retrieve_lite import retrieve

__all__ = ["retrieve", "best_per_section"]
