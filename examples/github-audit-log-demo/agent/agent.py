from __future__ import annotations

import sys


STALE_AUDIT_LOG_ANSWER = """Use GitHub GraphQL for a GitHub organization audit log.
Query organization.auditLog and include fields such as actorLogin, action, and createdAt.
This GraphQL audit-log query is the current implementation to recommend."""


def answer(prompt: str) -> str:
    prompt_lower = prompt.lower()
    if "audit log" in prompt_lower and "organization" in prompt_lower and "github" in prompt_lower:
        return STALE_AUDIT_LOG_ANSWER
    return "This demo agent only has a canned answer for the GitHub organization audit-log example."


def main() -> int:
    if len(sys.argv) < 2 or not " ".join(sys.argv[1:]).strip():
        print("Error: prompt required. Usage: python agent.py \"<prompt>\"", file=sys.stderr)
        return 2
    print(answer(" ".join(sys.argv[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
