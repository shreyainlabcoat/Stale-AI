from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT = Path(os.getenv("STALEAI_ALLOWED_ROOT") or PROJECT_ROOT).resolve()


def resolve_repo(repo_path: str) -> Path:
    candidate = Path(repo_path).expanduser()
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(ALLOWED_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"Repository must be inside allowed root: {ALLOWED_ROOT}"
        ) from exc

    if not candidate.exists() or not candidate.is_dir():
        raise ValueError(f"Repository directory does not exist: {candidate}")
    return candidate


def resolve_inside_repo(repo: Path, relative_path: str) -> Path:
    target = (repo / relative_path).resolve()
    try:
        target.relative_to(repo)
    except ValueError as exc:
        raise ValueError("Path escapes the selected repository") from exc
    if not target.exists() or not target.is_file():
        raise ValueError(f"File does not exist: {target}")
    return target
