from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .analyzer import analyze
from .config import StaleAIConfig, save_config
from .evals import generate_evaluations, run_evaluations
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    Evaluation,
    GenerateEvalsRequest,
    RunEvalsResponse,
    ScanResponse,
)
from .scanner import scan_repository
from .sources import fetch, load_store, save_store


STATE_DIRNAME = ".staleai"
SNAPSHOTS_FILENAME = "snapshots.json"
PENDING_FILENAME = "pending.json"
REPORTS_DIRNAME = "reports"
LATEST_REPORT_FILENAME = "latest.json"


class PipelineError(ValueError):
    """Raised when a pipeline operation cannot complete safely."""


class SourceCheckResult(BaseModel):
    name: str
    url: str
    status: str
    old_sha: str | None = None
    current_sha: str | None = None
    analysis: AnalyzeResponse | None = None
    scan: ScanResponse | None = None
    evaluations: list[Evaluation] = Field(default_factory=list)
    evaluation_results: RunEvalsResponse | None = None
    overall_pass_rate: float | None = None
    error: str | None = None


class FreshnessCheckResult(BaseModel):
    timestamp: str
    repository_path: str
    used_openai_api: bool
    status: str
    sources: list[SourceCheckResult]
    report_path: str
    latest_report_path: str


class InitializeProjectResult(BaseModel):
    config_path: str
    snapshots_path: str
    github_action_path: str | None = None
    captured_sources: list[str]


class AcceptPendingResult(BaseModel):
    snapshots_path: str
    accepted_sources: list[dict[str, str]]


def state_dir(repo: Path) -> Path:
    """Return the repository-local Stale AI state directory."""
    return repo / STATE_DIRNAME


def snapshots_path(repo: Path) -> Path:
    return state_dir(repo) / SNAPSHOTS_FILENAME


def pending_path(repo: Path) -> Path:
    return state_dir(repo) / PENDING_FILENAME


def reports_dir(repo: Path) -> Path:
    return state_dir(repo) / REPORTS_DIRNAME


def latest_report_path(repo: Path) -> Path:
    return reports_dir(repo) / LATEST_REPORT_FILENAME


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _workflow_contents() -> str:
    return """name: Stale AI

on:
  workflow_dispatch:
  schedule:
    - cron: "0 9 * * *"

env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  OPENAI_MODEL: ${{ vars.OPENAI_MODEL }}

jobs:
  staleai-check:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install repository dependencies when present
        shell: bash
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            python -m pip install -r requirements.txt
          elif [ -f pyproject.toml ]; then
            python -m pip install -e .
          fi

      - name: Install Stale AI
        run: python -m pip install "git+https://github.com/shreyainlabcoat/Stale-AI.git"

      - name: Run Stale AI check
        run: staleai check

      - name: Upload latest report artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: staleai-latest-report
          path: .staleai/reports/latest.json
          if-no-files-found: ignore

# Create the OPENAI_API_KEY repository secret to enable model-based analysis.
# The workflow never auto-accepts changed sources and does not run repair.
"""


def _write_github_action(repo: Path, force: bool) -> Path:
    workflow_path = repo / ".github" / "workflows" / "staleai.yml"
    if workflow_path.exists() and not force:
        raise PipelineError(f"GitHub workflow already exists: {workflow_path}")
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(_workflow_contents(), encoding="utf-8")
    return workflow_path


def initialize_project(
    repo: Path,
    config: StaleAIConfig,
    create_github_action: bool,
    *,
    force: bool = False,
) -> InitializeProjectResult:
    """Initialize Stale AI state in a target repository."""
    if not repo.exists() or not repo.is_dir():
        raise PipelineError(f"Repository directory does not exist: {repo}")

    config_file = repo / "staleai.yaml"
    if config_file.exists() and not force:
        raise PipelineError(f"Configuration already exists: {config_file.name}")

    baselines: dict[str, dict[str, str | float]] = {}
    captured_sources: list[str] = []
    for source in config.sources:
        fetched = fetch(source.url)
        baselines[source.url] = {
            "url": source.url,
            "label": source.name,
            "authority": source.authority,
            "text": fetched["text"],
            "sha": fetched["sha"],
            "fetched_at": fetched["fetched_at"],
        }
        captured_sources.append(source.name)

    save_config(repo, config)
    state_dir(repo).mkdir(parents=True, exist_ok=True)
    save_store(baselines, snapshots_path(repo))

    github_action_path: Path | None = None
    if create_github_action:
        github_action_path = _write_github_action(repo, force)

    return InitializeProjectResult(
        config_path=str(config_file),
        snapshots_path=str(snapshots_path(repo)),
        github_action_path=str(github_action_path) if github_action_path else None,
        captured_sources=captured_sources,
    )


