import pytest
from fastapi.testclient import TestClient

from app import main

ROWS = [
    {
        "chunk_id": "abc123",
        "text": "Expense ratio | 0.62%. This is the total expense ratio.",
        "score": 0.82,
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "page_title": "HDFC Large Cap Fund Direct Growth",
        "section": "Expense Ratio",
    }
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "manifest", lambda: {"ingested_at": "2026-11-05"})
    monkeypatch.setattr(main, "write_trace", lambda *args, **kwargs: None)
    return TestClient(main.app)


def test_pii_is_refused_without_retrieval(client, monkeypatch):
    def boom(_query):
        raise AssertionError("retrieval must not run for PII")

    monkeypatch.setattr(main, "retrieve", boom)
    res = client.post("/api/ask", json={"query": "My PAN is ABCDE1234F"})
    assert res.status_code == 200
    assert res.json()["refusal"] is True


def test_advice_is_refused(client, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda _q: ROWS)
    res = client.post("/api/ask", json={"query": "Should I buy HDFC Mid Cap?"})
    assert res.json()["refusal"] is True


def test_no_context_returns_not_found(client, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda _q: [])
    res = client.post("/api/ask", json={"query": "What is the AUM?"})
    assert res.json()["refusal"] is True


def test_missing_index_returns_503(client, monkeypatch):
    def missing(_query):
        raise RuntimeError("Vector store not built.")

    monkeypatch.setattr(main, "retrieve", missing)
    res = client.post(
        "/api/ask",
        json={"query": "What is the expense ratio of HDFC Large Cap Fund?"},
    )
    assert res.status_code == 503
    assert "app.index" in res.json()["detail"]


def test_answer_has_exactly_one_url_and_three_sentences(client, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda _q: ROWS)
    monkeypatch.setattr(
        main,
        "generate",
        lambda _q, _rows: {
            "answer": (
                "One. Two. Three. Four. "
                "https://evil.example/other-link"
            ),
            "citation_url": ROWS[0]["source_url"],
        },
    )
    res = client.post(
        "/api/ask",
        json={"query": "What is the expense ratio of HDFC Large Cap Fund?"},
    )
    data = res.json()
    assert data["answer"].count("http") == 1
    body = data["answer"].split("\n\nSource:")[0]
    assert len([s for s in body.split(".") if s.strip()]) <= 3
    assert "Source:" in data["answer"]
    assert "Last updated from sources: 2026-11-05" in data["answer"]


def test_statement_query_returns_not_found_without_retrieval(client, monkeypatch):
    def boom(_query):
        raise AssertionError("retrieval must not run for statement queries")

    monkeypatch.setattr(main, "retrieve", boom)
    res = client.post(
        "/api/ask",
        json={"query": "How do I download my capital gains statement?"},
    )
    data = res.json()
    assert res.status_code == 200
    assert data["refusal"] is True
    assert data["retrieved"] == []
    assert "not available in the scoped official pages" in data["answer"]
    assert data["citation_url"] == main.AMC_URL


def test_off_topic_query_returns_not_found_without_retrieval(client, monkeypatch):
    def boom(_query):
        raise AssertionError("retrieval must not run for out-of-scope queries")

    monkeypatch.setattr(main, "retrieve", boom)
    res = client.post(
        "/api/ask",
        json={"query": "Who regulates mutual funds in India?"},
    )
    data = res.json()
    assert res.status_code == 200
    assert data["refusal"] is True
    assert data["retrieved"] == []
    assert "not available in the scoped official pages" in data["answer"]


def test_empty_query_rejected(client):
    assert client.post("/api/ask", json={"query": "   "}).status_code == 400
