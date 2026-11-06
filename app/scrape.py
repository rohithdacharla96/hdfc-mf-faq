import hashlib
import json
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import CONFIG, DATA, URLS

RAW_DIR = DATA / "raw"
PAGES_FILE = DATA / "pages.json"

REMOVE = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form"}
# Groww renders most facts in <div> label/value pairs, so leaf divs are included.
BLOCKS = ["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "table", "blockquote", "div"]
CONTAINERS = ["div", "p", "li", "dt", "dd", "table", "blockquote", "ul", "ol", "section", "article"]


def _text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _fragment_text(fragment: str) -> str:
    soup = BeautifulSoup(fragment or "", "lxml")
    parts = [
        " ".join(el.get_text(" ", strip=True).split())
        for el in soup.find_all(["p", "li"])
    ]
    parts = [p for p in parts if p]
    if parts:
        return "\n".join(parts)
    return " ".join(soup.get_text(" ", strip=True).split())


def _next_data(html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError:
        return None


def _scheme_facts(mf: dict) -> list[dict]:
    facts: list[dict] = []

    def add(label: str, value, suffix: str = "") -> None:
        text = _text(value)
        if not text:
            return
        facts.append(
            {
                "section": f"Fund Details › {label}",
                "text": f"{label} | {text}{suffix}",
            }
        )

    category = " - ".join(
        part for part in (_text(mf.get("category")), _text(mf.get("sub_category"))) if part
    )
    add("Scheme name", mf.get("scheme_name"))
    add("Fund house", mf.get("fund_house"))
    add("Category", category)
    add("Expense ratio", mf.get("expense_ratio"), "%")
    add("Base expense ratio", mf.get("base_expense_ratio"), "%")
    add("Exit load", mf.get("exit_load"))
    add("Benchmark", mf.get("benchmark_name") or mf.get("benchmark"))
    add("Minimum SIP", mf.get("min_sip_investment"), " rupees")
    add("Minimum first investment", mf.get("min_investment_amount"), " rupees")
    add("Minimum additional investment", mf.get("mini_additional_investment"), " rupees")
    add("Minimum withdrawal", mf.get("min_withdrawal"), " rupees")

    lock = mf.get("lock_in") or {}
    lock_parts = [
        f"{lock[unit]} {unit}"
        for unit in ("years", "months", "days")
        if lock.get(unit)
    ]
    add("Lock-in period", " ".join(lock_parts) if lock_parts else "No lock-in")

    risk = _text(mf.get("nfo_risk")).replace("Riskometer", "").strip()
    meta_risk = re.search(r"Risk is ([A-Za-z ]+)", _text(mf.get("meta_desc")))
    if meta_risk:
        risk = meta_risk.group(1).strip()
    add("Riskometer", risk)

    add("Stamp duty", mf.get("stamp_duty"))
    add("Fund manager", mf.get("fund_manager"))
    add("Registrar", mf.get("registrar_agent"))
    if mf.get("aum") is not None:
        add("AUM", f"{float(mf['aum']):,.2f} crore")
    if mf.get("nav") is not None:
        nav = f"{float(mf['nav']):,.4f}"
        if mf.get("nav_date"):
            nav += f" as of {mf['nav_date']}"
        add("NAV", nav)
    add("Launch date", mf.get("launch_date"))

    options = []
    if mf.get("sip_allowed"):
        options.append("SIP")
    if mf.get("lumpsum_allowed"):
        options.append("lumpsum")
    add("Investment options", " and ".join(options))
    add("Scheme objective", mf.get("description"))
    return facts


def _walk_content_lists(node):
    """Yield every dict that carries a contentList, at any nesting depth."""
    if isinstance(node, dict):
        if isinstance(node.get("contentList"), list):
            yield node
            return
        for value in node.values():
            yield from _walk_content_lists(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_content_lists(value)


def _amc_facts(data) -> list[dict]:
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for holder in _walk_content_lists(data):
        for item in holder.get("contentList") or []:
            if not isinstance(item, dict):
                continue
            title = _text(item.get("title"))
            text = _fragment_text(item.get("content", ""))
            key = (title, text)
            if title and text and key not in seen:
                seen.add(key)
                facts.append(
                    {
                        "section": f"AMC Overview › {title}",
                        "text": text,
                    }
                )
    return facts


def extract_facts(html: str) -> list[dict]:
    data = _next_data(html)
    if not data:
        return []
    page_props = (data.get("props") or {}).get("pageProps") or {}
    scheme = page_props.get("mfServerSideData")
    if isinstance(scheme, dict):
        return _scheme_facts(scheme)
    amc = page_props.get("amcMainPageData")
    if isinstance(amc, (dict, list)):
        return _amc_facts(amc)
    return []


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
def fetch(url: str) -> httpx.Response:
    return httpx.get(
        url,
        timeout=CONFIG["sources"]["timeout_seconds"],
        follow_redirects=True,
        headers={"User-Agent": CONFIG["sources"]["user_agent"]},
    )


def clean_text(html: str) -> str:
    from app.chunk import strip_chrome

    soup = BeautifulSoup(html, "lxml")
    strip_chrome(soup)

    root = soup.find("main") or soup.find("article") or soup.body
    if root is None:
        return ""

    lines: list[str] = []
    for el in root.find_all(BLOCKS):
        if el.find_parent("table") and el.name != "table":
            continue
        if el.name == "div" and el.find(CONTAINERS) is not None:
            # Skip structural divs; their leaf children carry the text.
            continue
        if el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
        else:
            text = " ".join(el.get_text(" ", strip=True).split())
        if text:
            lines.append(text)
    return "\n".join(lines)


def fetch_all(raw_dir: Path = RAW_DIR) -> list[dict]:
    if len(URLS) != 5:
        raise ValueError("Only the five supplied URLs are allowed")

    raw_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []

    for i, url in enumerate(URLS):
        page_id = url.rstrip("/").split("/")[-1]
        raw_path = raw_dir / f"{page_id}.html"
        try:
            resp = fetch(url)
            resp.raise_for_status()
            html = resp.text
            raw_path.write_text(html, encoding="utf-8")
            soup = BeautifulSoup(html, "lxml")
            h1 = soup.find("h1")
            title = (
                " ".join(h1.get_text(" ", strip=True).split())
                if h1
                else (soup.title.get_text(strip=True) if soup.title else page_id)
            )
            pages.append(
                {
                    "url": url,
                    "page_id": page_id,
                    "title": title,
                    "status": resp.status_code,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "content_hash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                    "raw_path": str(raw_path),
                    "text": clean_text(html),
                    "facts": extract_facts(html),
                }
            )
        except Exception as exc:
            pages.append(
                {
                    "url": url,
                    "page_id": page_id,
                    "title": page_id,
                    "status": 0,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "content_hash": "",
                    "raw_path": str(raw_path) if raw_path.exists() else "",
                    "text": "",
                    "facts": [],
                    "error": type(exc).__name__,
                }
            )
        if i < len(URLS) - 1:
            time.sleep(CONFIG["sources"]["delay_seconds"])

    return pages


def main() -> None:
    pages = fetch_all()
    PAGES_FILE.write_text(
        json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ok = sum(1 for p in pages if p["status"] == 200)
    print(f"[scrape] {len(pages)} pages | {ok} ok | {len(pages) - ok} failed")


if __name__ == "__main__":
    main()
