#!/usr/bin/env python3
"""Deploy the HDFC MF FAQ assistant to a public Hugging Face Docker Space.

Usage:
    python deploy_hf.py                 # create/update the Space and wait
    python deploy_hf.py --no-wait       # upload and exit
    python deploy_hf.py --dry-run       # only build the upload staging folder

Authentication:
    Put a Hugging Face WRITE token in .env as:
        HF_TOKEN=hf_...
    or export HF_TOKEN in the shell. The token is never printed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
STAGE_PREFIX = "hdfc-hf-space-"

RUNTIME_FILES = (
    "config.yaml",
    "requirements.txt",
    "requirements-deploy.txt",
    "Dockerfile",
    ".dockerignore",
    "DISCLAIMER.md",
    "SOURCE_LIST.md",
    "SAMPLE_QA.md",
)

DATA_FILES = (
    "manifest.json",
    "chunks.jsonl",
    "pages.json",
    "id_map.json",
    "embeddings.npy",
)

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def build_stage() -> Path:
    """Create a clean folder containing exactly what the Space needs."""
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX))

    for folder in ("app", "ui"):
        src = ROOT / folder
        if not src.is_dir():
            raise SystemExit(f"Missing required folder: {src}")
        shutil.copytree(src, stage / folder, ignore=IGNORE)

    data_dir = stage / "data"
    data_dir.mkdir()
    chroma = ROOT / "data" / "chroma"
    if not (chroma / "chroma.sqlite3").exists():
        raise SystemExit("Missing data/chroma/chroma.sqlite3. Run the ingestion pipeline first.")
    shutil.copytree(chroma, data_dir / "chroma", ignore=IGNORE)

    for name in DATA_FILES:
        src = ROOT / "data" / name
        if src.exists():
            shutil.copy2(src, data_dir / name)

    for name in RUNTIME_FILES:
        src = ROOT / name
        if not src.exists():
            raise SystemExit(f"Missing required deployment file: {src}")
        shutil.copy2(src, stage / name)

    readme = ROOT / "deploy" / "huggingface" / "README.md"
    if not readme.exists():
        raise SystemExit(f"Missing Space README template: {readme}")
    (stage / "README.md").write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")

    if not (stage / "data" / "manifest.json").exists():
        raise SystemExit("Missing data/manifest.json after staging.")
    if not (stage / "app" / "main.py").exists():
        raise SystemExit("Missing app/main.py after staging.")

    return stage


def space_stage(api, repo_id: str, timeout_seconds: int) -> bool:
    from huggingface_hub._space_api import SpaceStage

    print("[build] waiting for the Space to become RUNNING (first build can take 5-15 minutes)")
    time.sleep(10)
    started = time.time()
    seen_build = False
    last = ""

    while time.time() - started < timeout_seconds:
        try:
            runtime = api.get_space_runtime(repo_id=repo_id)
            stage = runtime.stage
        except Exception as exc:  # transient API/network issue
            print(f"[build] waiting ({type(exc).__name__})")
            time.sleep(15)
            continue

        value = stage.value if hasattr(stage, "value") else str(stage)
        if value != last:
            print(f"[build] {value}")
            last = value

        if stage in (SpaceStage.BUILDING, SpaceStage.RUNNING_BUILDING):
            seen_build = True
        if stage == SpaceStage.RUNNING and (seen_build or time.time() - started > 90):
            return True
        if stage in (
            SpaceStage.BUILD_ERROR,
            SpaceStage.CONFIG_ERROR,
            SpaceStage.RUNTIME_ERROR,
            SpaceStage.NO_APP_FILE,
        ):
            print(f"[build] failed with {value}")
            print(f"[logs] https://huggingface.co/spaces/{repo_id}/logs/build")
            return False

        time.sleep(15)

    print("[build] timed out waiting for the Space.")
    print(f"[logs] https://huggingface.co/spaces/{repo_id}/logs/build")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", default="hdfc-mf-faq", help="Space name (default: hdfc-mf-faq)")
    parser.add_argument("--owner", default="", help="HF user or org (default: token owner)")
    parser.add_argument("--private", action="store_true", help="Create a private Space")
    parser.add_argument("--no-wait", action="store_true", help="Upload and exit without waiting for the build")
    parser.add_argument("--dry-run", action="store_true", help="Build the staging folder and print its size")
    parser.add_argument("--timeout", type=int, default=1800, help="Build wait timeout in seconds (default: 1800)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    token = (os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN") or "").strip()
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    groq_model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()

    stage = build_stage()
    size_mb = tree_size(stage) / (1024 * 1024)
    print(f"[stage] {stage}")
    print(f"[stage] {size_mb:.1f} MB")

    if args.dry_run:
        print("[dry-run] staging folder is ready; nothing was uploaded.")
        return 0

    if not token:
        print(
            "\nHF_TOKEN is missing.\n"
            "1. Create a free Hugging Face account: https://huggingface.co/join\n"
            "2. Create a WRITE token:              https://huggingface.co/settings/tokens\n"
            "3. Add it to .env (never commit this file):\n"
            "       HF_TOKEN=hf_your_token_here\n"
            "4. Re-run:  .\\.venv\\Scripts\\python.exe deploy_hf.py\n",
            file=sys.stderr,
        )
        return 2

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    try:
        who = api.whoami()
    except Exception as exc:
        print(f"[auth] Hugging Face rejected the token: {type(exc).__name__}", file=sys.stderr)
        return 2

    owner = args.owner.strip() or str(who.get("name") or "").strip()
    if not owner:
        print("[auth] Could not determine the token owner; pass --owner.", file=sys.stderr)
        return 2

    repo_id = f"{owner}/{args.space}"
    print(f"[repo] {repo_id}")

    try:
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=args.private,
            exist_ok=True,
        )
        print("[repo] Space created or already exists")

        print("[upload] uploading application, UI, config, and prebuilt Chroma index")
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=str(stage),
            commit_message="Deploy HDFC MF facts-only FAQ assistant",
        )
        print("[upload] complete")

        if groq_key:
            api.add_space_secret(
                repo_id=repo_id,
                key="GROQ_API_KEY",
                value=groq_key,
                description="Groq API key for answer generation",
            )
            print("[config] GROQ_API_KEY secret set")
        else:
            print("[config] no GROQ_API_KEY found; the Space will use deterministic fallback answers")

        api.add_space_variable(
            repo_id=repo_id,
            key="GROQ_MODEL",
            value=groq_model,
            description="Groq model ID used for answer generation",
        )
        print(f"[config] GROQ_MODEL={groq_model}")
    except Exception as exc:
        print(f"[deploy] failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"[stage] kept for inspection: {stage}", file=sys.stderr)
        return 1

    subdomain = f"{owner}-{args.space}".lower().replace("_", "-").replace(".", "-")
    print("\n[urls]")
    print(f"  Space page: https://huggingface.co/spaces/{repo_id}")
    print(f"  Public app: https://{subdomain}.hf.space")

    if args.no_wait:
        print("\n[build] not waiting (--no-wait). Check the Space page for build status.")
        return 0

    ok = space_stage(api, repo_id, args.timeout)
    shutil.rmtree(stage, ignore_errors=True)

    if not ok:
        return 1

    print("\n[done] The Space is running.")
    print(f"  Public app: https://{subdomain}.hf.space")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
