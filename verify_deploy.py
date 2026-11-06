#!/usr/bin/env python3
"""Verify a deployed HDFC FAQ assistant over HTTP.

Usage:
    python verify_deploy.py
    python verify_deploy.py --url https://rohithdacharla-hdfc-mf-faq.hf.space
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

import httpx

DEFAULT_URL = os.getenv("PUBLIC_APP_URL", "").rstrip("/")

SOURCES = {
    "amc": "https://groww.in/mutual-funds/amc/hdfc-mutual-funds",
    "large": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    "flexi": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    "elss": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    "mid": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
}

CASES = [
    {
        "query": "What is the expense ratio of HDFC Large Cap Fund?",
        "source": "large",
        "contains": ["1.02%"],
    },
    {
        "query": "What is the exit load of HDFC Large Cap Fund?",
        "source": "large",
        "contains": ["1%"],
    },
    {
        "query": "What is the minimum SIP for HDFC Large Cap Fund?",
        "source": "large",
        "contains": ["100"],
    },
    {
        "query": "What is the benchmark of HDFC Large Cap Fund?",
        "source": "large",
        "contains": ["NIFTY 100"],
    },
    {
        "query": "What is the riskometer of HDFC Large Cap Fund?",
        "source": "large",
        "contains": ["Very High"],
    },
    {
        "query": "What is the ELSS lock-in period?",
        "source": "elss",
        "contains": ["3 year"],
    },
    {
        "query": "What is the exit load of HDFC ELSS Tax Saver Fund?",
        "source": "elss",
        "contains": ["NIL", "Nil", "nil"],
    },
    {
        "query": "What is the expense ratio of HDFC Flexi Cap Fund?",
        "source": "flexi",
        "contains": ["0.75%"],
    },
    {
        "query": "What is the benchmark of HDFC Mid Cap Fund?",
        "source": "mid",
        "contains": ["NIFTY Midcap 150"],
    },
    {
        "query": "What is the expense ratio of HDFC Mid Cap Fund?",
        "source": "mid",
        "contains": ["0.74%"],
    },
]

REFUSALS = [
    "Should I buy HDFC Large Cap Fund?",
    "What returns did HDFC Mid Cap Fund give last year?",
    "How do I download my capital gains statement?",
    "Who won the 2022 FIFA World Cup?",
    "My PAN is ABCDE1234F. What is the expense ratio?",
]


def wait_for_health(base: str, wait_seconds: int) -> bool:
    if wait_seconds <= 0:
        return True
    deadline = time.time() + wait_seconds
    print(f"[wait] checking {base}/health (up to {wait_seconds}s)")
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base}/health", timeout=20)
            if response.status_code == 200 and response.json().get("status") == "ok":
                print("[wait] healthy")
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def sentence_count(body: str) -> int:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", body.strip()) if p.strip()]
    return len(parts)


def check_answer(case: dict, data: dict) -> list[str]:
    errors: list[str] = []
    answer = str(data.get("answer", ""))
    citation = str(data.get("citation_url", ""))
    expected_source = SOURCES[case["source"]]

    urls = re.findall(r"https?://\S+", answer)
    if len(urls) != 1:
        errors.append(f"expected exactly 1 URL in answer, found {len(urls)}")
    if citation != expected_source:
        errors.append(f"citation mismatch: {citation}")
    if urls and urls[0].rstrip(").,") != expected_source:
        errors.append(f"answer URL mismatch: {urls[0]}")
    if "Last updated from sources:" not in answer:
        errors.append("missing last-updated line")

    body = answer.split("\n\nSource:")[0]
    if sentence_count(body) > 3:
        errors.append(f"body has {sentence_count(body)} sentences")

    if data.get("refusal"):
        errors.append("unexpected refusal")
    for needle in case.get("contains", []):
        if needle.lower() not in body.lower():
            errors.append(f"missing expected text: {needle!r}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL of the deployed app")
    parser.add_argument("--wait", type=int, default=180, help="Seconds to wait for /health")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    if not base:
        print(
            "Pass --url or set PUBLIC_APP_URL, e.g. "
            "python verify_deploy.py --url https://hdfc-mf-faq.onrender.com",
            file=sys.stderr,
        )
        return 2
    print(f"[url] {base}")

    if not wait_for_health(base, args.wait):
        print("[fail] the app did not become healthy", file=sys.stderr)
        return 1

    failures = 0
    try:
        page = httpx.get(f"{base}/", timeout=args.timeout)
        page.raise_for_status()
        html = page.text
        checks = {
            "welcome/disclaimer": "Facts-only. No investment advice." in html,
            "three examples": html.count('class="example-card"') == 3,
            "chat history UI": "/static/app.js?v=" in html,
        }
        for label, ok in checks.items():
            print(f"[ui] {label}: {'ok' if ok else 'FAIL'}")
            if not ok:
                failures += 1
    except Exception as exc:
        print(f"[fail] UI request failed: {exc}", file=sys.stderr)
        failures += 1

    print("\n[factual checks]")
    for case in CASES:
        try:
            response = httpx.post(
                f"{base}/api/ask",
                json={"query": case["query"]},
                timeout=args.timeout,
            )
            response.raise_for_status()
            data = response.json()
            errors = check_answer(case, data)
        except Exception as exc:
            errors = [f"request failed: {exc}"]
            data = {}

        status = "ok" if not errors else "FAIL"
        print(f"  [{status}] {case['query']}")
        if errors:
            failures += 1
            for error in errors:
                print(f"        - {error}")
            print(f"        answer: {data.get('answer', '')!r}")

    print("\n[refusal checks]")
    for query in REFUSALS:
        try:
            response = httpx.post(f"{base}/api/ask", json={"query": query}, timeout=args.timeout)
            response.raise_for_status()
            data = response.json()
            errors = []
            if not data.get("refusal"):
                errors.append("expected refusal=true")
            answer = str(data.get("answer", ""))
            if "Last updated from sources:" not in answer:
                errors.append("missing last-updated line")
            if "ABCDE1234F" in answer:
                errors.append("PII echoed in answer")
        except Exception as exc:
            errors = [f"request failed: {exc}"]

        status = "ok" if not errors else "FAIL"
        print(f"  [{status}] {query}")
        if errors:
            failures += 1
            for error in errors:
                print(f"        - {error}")

    print(f"\n[done] failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
