import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")
ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")


def _expand(value):
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: Path | None = None) -> dict:
    path = path or (ROOT / "config.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = _expand(raw)
    urls = cfg["sources"]["urls"]
    if len(urls) != 5:
        raise ValueError(f"Expected exactly 5 source URLs, got {len(urls)}")
    return cfg


CONFIG = load_config()
URLS: list[str] = CONFIG["sources"]["urls"]
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"
