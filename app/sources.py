from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import trafilatura


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_FILE = DATA_DIR / "snapshots.json"
USER_AGENT = "StaleAI/0.1 (+https://localhost)"
DEFAULT_TIMEOUT = 10.0


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def content_sha(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def fetch(url: str) -> dict[str, str]:
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=DEFAULT_TIMEOUT,
    ) as client:
        response = client.get(url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    text = response.text
    looks_like_html = "html" in content_type or text.lstrip().lower().startswith(
        ("<!doctype html", "<html")
    )

    if looks_like_html:
        extracted = trafilatura.extract(text)
        if extracted:
            text = extracted

    fetched_at = datetime.now(timezone.utc).isoformat()
    return {
        "url": url,
        "text": text,
        "sha": content_sha(text),
        "fetched_at": fetched_at,
    }


def load_store() -> dict[str, dict[str, str | float]]:
    if not SNAPSHOT_FILE.exists():
        return {}
    with SNAPSHOT_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_store(store: dict[str, dict[str, str | float]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2, sort_keys=True)


def get_snapshot(url: str) -> dict[str, str | float] | None:
    return load_store().get(url)


def put_snapshot(
    url: str,
    *,
    label: str,
    authority: float,
    text: str,
    sha: str,
    fetched_at: str,
) -> dict[str, str | float]:
    store = load_store()
    snapshot: dict[str, str | float] = {
        "url": url,
        "label": label,
        "authority": authority,
        "text": text,
        "sha": sha,
        "fetched_at": fetched_at,
    }
    store[url] = snapshot
    save_store(store)
    return snapshot
