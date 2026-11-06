#!/usr/bin/env python3
"""Download the ONNX MiniLM embedder used by the lightweight backend.

The full local stack uses sentence-transformers (PyTorch). Render's free 512 MB
instance cannot fit PyTorch, so it runs ``app.retrieve_lite`` with the same
weights exported to ONNX. This script fetches those two files at build time so
the git repository stays small.

Usage:
    python scripts/fetch_model.py
    python scripts/fetch_model.py --force
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.getenv("ONNX_MODEL_DIR", str(ROOT / "data" / "model")))

BASE = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"
FILES = {
    "model.onnx": ("onnx/model.onnx", 80_000_000),
    "tokenizer.json": ("tokenizer.json", 400_000),
}


def download(remote: str, dest: Path) -> None:
    url = f"{BASE}/{remote}"
    print(f"[fetch] {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "hdfc-faq-build/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as handle:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            handle.write(block)
    tmp.replace(dest)
    print(f"[fetch] saved {dest} ({dest.stat().st_size / 1048576:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for name, (remote, minimum) in FILES.items():
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size >= minimum and not args.force:
            print(f"[fetch] {dest} already present ({dest.stat().st_size / 1048576:.1f} MB)")
            continue
        try:
            download(remote, dest)
        except Exception as exc:
            print(f"[fetch] failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if dest.stat().st_size < minimum:
            print(f"[fetch] {dest} is unexpectedly small", file=sys.stderr)
            return 1

    print("[fetch] embedding model ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
