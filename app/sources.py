from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import httpx
import trafilatura


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_FILE = DATA_DIR / "snapshots.json"
USER_AGENT = "StaleAI/0.1 (+https://localhost)"
DEFAULT_TIMEOUT = 10.0
SnapshotRecord = dict[str, str | float]
SnapshotMap = dict[str, SnapshotRecord]


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


def _coerce_store(data: Any) -> SnapshotMap:
    return data if isinstance(data, dict) else {}


def load_store(snapshot_file: Path | None = None) -> SnapshotMap:
    """Load a snapshot store from disk."""
    path = snapshot_file or SNAPSHOT_FILE
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return _coerce_store(data)


def save_store(store: SnapshotMap, snapshot_file: Path | None = None) -> None:
    """Persist a snapshot store with an atomic replace."""
    path = snapshot_file or SNAPSHOT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(store, handle, indent=2, sort_keys=True)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def get_snapshot(url: str, snapshot_file: Path | None = None) -> SnapshotRecord | None:
    """Return a single stored snapshot by URL."""
    return load_store(snapshot_file).get(url)


def put_snapshot(
    url: str,
    *,
    label: str,
    authority: float,
    text: str,
    sha: str,
    fetched_at: str,
    snapshot_file: Path | None = None,
) -> SnapshotRecord:
    """Insert or replace a stored snapshot by URL."""
    store = load_store(snapshot_file)
    snapshot: SnapshotRecord = {
        "url": url,
        "label": label,
        "authority": authority,
        "text": text,
        "sha": sha,
        "fetched_at": fetched_at,
    }
    store[url] = snapshot
    save_store(store, snapshot_file)
    return snapshot
