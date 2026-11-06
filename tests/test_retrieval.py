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
