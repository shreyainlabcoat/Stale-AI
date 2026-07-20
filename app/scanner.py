from __future__ import annotations

import math
from pathlib import Path

from .models import ChangeCard, RepoMatch, ScanResponse
from .security import resolve_repo


TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".txt", ".json", ".yaml",
    ".yml", ".toml", ".html", ".css", ".java", ".go", ".rs", ".rb", ".php",
    ".sh", ".ps1", ".sql",
}
IGNORED_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".next", ".pytest_cache",
}


def scan_repository(
    repo_path: str | Path,
    change: ChangeCard,
    *,
    base_dir: Path | None = None,
) -> ScanResponse:
    """Scan a repository for text references affected by a documentation change."""
    repo = resolve_repo(repo_path, base_dir=base_dir)
    search_terms = list(dict.fromkeys(
        change.deprecated_terms + change.affected_terms + [change.old_behavior]
    ))
    search_terms = [x.strip() for x in search_terms if 2 <= len(x.strip()) <= 160]

    matches: list[RepoMatch] = []
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            lower_line = line.lower()
            for term in search_terms:
                if term.lower() in lower_line:
                    matches.append(
                        RepoMatch(
                            file=str(path.relative_to(repo)),
                            line=line_no,
                            text=line.strip()[:300],
                            matched_term=term,
                        )
                    )
                    break
            if len(matches) >= 300:
                break
        if len(matches) >= 300:
            break

    impacted = sorted({m.file for m in matches})
    # Saturating score: 1 match matters, but 40 matches should not be 40x stronger.
    repository_impact = min(1.0, math.log1p(len(matches)) / math.log(41))
    adjusted = (
        0.30 * change.semantic_materiality
        + 0.20 * change.explicit_breaking_signal
        + 0.15 * change.source_authority
        + 0.10 * change.testability
        + 0.25 * repository_impact
    )
    adjusted = round(max(0, min(1, adjusted)), 3)

    if adjusted < 0.35:
        decision = "ignore"
    elif adjusted < 0.65:
        decision = "review"
    else:
        decision = "generate_evals"

    return ScanResponse(
        matches=matches,
        impacted_files=impacted,
        reference_count=len(matches),
        repository_impact=round(repository_impact, 3),
        adjusted_score=adjusted,
        decision=decision,
    )
