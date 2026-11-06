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
