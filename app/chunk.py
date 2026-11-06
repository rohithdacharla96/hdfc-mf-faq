import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.config import CONFIG, DATA

PAGES_FILE = DATA / "pages.json"
CHUNKS_FILE = DATA / "chunks.jsonl"
MAX_WORDS = CONFIG["chunking"]["max_words"]

HEADINGS = {"h1", "h2", "h3", "h4"}
BLOCKS = ["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "table", "blockquote", "div"]
CONTAINERS = ["div", "p", "li", "dt", "dd", "table", "blockquote", "ul", "ol", "section", "article"]

# Groww puts site chrome in class-named divs, not <footer>/<nav> tags.
CHROME = re.compile(
    r"footer|topnav|navbar|nav-bar|sidenav|side-nav|drawer|breadcrumb"
    r"|seonavigation|layout-sidebar|dropdown|loggedout",
    re.IGNORECASE,
)

# No performance, return, ranking, or comparison content may enter the corpus.
PERFORMANCE_SECTION = re.compile(
    r"return|ranking|compare similar|performance|nav history|peer"
    r"|closer look|list of hdfc|from other amcs",
    re.IGNORECASE,
)


def strip_chrome(soup: BeautifulSoup) -> None:
    # Groww's page <header> holds the price/return strip, not article content.
    for tag in soup.find_all(
        ["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]
    ):
        tag.decompose()
    for tag in soup.find_all(True):
        if getattr(tag, "decomposed", False):
            continue
        klass = tag.get("class") or []
        if isinstance(klass, str):
            klass = [klass]
        marker = " ".join(klass) + " " + (tag.get("id") or "")
        if marker.strip() and CHROME.search(marker) and tag.find("h1") is None:
            tag.decompose()


def table_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def sections_from_html(html: str) -> dict[str, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    strip_chrome(soup)

    root = soup.find("main") or soup.find("article") or soup.body
    if root is None:
        return {}

    sections: dict[str, list[str]] = {"General": []}
    stack: list[str] = []
    current = "General"

    for el in root.find_all(BLOCKS):
        if el.find_parent("table") and el.name != "table":
            continue
        if el.name == "div" and el.find(CONTAINERS) is not None:
            # Skip structural divs; their leaf children carry the text.
            continue
        if el.name in HEADINGS:
            label = " ".join(el.get_text(" ", strip=True).split())
            if not label:
                continue
            level = int(el.name[1])
            stack = stack[: level - 1]
            stack.append(label)
            current = " › ".join(stack)
            sections.setdefault(current, [])
            continue
        text = (
            table_text(el)
            if el.name == "table"
            else " ".join(el.get_text(" ", strip=True).split())
        )
        if text:
            sections.setdefault(current, []).append(text)

    return {k: v for k, v in sections.items() if v}


def split_text(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """Split on sentence boundaries so facts are never cut mid-sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    buf: list[str] = []
    count = 0

    def flush() -> None:
        nonlocal buf, count
        if buf:
            pieces.append(" ".join(buf))
            buf, count = [], 0

    for sentence in sentences:
        words = len(sentence.split())
        if words > max_words:
            # Tables and nav dumps can be one "sentence"; hard-split on lines.
            flush()
            for unit in sentence.split("\n"):
                unit_words = unit.split()
                if not unit_words:
                    continue
                if len(unit_words) <= max_words:
                    if count + len(unit_words) > max_words:
                        flush()
                    buf.append(unit)
                    count += len(unit_words)
                else:
                    flush()
                    for i in range(0, len(unit_words), max_words):
                        pieces.append(" ".join(unit_words[i : i + max_words]))
            continue
        if buf and count + words > max_words:
            flush()
        buf.append(sentence)
        count += words

    flush()
    return [p for p in pieces if p.strip()]


def build_chunks(pages: list[dict] | None = None) -> list[dict]:
    if pages is None:
        pages = json.loads(PAGES_FILE.read_text(encoding="utf-8"))

    chunks: list[dict] = []
    for page in pages:
        # Structured facts from the page's own JSON data: one section per fact.
        for fact in page.get("facts") or []:
            section = " ".join(str(fact.get("section", "General")).split())
            text = " ".join(str(fact.get("text", "")).split())
            if not section or not text:
                continue
            for piece in split_text(text):
                chunks.append(
                    {
                        "chunk_id": hashlib.sha1(
                            f"{page['url']}|{section}|{piece}".encode("utf-8")
                        ).hexdigest()[:16],
                        "source_url": page["url"],
                        "page_title": page["title"],
                        "section": section,
                        "text": piece,
                        "embed_text": f"{page['title']} › {section}\n{piece}",
                        "fetched_at": page["fetched_at"],
                    }
                )

        raw_path = page.get("raw_path") or ""
        if not raw_path or not Path(raw_path).exists():
            continue

        html = Path(raw_path).read_text(encoding="utf-8")
        for section, parts in sections_from_html(html).items():
            # "General" is the page header/nav leftovers with return figures.
            if section == "General" or section.endswith(" › General"):
                continue
            # Keep returns/rankings/comparison tables out of the facts-only corpus.
            if PERFORMANCE_SECTION.search(section):
                continue
            text = "\n".join(parts).strip()
            if not text:
                continue

            # Very short key-value facts are valid answers.
            if len(text.split()) < 4 and "|" not in text and ":" not in text:
                continue

            for piece in split_text(text):
                chunks.append(
                    {
                        "chunk_id": hashlib.sha1(
                            f"{page['url']}|{section}|{piece}".encode("utf-8")
                        ).hexdigest()[:16],
                        "source_url": page["url"],
                        "page_title": page["title"],
                        "section": section,
                        "text": piece,
                        "embed_text": f"{page['title']} › {section}\n{piece}",
                        "fetched_at": page["fetched_at"],
                    }
                )
    return chunks


def main() -> None:
    rows = build_chunks()
    CHUNKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHUNKS_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"[chunk] {len(rows)} chunks")


if __name__ == "__main__":
    main()
