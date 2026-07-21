from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}

FAST_DEMO_RUNS_PER_EVAL = 1


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE_VALUES


def fast_demo_enabled() -> bool:
    """Whether STALEAI_FAST_DEMO is active for this process."""
    return _bool_env("STALEAI_FAST_DEMO", default=False)


def semantic_judge_enabled() -> bool:
    """Whether the OpenAI semantic judge should run.

    Fast demo mode always disables the judge. STALEAI_SEMANTIC_JUDGE can
    also disable it independently, without turning on the rest of fast
    demo mode (defaults to on otherwise).
    """
    if fast_demo_enabled():
        return False
    return _bool_env("STALEAI_SEMANTIC_JUDGE", default=True)


def fast_demo_status() -> dict[str, bool]:
    return {
        "fast_demo": fast_demo_enabled(),
        "semantic_judge": semantic_judge_enabled(),
    }
