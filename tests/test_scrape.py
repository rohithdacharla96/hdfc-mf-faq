import httpx

from app import scrape
from app.config import URLS


class FakeResponse:
    status_code = 200
    text = "<html><head><title>Page</title></head><body><main><p>Fact</p></main></body></html>"

    def raise_for_status(self):
        return None


def test_only_the_five_urls_are_requested(monkeypatch, tmp_path):
    called = []

    def fake_fetch(url):
        called.append(url)
        return FakeResponse()

    monkeypatch.setattr(scrape.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scrape, "fetch", fake_fetch)
    pages = scrape.fetch_all(raw_dir=tmp_path)

    assert len(pages) == 5
    assert called == URLS
    assert set(called) == set(URLS)


def test_internal_links_are_never_followed(monkeypatch, tmp_path):
    class LinkResponse(FakeResponse):
        text = (
            "<html><body><main>"
            "<a href='https://groww.in/some-internal-page'>Internal</a>"
            "<p>Fact</p></main></body></html>"
        )

    called = []

    def fake_fetch(url):
        called.append(url)
        return LinkResponse()

    monkeypatch.setattr(scrape.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scrape, "fetch", fake_fetch)
    scrape.fetch_all(raw_dir=tmp_path)

    assert "https://groww.in/some-internal-page" not in called


def test_clean_text_removes_navigation():
    html = (
        "<html><body><nav>Menu</nav><main><p>Expense ratio | 0.62%</p></main>"
        "<script>alert(1)</script></body></html>"
    )
    text = scrape.clean_text(html)
    assert "Expense ratio | 0.62%" in text
    assert "Menu" not in text
