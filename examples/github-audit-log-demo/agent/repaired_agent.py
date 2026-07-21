from __future__ import annotations

import sys


REPAIRED_AUDIT_LOG_ANSWER = """Use the GitHub REST API for a GitHub organization audit log.
Call GET /orgs/{org}/audit-log.
The older GraphQL audit-log interface is deprecated for this workflow."""


def answer(prompt: str) -> str:
    prompt_lower = prompt.lower()
    if "audit log" in prompt_lower and "organization" in prompt_lower and "github" in prompt_lower:
        return REPAIRED_AUDIT_LOG_ANSWER
    return "This demo agent only has a canned answer for the GitHub organization audit-log example."


def main() -> int:
    if len(sys.argv) < 2 or not " ".join(sys.argv[1:]).strip():
        print("Error: prompt required. Usage: python repaired_agent.py \"<prompt>\"", file=sys.stderr)
        return 2
    print(answer(" ".join(sys.argv[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
