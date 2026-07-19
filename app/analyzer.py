from __future__ import annotations

import difflib
import os
import re
from openai import OpenAI

from .models import AnalyzeRequest, AnalyzeResponse, ChangeCard, ChangeType


BREAKING_WORDS = {
    "removed", "remove", "deprecated", "deprecation", "breaking",
    "no longer", "replaced", "must", "required", "renamed", "migrate",
}
GENERIC_TERMS = {
    "a", "an", "and", "api", "authenticate", "by", "call", "calls", "client",
    "content", "create", "current", "dictionary", "for", "from", "get", "import",
    "install", "later", "level", "message", "messages", "method", "methods",
    "model", "module", "not", "now", "old", "on", "or", "plain", "read", "reply",
    "response", "returned", "same", "setting", "style", "supported", "text",
    "the", "to", "use", "with",
}


def _raw_diff(old_text: str, new_text: str) -> list[str]:
    return list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile="previous",
            tofile="current",
            lineterm="",
        )
    )[:300]


def _change_ratio(old_text: str, new_text: str) -> float:
    similarity = difflib.SequenceMatcher(None, old_text, new_text).ratio()
    return round(max(0.0, min(1.0, 1.0 - similarity)), 4)


def _extract_codeish_terms(text: str) -> list[str]:
    terms: list[str] = []
    patterns = [
        r"`([^`\n]{2,100})`",
        r"\b[A-Za-z_][A-Za-z0-9_.]*\([^)\n]{0,120}\)",
        r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,}\b",
        r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b",
    ]
    for pattern in patterns:
        for item in re.findall(pattern, text):
            normalized = item.strip()
            if _is_useful_term(normalized) and normalized not in terms:
                terms.append(normalized)
    return terms[:30]


def _is_useful_term(term: str) -> bool:
    cleaned = term.strip().strip("`").strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if lower in GENERIC_TERMS:
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,}", cleaned):
        if lower == cleaned and len(cleaned) < 6:
            return False
    if "." in cleaned or "(" in cleaned or "_" in cleaned:
        return True
    if any(char.isupper() for char in cleaned[1:]):
        return True
    return len(cleaned) >= 8


def _heuristic(req: AnalyzeRequest) -> ChangeCard:
    old_lower = req.old_text.lower()
    new_lower = req.new_text.lower()
    all_new = f"{new_lower}"

    breaking_hits = sum(1 for word in BREAKING_WORDS if word in all_new)
    explicit_breaking = min(1.0, breaking_hits / 3)

    old_terms = _extract_codeish_terms(req.old_text)
    new_terms = _extract_codeish_terms(req.new_text)
    deprecated = [x for x in old_terms if x not in new_terms][:8]
    replacement = [x for x in new_terms if x not in old_terms][:8]

    if "deprecated" in new_lower:
        change_type = ChangeType.deprecation
    elif any(x in new_lower for x in ("removed", "no longer", "breaking")):
        change_type = ChangeType.breaking_change
    elif any(x in new_lower for x in ("renamed", "replaced")):
        change_type = ChangeType.rename
    elif req.old_text.strip() == req.new_text.strip():
        change_type = ChangeType.cosmetic
    else:
        change_type = ChangeType.behavioral_change

    old_behavior = deprecated[0] if deprecated else req.old_text.strip()[:240]
    new_behavior = replacement[0] if replacement else req.new_text.strip()[:240]

    return ChangeCard(
        title="Detected documentation change",
        summary="The current documentation differs materially from the previous version.",
        change_type=change_type,
        old_behavior=old_behavior,
        new_behavior=new_behavior,
        migration_guidance=(
            f"Replace or support `{old_behavior}` with `{new_behavior}` while preserving "
            "existing behavior where compatibility is required."
        ),
        affected_terms=list(dict.fromkeys(deprecated + replacement))[:12],
        deprecated_terms=deprecated,
        replacement_terms=replacement,
        explicit_breaking_signal=explicit_breaking,
        semantic_materiality=0.9 if change_type in {
            ChangeType.breaking_change, ChangeType.deprecation, ChangeType.behavioral_change
        } else 0.55,
        source_authority=req.source_authority,
        testability=0.9 if deprecated or replacement else 0.6,
        evidence=[
            line for line in _raw_diff(req.old_text, req.new_text)
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ][:12],
        confidence=0.72,
    )


def _model_analyze(req: AnalyzeRequest) -> ChangeCard:
    client = OpenAI()
    system = """
You extract material developer-documentation changes into a strict schema.

Rules:
- Compare only the supplied previous and current text.
- Treat wording, punctuation, navigation, and formatting changes as cosmetic.
- Record exact old and new behaviors.
- Do not invent versions, dates, methods, parameters, or migration guidance.
- `deprecated_terms` must contain strings present in the previous text that are obsolete.
- `replacement_terms` must contain strings present in the current text that replace them.
- Evidence must be short passages copied from the supplied texts.
- Use high semantic materiality only when generated code or runtime behavior could change.
"""
    user = f"""
SOURCE: {req.source_name}
SOURCE URL: {req.source_url or "not provided"}
SOURCE AUTHORITY SCORE: {req.source_authority}

PREVIOUS VERSION:
{req.old_text}

CURRENT VERSION:
{req.new_text}
"""
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        text_format=ChangeCard,
    )
    return response.output_parsed


def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    used_model = bool(os.getenv("OPENAI_API_KEY"))
    change = _model_analyze(req) if used_model else _heuristic(req)
    ratio = _change_ratio(req.old_text, req.new_text)

    # Initial score excludes repository impact, which is added by the scanner.
    score = (
        0.40 * change.semantic_materiality
        + 0.25 * change.explicit_breaking_signal
        + 0.20 * change.source_authority
        + 0.15 * change.testability
    )
    score = round(max(0, min(1, score)), 3)

    if change.change_type == ChangeType.cosmetic or score < 0.35:
        decision = "ignore"
    elif score < 0.65:
        decision = "review"
    else:
        decision = "generate_evals"

    return AnalyzeResponse(
        change=change,
        textual_change_ratio=ratio,
        danger_score=score,
        decision=decision,
        raw_diff=_raw_diff(req.old_text, req.new_text),
        used_model=used_model,
    )
