from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .models import RepairRequest, RepairResponse
from .security import resolve_repo


def _git_diff(repo: Path) -> str:
    if not (repo / ".git").exists():
        return ""
    completed = subprocess.run(
        ["git", "diff", "--"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return completed.stdout[:20000]


def build_repair_prompt(req: RepairRequest) -> str:
    failure_summary = [
        {
            "name": f.name,
            "missing_required": f.missing_required,
            "found_forbidden": f.found_forbidden,
            "error": f.error,
        }
        for f in req.failures
        if not f.passed
    ]
    impacted = [
        {"file": m.file, "line": m.line, "text": m.text, "term": m.matched_term}
        for m in req.matches[:80]
    ]
    return f"""
You are repairing an AI agent repository after an official documentation change.

CHANGE RECORD:
{json.dumps(req.change.model_dump(), indent=2)}

FAILING REGRESSION EVIDENCE:
{json.dumps(failure_summary, indent=2)}

IMPACTED LOCATIONS:
{json.dumps(impacted, indent=2)}

TASK:
1. Inspect the repository and locate the actual source of the stale behavior.
2. Make the smallest safe patch that updates prompts, examples, tool schemas,
   knowledge files, or code as needed.
3. Preserve backward compatibility where doing so does not contradict the current docs.
4. Do not edit historical citations merely to make strings disappear.
5. Add or update tests for the detected change.
6. Run the repository's existing tests and the relevant agent command.
7. Do not commit, push, deploy, or access files outside this repository.
8. Finish with a concise summary of files changed and tests run.
"""


def repair_with_codex(req: RepairRequest) -> RepairResponse:
    repo = resolve_repo(req.repo_path)
    prompt = build_repair_prompt(req)

    if not req.run_codex:
        return RepairResponse(
            status="plan_only",
            message="Repair prompt generated. Codex execution was disabled.",
            codex_output=prompt,
            git_diff=_git_diff(repo),
        )

    codex_bin = os.getenv("CODEX_BIN", "codex")
    if not shutil.which(codex_bin):
        return RepairResponse(
            status="codex_unavailable",
            message=(
                "Codex CLI was not found. Install and authenticate Codex, then retry. "
                "The generated repair prompt is included below."
            ),
            codex_output=prompt,
            git_diff=_git_diff(repo),
        )

    try:
        completed = subprocess.run(
            [
                codex_bin,
                "exec",
                "--ephemeral",
                "--sandbox",
                "workspace-write",
                prompt,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RepairResponse(
            status="failed",
            message=f"Codex execution failed: {exc}",
            codex_output="",
            git_diff=_git_diff(repo),
        )

    output = (completed.stdout + "\n" + completed.stderr).strip()
    status = "patched" if completed.returncode == 0 else "failed"
    return RepairResponse(
        status=status,
        message=(
            "Codex completed the repair workflow."
            if completed.returncode == 0
            else f"Codex exited with code {completed.returncode}."
        ),
        codex_output=output[:30000],
        git_diff=_git_diff(repo),
    )
