"""Shared ranking helpers used by both retrieval backends."""


def best_per_section(rows: list[dict]) -> list[dict]:
    """Keep the highest-scoring chunk per (source_url, section)."""
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["source_url"], row["section"])
        if key not in best or row["score"] > best[key]["score"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: (-r["score"], r["chunk_id"]))
