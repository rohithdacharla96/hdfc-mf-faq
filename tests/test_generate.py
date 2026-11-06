import json

from app import generate

ROWS = [
    {
        "chunk_id": "abc123",
        "text": "Expense ratio | 1.02%",
        "score": 0.91,
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "page_title": "HDFC Large Cap Fund Direct Growth",
        "section": "Fund Details › Expense ratio",
    },
    {
        "chunk_id": "def456",
        "text": "Exit load | Exit load of 1% if redeemed within 1 year.",
        "score": 0.80,
        "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        "page_title": "HDFC Mid Cap Fund Direct Growth",
        "section": "Fund Details › Exit load",
    },
]


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **_kwargs):
        return FakeResponse(self.content)


class FakeChat:
    def __init__(self, content):
        self.completions = FakeCompletions(content)


class FakeClient:
    def __init__(self, content):
        self.chat = FakeChat(content)


def test_generate_parses_json_and_keeps_allowed_citation(monkeypatch):
    payload = json.dumps(
        {
            "answer": "The expense ratio is 1.02%.",
            "citation_url": ROWS[0]["source_url"],
        }
    )
    monkeypatch.setattr(generate, "_client", lambda: FakeClient(payload))

    result = generate.generate("What is the expense ratio?", ROWS)

    assert result["answer"] == "The expense ratio is 1.02%."
    assert result["citation_url"] == ROWS[0]["source_url"]
    assert "Context:" in result["prompt"]


def test_generate_replaces_invented_citation(monkeypatch):
    payload = json.dumps(
        {
            "answer": "The expense ratio is 1.02%.",
            "citation_url": "https://evil.example/invented",
        }
    )
    monkeypatch.setattr(generate, "_client", lambda: FakeClient(payload))

    result = generate.generate("What is the expense ratio?", ROWS)

    assert result["citation_url"] == ROWS[0]["source_url"]


def test_generate_accepts_fenced_json(monkeypatch):
    payload = "```json\n" + json.dumps(
        {
            "answer": "Exit load is Nil.",
            "citation_url": ROWS[1]["source_url"],
        }
    ) + "\n```"
    monkeypatch.setattr(generate, "_client", lambda: FakeClient(payload))

    result = generate.generate("What is the exit load?", ROWS)

    assert result["answer"] == "Exit load is Nil."
    assert result["citation_url"] == ROWS[1]["source_url"]


def test_clean_body_strips_urls_and_caps_at_three_sentences():
    text = "One. Two. Three. Four. https://evil.example/x"
    body = generate.clean_body(text)

    assert "http" not in body
    assert body == "One. Two. Three."


def test_fallback_formats_structured_fact():
    result = generate.fallback_answer(ROWS)

    assert result["answer"] == "Expense ratio: 1.02%."
    assert result["citation_url"] == ROWS[0]["source_url"]
