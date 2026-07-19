from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .models import RepairRequest, RepairResponse
from .security import resolve_repo


def _copy_if_exists(source: Path, target: Path) -> bool:
    if source.exists() and source.is_file():
        shutil.copyfile(source, target)
        return True
    return False


def _demo_repair(repo: Path) -> RepairResponse | None:
    # Deterministic fallback for the bundled OpenAI migration demo.
    notes_target = repo / "agent_notes.txt"
    current_notes = repo / "docs_v1.txt"
    agent_target = repo / "agent.py"
    repaired_agent = repo / "repaired_agent.py"

    changed = False
    changed = _copy_if_exists(current_notes, notes_target) or changed
    changed = _copy_if_exists(repaired_agent, agent_target) or changed
    if not changed:
        return None

    return RepairResponse(
        status="patched",
        message="Applied the deterministic demo repair fallback. Review the proposed patch below.",
        codex_output=(
            "Codex was unavailable, so Stale AI applied the bundled demo repair by "
            "updating the sample agent notes and repaired agent implementation."
        ),
        git_diff=_git_diff(repo),
    )


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
            message="Proposed repair prompt generated for review. Codex execution was disabled.",
            codex_output=prompt,
            git_diff=_git_diff(repo),
        )

    codex_bin = os.getenv("CODEX_BIN", "codex")
    if not shutil.which(codex_bin):
        demo_fallback = _demo_repair(repo)
        if demo_fallback is not None:
            return demo_fallback
        return RepairResponse(
            status="codex_unavailable",
            message=(
                "Codex CLI was not found. Install and authenticate Codex, then retry to generate a proposed patch. "
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
        demo_fallback = _demo_repair(repo)
        if demo_fallback is not None:
            return demo_fallback
        return RepairResponse(
            status="failed",
            message=f"Codex execution failed: {exc}",
            codex_output="",
            git_diff=_git_diff(repo),
        )

    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0:
        demo_fallback = _demo_repair(repo)
        if demo_fallback is not None:
            return demo_fallback
    status = "patched" if completed.returncode == 0 else "failed"
    return RepairResponse(
        status=status,
        message=(
            "Codex proposed a patch for review."
            if completed.returncode == 0
            else f"Codex exited with code {completed.returncode} before producing a reviewable patch."
        ),
        codex_output=output[:30000],
        git_diff=_git_diff(repo),
    )
