from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROMPT = "How should I retrieve the audit log for a GitHub organization?"
ROOT = Path(__file__).resolve().parent
AGENT_DIR = ROOT / "agent"


def _run(script_name: str) -> str:
    completed = subprocess.run(
        [sys.executable, script_name, PROMPT],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{script_name} failed with exit code {completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def main() -> int:
    try:
        stale_output = _run("agent.py")
        repaired_output = _run("repaired_agent.py")

        for term in ("GraphQL", "organization.auditLog", "actorLogin"):
            if term not in stale_output:
                raise AssertionError(f"Stale agent output is missing required term: {term}")

        for term in ("REST", "GET /orgs/{org}/audit-log", "deprecated"):
            if term not in repaired_output:
                raise AssertionError(f"Repaired agent output is missing required term: {term}")

        for forbidden in ("organization.auditLog", "actorLogin"):
            if forbidden in repaired_output:
                raise AssertionError(f"Repaired agent output should not contain: {forbidden}")
    except Exception as exc:  # noqa: BLE001
        print(f"Demo validation failed: {exc}", file=sys.stderr)
        return 1

    print("Demo validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
