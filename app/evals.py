from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from openai import OpenAI
from pydantic import BaseModel

from .models import (
    ChangeCard,
    EvalResult,
    Evaluation,
    GenerateEvalsRequest,
    GenerateEvalsResponse,
    RunEvalsResponse,
)
from .security import resolve_inside_repo, resolve_repo


class EvaluationSet(BaseModel):
    evaluations: list[Evaluation]


class SemanticJudgeResult(BaseModel):
    passed: bool
    reason: str


def _clean_assertion(value: str) -> str:
    return value.strip().strip("`").strip()


def _heuristic_evals(req: GenerateEvalsRequest) -> list[Evaluation]:
    old = [_clean_assertion(x) for x in req.change.deprecated_terms if x.strip()]
    new = [_clean_assertion(x) for x in req.change.replacement_terms if x.strip()]

    old_term = old[0] if old else _clean_assertion(req.change.old_behavior)
    new_term = new[0] if new else _clean_assertion(req.change.new_behavior)

    prompts = [
        "Write the current implementation for the behavior described in the connected documentation.",
        "Show a minimal working example using the current API, not a legacy API.",
        "Explain the migration and provide updated code that preserves intended behavior.",
    ]

    evaluations: list[Evaluation] = []
    for i in range(req.count):
        required = [new_term] if new_term and len(new_term) < 160 else []
        forbidden = [old_term] if old_term and old_term != new_term and len(old_term) < 160 else []
        evaluations.append(
            Evaluation(
                id=f"eval-{i+1}",
                name=["Current implementation", "Legacy rejection", "Migration behavior"][i % 3],
                prompt=prompts[i % len(prompts)],
                required_substrings=required,
                forbidden_substrings=forbidden,
                rationale="The output should use the current documented behavior and avoid the obsolete form.",
            )
        )
    return evaluations


def _model_evals(req: GenerateEvalsRequest) -> list[Evaluation]:
    client = OpenAI()
    system = """
Generate deterministic regression evaluations for an AI coding or support agent.

Each evaluation must:
- Ask for behavior that is directly affected by the supplied documentation change.
- Use exact, short required and forbidden substrings that can be checked mechanically.
- Never require a substring unless it is present in the supplied current documentation/change record.
- Never forbid a substring unless it is explicitly deprecated, removed, or replaced.
- Avoid trivia questions. Prefer implementation, migration, or compatibility tasks.
- Return no more than the requested count.
"""
    context = {
        "change": req.change.model_dump(),
        "repository_matches": [m.model_dump() for m in req.matches[:30]],
        "requested_count": req.count,
    }
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(context)},
        ],
        text_format=EvaluationSet,
    )
    return response.output_parsed.evaluations[: req.count]


def generate_evaluations(req: GenerateEvalsRequest) -> GenerateEvalsResponse:
    used_model = bool(os.getenv("OPENAI_API_KEY"))
    evaluations = _model_evals(req) if used_model else _heuristic_evals(req)
    return GenerateEvalsResponse(evaluations=evaluations, used_model=used_model)


def _semantic_judge(
    agent_output: str,
    change: ChangeCard | None,
    evaluation: Evaluation,
) -> SemanticJudgeResult | None:
    if not os.getenv("OPENAI_API_KEY") or change is None:
        return None

    client = OpenAI()
    system = """
Judge only whether the output is consistent with the current documented behavior.
Ignore style and completeness.
A legitimate historical mention of a former term is allowed.
Fail only if the output presents obsolete behavior as current or contradicts the current docs.
"""
    context = {
        "change": change.model_dump(),
        "evaluation": evaluation.model_dump(),
        "agent_output": agent_output,
    }
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(context)},
        ],
        text_format=SemanticJudgeResult,
    )
    return response.output_parsed


def run_evaluations(
    repo_path: str,
    agent_script: str,
    evaluations: list[Evaluation],
    change: ChangeCard | None,
    timeout_seconds: int,
) -> RunEvalsResponse:
    repo = resolve_repo(repo_path)
    script = resolve_inside_repo(repo, agent_script)

    results: list[EvalResult] = []
    for evaluation in evaluations:
        returncode_ok = False
        try:
            completed = subprocess.run(
                [sys.executable, str(script), evaluation.prompt],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            output = (completed.stdout + "\n" + completed.stderr).strip()
            output_lower = output.lower()
            missing = [
                s for s in evaluation.required_substrings
                if s.lower() not in output_lower
            ]
            found = [
                s for s in evaluation.forbidden_substrings
                if s.lower() in output_lower
            ]
            returncode_ok = completed.returncode == 0
            passed = returncode_ok and not missing and not found
            error = None if completed.returncode == 0 else f"Exit code {completed.returncode}"
        except subprocess.TimeoutExpired:
            output = ""
            missing = evaluation.required_substrings
            found = []
            passed = False
            error = "Timed out"
        except OSError as exc:
            output = ""
            missing = evaluation.required_substrings
            found = []
            passed = False
            error = str(exc)

        judge_result = _semantic_judge(output, change, evaluation)
        judge_passed = None if judge_result is None else judge_result.passed
        judge_reason = None if judge_result is None else judge_result.reason
        passed = returncode_ok and not missing and not found and judge_passed is not False

        results.append(
            EvalResult(
                evaluation_id=evaluation.id,
                name=evaluation.name,
                passed=passed,
                output=output[:6000],
                missing_required=missing,
                found_forbidden=found,
                judge_passed=judge_passed,
                judge_reason=judge_reason,
                error=error,
            )
        )

    passed_count = sum(1 for r in results if r.passed)
    return RunEvalsResponse(
        passed=passed_count,
        failed=len(results) - passed_count,
        results=results,
    )
