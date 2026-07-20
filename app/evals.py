from __future__ import annotations

import os
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
from .stats import brier_score_binary, wilson_interval


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
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(context)},
        ],
        text_format=EvaluationSet,
    )
    return response.output_parsed.evaluations[: req.count]


def generate_evaluations(req: GenerateEvalsRequest) -> GenerateEvalsResponse:
    used_model = bool(os.getenv("OPENAI_API_KEY"))
    if used_model:
        try:
            evaluations = _model_evals(req)
        except Exception:  # noqa: BLE001
            evaluations = _heuristic_evals(req)
            used_model = False
    else:
        evaluations = _heuristic_evals(req)
    return GenerateEvalsResponse(evaluations=evaluations, used_model=used_model)


def build_agent_command(command_template: list[str], prompt: str) -> list[str]:
    """Build a concrete agent command by substituting the prompt placeholder."""
    occurrences = sum(part.count("{prompt}") for part in command_template)
    if occurrences != 1:
        raise ValueError('Agent command must contain "{prompt}" exactly once')
    return [part.replace("{prompt}", prompt) for part in command_template]


def execute_agent_command(
    repo: Path,
    command: list[str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    """Execute an agent command inside the selected repository."""
    return subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )


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
    try:
        response = client.responses.parse(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": str(context)},
            ],
            text_format=SemanticJudgeResult,
        )
    except Exception:  # noqa: BLE001
        return None
    return response.output_parsed


def _run_evaluations_for_command(
    repo: Path,
    command_builder,
    evaluations: list[Evaluation],
    change: ChangeCard | None,
    timeout_seconds: int,
    runs_per_eval: int,
) -> RunEvalsResponse:
    results: list[EvalResult] = []
    for evaluation in evaluations:
        attempts: list[dict[str, object]] = []
        for _ in range(runs_per_eval):
            returncode_ok = False
            try:
                completed = execute_agent_command(
                    repo,
                    command_builder(evaluation.prompt),
                    timeout_seconds,
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
                error = None if completed.returncode == 0 else f"Exit code {completed.returncode}"
            except subprocess.TimeoutExpired:
                output = ""
                missing = evaluation.required_substrings
                found = []
                error = "Timed out"
            except OSError as exc:
                output = ""
                missing = evaluation.required_substrings
                found = []
                error = str(exc)
            except ValueError as exc:
                output = ""
                missing = evaluation.required_substrings
                found = []
                error = str(exc)

            judge_result = _semantic_judge(output, change, evaluation)
            judge_passed = None if judge_result is None else judge_result.passed
            judge_reason = None if judge_result is None else judge_result.reason
            passed = returncode_ok and not missing and not found and judge_passed is not False
            attempts.append(
                {
                    "passed": passed,
                    "output": output[:6000],
                    "missing_required": missing,
                    "found_forbidden": found,
                    "judge_passed": judge_passed,
                    "judge_reason": judge_reason,
                    "error": error,
                }
            )

        passed_runs = sum(1 for attempt in attempts if bool(attempt["passed"]))
        pass_rate = round(passed_runs / runs_per_eval, 3)
        wilson_low, wilson_high = wilson_interval(passed_runs, runs_per_eval)
        brier_score = brier_score_binary(pass_rate, 1.0)
        first = attempts[0]

        results.append(
            EvalResult(
                evaluation_id=evaluation.id,
                name=evaluation.name,
                passed=passed_runs == runs_per_eval,
                output=str(first["output"]),
                missing_required=list(first["missing_required"]),
                found_forbidden=list(first["found_forbidden"]),
                judge_passed=first["judge_passed"],
                judge_reason=first["judge_reason"],
                passed_runs=passed_runs,
                total_runs=runs_per_eval,
                pass_rate=pass_rate,
                wilson_low=wilson_low,
                wilson_high=wilson_high,
                brier_score=brier_score,
                error=first["error"],
            )
        )

    passed_count = sum(1 for r in results if r.passed)
    overall_pass_rate = round(
        sum(result.passed_runs for result in results) / max(1, len(results) * runs_per_eval),
        3,
    )
    average_brier_score = round(
        sum(result.brier_score for result in results) / max(1, len(results)),
        3,
    )
    return RunEvalsResponse(
        passed=passed_count,
        failed=len(results) - passed_count,
        pass_rate=overall_pass_rate,
        average_brier_score=average_brier_score,
        results=results,
    )


def run_evaluations(
    repo_path: str,
    agent_script: str,
    evaluations: list[Evaluation],
    change: ChangeCard | None,
    timeout_seconds: int,
    runs_per_eval: int,
    agent_command: list[str] | None = None,
    base_dir: Path | None = None,
) -> RunEvalsResponse:
    repo = resolve_repo(repo_path, base_dir=base_dir)
    if agent_command is not None:
        return _run_evaluations_for_command(
            repo,
            lambda prompt: build_agent_command(list(agent_command), prompt),
            evaluations,
            change,
            timeout_seconds,
            runs_per_eval,
        )

    script = resolve_inside_repo(repo, agent_script)
    return _run_evaluations_for_command(
        repo,
        lambda prompt: [sys.executable, str(script), prompt],
        evaluations,
        change,
        timeout_seconds,
        runs_per_eval,
    )