def run_freshness_check(repo: Path, config: StaleAIConfig) -> FreshnessCheckResult:
    """Run a repository-local freshness check without modifying the approved baseline."""
    snapshot_file = snapshots_path(repo)
    if not snapshot_file.exists():
        raise PipelineError(f"Missing approved baseline: {snapshot_file}")

    approved = load_store(snapshot_file)
    pending_updates = load_store(pending_path(repo))
    source_results: list[SourceCheckResult] = []
    overall_status = "fresh"
    used_openai_api = bool(os.getenv("OPENAI_API_KEY"))

    for source in config.sources:
        baseline = approved.get(source.url)
        if baseline is None:
            raise PipelineError(f"Missing approved baseline for source: {source.name}")

        try:
            fetched = fetch(source.url)
        except Exception as exc:  # noqa: BLE001
            source_results.append(
                SourceCheckResult(
                    name=source.name,
                    url=source.url,
                    status="error",
                    old_sha=str(baseline.get("sha")),
                    error=str(exc),
                )
            )
            overall_status = "error"
            continue

        old_sha = str(baseline["sha"])
        current_sha = fetched["sha"]
        if old_sha == current_sha:
            source_results.append(
                SourceCheckResult(
                    name=source.name,
                    url=source.url,
                    status="unchanged",
                    old_sha=old_sha,
                    current_sha=current_sha,
                )
            )
            continue

        analysis = analyze(
            AnalyzeRequest(
                source_name=source.name,
                source_url=source.url,
                old_text=str(baseline["text"]),
                new_text=fetched["text"],
                source_authority=source.authority,
            )
        )
        pending_updates[source.url] = {
            "url": source.url,
            "label": source.name,
            "authority": source.authority,
            "text": fetched["text"],
            "sha": fetched["sha"],
            "fetched_at": fetched["fetched_at"],
        }

        if analysis.decision == "ignore":
            source_results.append(
                SourceCheckResult(
                    name=source.name,
                    url=source.url,
                    status="changed_ignored",
                    old_sha=old_sha,
                    current_sha=current_sha,
                    analysis=analysis,
                )
            )
            continue

        scan = scan_repository(str(repo), analysis.change, base_dir=repo.parent)
        if scan.decision == "ignore":
            source_results.append(
                SourceCheckResult(
                    name=source.name,
                    url=source.url,
                    status="changed_ignored",
                    old_sha=old_sha,
                    current_sha=current_sha,
                    analysis=analysis,
                    scan=scan,
                )
            )
            continue
        if scan.decision == "review":
            source_results.append(
                SourceCheckResult(
                    name=source.name,
                    url=source.url,
                    status="changed_review",
                    old_sha=old_sha,
                    current_sha=current_sha,
                    analysis=analysis,
                    scan=scan,
                )
            )
            if overall_status != "error":
                overall_status = "review"
            continue

        generated = generate_evaluations(
            GenerateEvalsRequest(
                change=analysis.change,
                matches=scan.matches,
                count=config.evaluations.count,
            )
        )
        evaluation_results = run_evaluations(
            repo_path=str(repo),
            agent_script="agent.py",
            evaluations=generated.evaluations,
            change=analysis.change,
            timeout_seconds=config.agent.timeout_seconds,
            runs_per_eval=config.evaluations.runs_per_eval,
            agent_command=config.agent.command,
            base_dir=repo.parent,
        )
        if evaluation_results.failed:
            status = "stale"
            overall_status = "stale"
        else:
            status = "changed_passed"
            if overall_status == "fresh":
                overall_status = "passed"
        source_results.append(
            SourceCheckResult(
                name=source.name,
                url=source.url,
                status=status,
                old_sha=old_sha,
                current_sha=current_sha,
                analysis=analysis,
                scan=scan,
                evaluations=generated.evaluations,
                evaluation_results=evaluation_results,
                overall_pass_rate=evaluation_results.pass_rate,
            )
        )

    save_store(pending_updates, pending_path(repo))
    report_timestamp = _timestamp()
    report_file = reports_dir(repo) / f"{report_timestamp}.json"
    latest_file = latest_report_path(repo)
    report = FreshnessCheckResult(
        timestamp=_iso_timestamp(),
        repository_path=str(repo),
        used_openai_api=used_openai_api,
        status=overall_status,
        sources=source_results,
        report_path=str(report_file),
        latest_report_path=str(latest_file),
    )
    payload = report.model_dump(mode="json")
    _write_json(report_file, payload)
    _write_json(latest_file, payload)
    return report


def accept_pending_sources(repo: Path) -> AcceptPendingResult:
    """Promote pending snapshots into the approved baseline after review."""
    pending_file = pending_path(repo)
    if not pending_file.exists():
        raise PipelineError("No pending source updates found.")

    pending = load_store(pending_file)
    if not pending:
        raise PipelineError("No pending source updates found.")

    approved = load_store(snapshots_path(repo))
    accepted_sources: list[dict[str, str]] = []
    for url, snapshot in pending.items():
        approved[url] = snapshot
        accepted_sources.append(
            {
                "name": str(snapshot.get("label", url)),
                "url": url,
                "sha": str(snapshot.get("sha", "")),
            }
        )

    save_store(approved, snapshots_path(repo))
    save_store({}, pending_file)
    return AcceptPendingResult(
        snapshots_path=str(snapshots_path(repo)),
        accepted_sources=accepted_sources,
    )
