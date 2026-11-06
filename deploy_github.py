#!/usr/bin/env python3
"""Create a GitHub repository and push this project to it.

Run after adding a classic GitHub token with the ``repo`` scope to ``.env``:

    GITHUB_TOKEN=ghp_...

Usage:
    python deploy_github.py
    python deploy_github.py --repo hdfc-mf-faq --private
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
API = "https://api.github.com"


def request(token: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "hdfc-faq-deploy",
    }
    try:
        response = httpx.request(
            method, f"{API}{path}", headers=headers, json=payload, timeout=60
        )
    except httpx.HTTPError as exc:
        return 0, {"message": f"{type(exc).__name__}: {exc}"}
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


def git(*args: str, secret: str = "") -> None:
    command = ["git", *args]
    shown = " ".join(a.replace(secret, "***") if secret else a for a in command)
    print(f"[git] {shown}")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(command, cwd=ROOT, check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="hdfc-mf-faq", help="Repository name (default: hdfc-mf-faq)")
    parser.add_argument("--private", action="store_true", help="Create a private repository")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        print(
            "GITHUB_TOKEN is missing.\n"
            "1. Open https://github.com/settings/tokens\n"
            "2. Generate a classic token with the 'repo' scope.\n"
            "3. Add it to .env as:  GITHUB_TOKEN=ghp_...\n"
            "4. Re-run this script.",
            file=sys.stderr,
        )
        return 2

    status, user = request(token, "GET", "/user")
    if status != 200:
        print(f"[auth] GitHub rejected the token ({status}): {user.get('message')}", file=sys.stderr)
        return 2
    login = user["login"]
    print(f"[auth] authenticated as {login}")

    status, repo = request(
        token,
        "POST",
        "/user/repos",
        {
            "name": args.repo,
            "description": "Facts-only HDFC Mutual Fund FAQ assistant (RAG)",
            "private": args.private,
            "auto_init": False,
        },
    )
    if status == 201:
        print(f"[repo] created {repo['full_name']}")
    elif status == 422:
        print(f"[repo] {login}/{args.repo} already exists; reusing it")
    else:
        print(f"[repo] creation failed ({status}): {repo.get('message')}", file=sys.stderr)
        return 1

    clean = f"https://github.com/{login}/{args.repo}.git"
    push_url = f"https://x-access-token:{token}@github.com/{login}/{args.repo}.git"

    try:
        git("remote", "remove", "origin")
    except subprocess.CalledProcessError:
        pass
    git("remote", "add", "origin", clean)
    git("push", push_url, "main", secret=token)

    # Best-effort upstream tracking (works for public repos without credentials).
    try:
        git("fetch", "origin")
        git("branch", "--set-upstream-to=origin/main", "main")
    except subprocess.CalledProcessError:
        pass

    print("\n[done] repository published")
    print(f"  Repo: {clean[:-4]}")
    print(f"  Render: https://dashboard.render.com/blueprint/new?repo={clean[:-4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
