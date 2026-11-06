#!/usr/bin/env python3
"""Create (or update) the Render free web service and wait for it to go live.

Requires ``RENDER_API_KEY`` in ``.env``. The repository must already be pushed
to GitHub (see ``deploy_github.py``).

Usage:
    python deploy_render.py
    python deploy_render.py --no-wait
    python deploy_render.py --repo-name hdfc-mf-faq --timeout 1200
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
API = "https://api.render.com/v1"
GITHUB_OWNER = "rohithdacharla96"
BUILD = (
    "pip install --upgrade pip "
    "&& pip install -r requirements-render.txt "
    "&& python scripts/fetch_model.py"
)
START = "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"
LIVE = {"live"}
FAILED = {"build_failed", "canceled", "pre_deploy_failed", "deactivated"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="hdfc-mf-faq", help="Render service name")
    parser.add_argument("--repo", default=f"https://github.com/{GITHUB_OWNER}/hdfc-mf-faq")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--region", default="oregon")
    parser.add_argument("--no-wait", action="store_true", help="Create and exit")
    parser.add_argument("--timeout", type=int, default=1200, help="Build wait timeout (seconds)")
    args = parser.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    key = (os.getenv("RENDER_API_KEY") or "").strip()
    if not key:
        print("RENDER_API_KEY is missing from .env", file=sys.stderr)
        return 2

    client = httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=60,
    )

    owners = client.get("/owners")
    owners.raise_for_status()
    owner_id = owners.json()[0]["owner"]["id"]
    print(f"[auth] workspace {owner_id}")

    services = client.get("/services", params={"limit": 100})
    services.raise_for_status()
    existing = None
    for row in services.json():
        service = row.get("service", row)
        if service.get("name") == args.name:
            existing = service
            break

    payload = {
        "type": "web_service",
        "name": args.name,
        "ownerId": owner_id,
        "repo": args.repo,
        "branch": args.branch,
        "autoDeployTrigger": "commit",
        "envVars": [
            {"key": "PYTHON_VERSION", "value": "3.11.9"},
            {"key": "RETRIEVAL_BACKEND", "value": "lite"},
            {"key": "GROQ_MODEL", "value": "llama-3.3-70b-versatile"},
        ],
        "serviceDetails": {
            "runtime": "python",
            "plan": "free",
            "region": args.region,
            "healthCheckPath": "/health",
            "envSpecificDetails": {"buildCommand": BUILD, "startCommand": START},
        },
    }

    if existing:
        service_id = existing["id"]
        print(f"[service] reusing {service_id}")
        response = client.patch(
            f"/services/{service_id}",
            json={
                "serviceDetails": {
                    "plan": "free",
                    "healthCheckPath": "/health",
                    "envSpecificDetails": {"buildCommand": BUILD, "startCommand": START},
                }
            },
        )
        if response.status_code >= 400:
            print(f"[service] update failed ({response.status_code}): {response.text[:400]}", file=sys.stderr)
            return 1
        deploy = client.post(f"/services/{service_id}/deploys", json={"clearCache": "do_not_clear"})
        if deploy.status_code >= 400:
            print(f"[deploy] trigger failed ({deploy.status_code}): {deploy.text[:400]}", file=sys.stderr)
            return 1
        deploy_id = deploy.json().get("id")
    else:
        response = client.post("/services", json=payload)
        if response.status_code >= 400:
            print(f"[service] creation failed ({response.status_code}): {response.text[:800]}", file=sys.stderr)
            return 1
        data = response.json()
        service_id = data["service"]["id"]
        deploy_id = data.get("deployId")
        print(f"[service] created {service_id}")

    service = client.get(f"/services/{service_id}").json()
    details = service.get("serviceDetails", {}) or {}
    url = details.get("url") or f"https://{service.get('slug')}.onrender.com"
    print(f"[service] dashboard: {service.get('dashboardUrl')}")
    print(f"[service] url: {url}")

    if args.no_wait:
        return 0

    print("[build] waiting for the first deploy (3-6 minutes)")
    started = time.time()
    last = ""
    while time.time() - started < args.timeout:
        try:
            deploys = client.get(f"/services/{service_id}/deploys", params={"limit": 1}).json()
            status = deploys[0]["deploy"]["status"] if deploys else "pending"
        except Exception as exc:
            print(f"[build] waiting ({type(exc).__name__})")
            time.sleep(15)
            continue

        if status != last:
            print(f"[build] {status}")
            last = status
        if status in LIVE:
            print("\n[done] service is live")
            print(f"  {url}")
            print(f"  Verify: python verify_deploy.py --url {url} --wait 300")
            return 0
        if status in FAILED:
            print(f"[build] failed: {status}", file=sys.stderr)
            print(f"[logs] {service.get('dashboardUrl')}", file=sys.stderr)
            return 1
        time.sleep(15)

    print("[build] timed out waiting for the deploy", file=sys.stderr)
    print(f"[logs] {service.get('dashboardUrl')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
