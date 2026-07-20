from __future__ import annotations

import json
import traceback
from pathlib import Path

import typer

from .config import (
    ConfigError,
    StaleAIConfig,
    AgentConfig,
    EvaluationConfig,
    RepairConfig,
    TrustedSourceConfig,
    load_config,
    parse_agent_command,
)
from .pipeline import (
    PipelineError,
    accept_pending_sources,
    initialize_project,
    latest_report_path,
    run_freshness_check,
)


app = typer.Typer(help="Detect when trusted documentation changes have made an agent stale.")


def _resolve_repo(directory: Path) -> Path:
    repo = directory.expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise PipelineError(f"Repository directory does not exist: {repo}")
    return repo


def _print_error(message: str, verbose: bool, exc: Exception | None = None) -> None:
    typer.echo(f"Error: {message}", err=True)
    if verbose and exc is not None:
        typer.echo(traceback.format_exc(), err=True)


def _prompt_init_values(
    agent_command: str | None,
    source_name: str | None,
    source_url: str | None,
    authority: float,
    eval_count: int,
    runs_per_eval: int,
    timeout: int,
    github_action: bool,
) -> tuple[str, str, str, float, int, int, int, bool]:
    typer.echo("Stale AI initialization")
    command_value = agent_command or typer.prompt(
        'Agent command', default='python agent.py "{prompt}"'
    )
    name_value = source_name or typer.prompt(
        "Trusted source name", default="Official documentation"
    )
    url_value = source_url or typer.prompt("Trusted source URL")
    authority_value = authority if source_name or source_url or agent_command else typer.prompt(
        "Source authority", default=authority
    )
    eval_count_value = eval_count if agent_command or source_url else typer.prompt(
        "Evaluations per change", default=eval_count
    )
    runs_value = runs_per_eval if agent_command or source_url else typer.prompt(
        "Runs per evaluation", default=runs_per_eval
    )
    timeout_value = timeout if agent_command or source_url else typer.prompt(
        "Agent timeout in seconds", default=timeout
    )
    github_value = github_action if github_action else typer.confirm(
        "Create GitHub Action?", default=True
    )
    return (
        command_value,
        name_value,
        url_value,
        float(authority_value),
        int(eval_count_value),
        int(runs_value),
        int(timeout_value),
        bool(github_value),
    )


def _build_config(
    agent_command: str,
    source_name: str,
    source_url: str,
    authority: float,
    eval_count: int,
    runs_per_eval: int,
    timeout: int,
) -> StaleAIConfig:
    return StaleAIConfig(
        version=1,
        agent=AgentConfig(
            command=parse_agent_command(agent_command),
            timeout_seconds=timeout,
        ),
        sources=[
            TrustedSourceConfig(
                name=source_name,
                url=source_url,
                authority=authority,
            )
        ],
        evaluations=EvaluationConfig(
            count=eval_count,
            runs_per_eval=runs_per_eval,
        ),
        repair=RepairConfig(enabled=False, require_approval=True),
    )


def _status_to_exit_code(status: str) -> int:
    if status in {"fresh", "passed"}:
        return 0
    if status in {"review", "stale"}:
        return 1
    return 2


def _ok(message: str) -> None:
    typer.echo(f"[ok] {message}")


def _warn(message: str) -> None:
    typer.echo(f"[!] {message}")


def _fail(message: str) -> None:
    typer.echo(f"[x] {message}")


@app.command("init")
def init_command(
    directory: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True),
    agent_command: str | None = typer.Option(None, "--agent-command"),
    source_url: str | None = typer.Option(None, "--source-url"),
    source_name: str | None = typer.Option(None, "--source-name"),
    authority: float = typer.Option(0.9, "--authority"),
    eval_count: int = typer.Option(3, "--eval-count"),
    runs_per_eval: int = typer.Option(3, "--runs-per-eval"),
    timeout: int = typer.Option(20, "--timeout"),
    github_action: bool = typer.Option(False, "--github-action"),
    force: bool = typer.Option(False, "--force"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Initialize Stale AI inside an agent repository."""
    try:
        repo = _resolve_repo(directory)
        if agent_command is None or source_url is None or source_name is None:
            (
                agent_command,
                source_name,
                source_url,
                authority,
                eval_count,
                runs_per_eval,
                timeout,
                github_action,
            ) = _prompt_init_values(
                agent_command,
                source_name,
                source_url,
                authority,
                eval_count,
                runs_per_eval,
                timeout,
                github_action,
            )
        assert agent_command is not None
        assert source_name is not None
        assert source_url is not None

        config = _build_config(
            agent_command=agent_command,
            source_name=source_name,
            source_url=source_url,
            authority=authority,
            eval_count=eval_count,
            runs_per_eval=runs_per_eval,
            timeout=timeout,
        )

        typer.echo(f"Repository: {repo}")
        typer.echo(f"Agent command: {' '.join(config.agent.command)}")
        typer.echo(f"Trusted source: {config.sources[0].name} ({config.sources[0].url})")
        typer.echo(f"Evaluations: {config.evaluations.count} x {config.evaluations.runs_per_eval}")
        typer.echo(f"GitHub Action: {'yes' if github_action else 'no'}")

        result = initialize_project(
            repo=repo,
            config=config,
            create_github_action=github_action,
            force=force,
        )
        _ok("Created staleai.yaml")
        for source in result.captured_sources:
            _ok(f"Captured baseline for {source}")
        _ok("Created .staleai/snapshots.json")
        if result.github_action_path:
            _ok("Created GitHub workflow")
        typer.echo("")
        typer.echo("Next:")
        typer.echo("  staleai check")
    except (ConfigError, PipelineError, ValueError) as exc:
        _print_error(str(exc), verbose, exc)
        raise typer.Exit(code=2) from exc


@app.command("check")
def check_command(
    directory: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run a Stale AI freshness check for the current repository."""
    try:
        repo = _resolve_repo(directory)
        config = load_config(repo)
        report = run_freshness_check(repo, config)
    except (ConfigError, PipelineError, ValueError) as exc:
        _print_error(str(exc), verbose, exc)
        raise typer.Exit(code=2) from exc
    except Exception as exc:  # noqa: BLE001
        _print_error("Unexpected pipeline error.", verbose, exc)
        raise typer.Exit(code=2) from exc

    typer.echo("Stale AI")
    typer.echo("")
    for source in report.sources:
        if source.status == "unchanged":
            _ok(f"{source.name}: source fetched")
        elif source.status == "changed_ignored":
            _warn(f"{source.name}: trusted source changed, no material agent impact detected")
        elif source.status == "changed_review":
            _warn(f"{source.name}: trusted source changed and requires review")
            if source.scan is not None:
                _ok(f"Found {source.scan.reference_count} potentially affected references")
        elif source.status == "changed_passed":
            _warn(f"{source.name}: trusted source changed")
            _ok("Analyzed documentation change")
            if source.scan is not None:
                _ok(f"Found {source.scan.reference_count} potentially affected references")
            if source.evaluation_results is not None:
                _ok(f"Agent passed all {len(source.evaluation_results.results)} regression evaluations")
        elif source.status == "stale":
            _warn(f"{source.name}: trusted source changed")
            _ok("Analyzed documentation change")
            if source.scan is not None:
                _ok(f"Found {source.scan.reference_count} potentially affected references")
                if source.scan.impacted_files:
                    typer.echo("")
                    typer.echo("Potentially stale:")
                    for file_path in source.scan.impacted_files[:10]:
                        typer.echo(f"  {file_path}")
            if source.evaluation_results is not None:
                _fail(
                    f"Agent failed {source.evaluation_results.failed} of "
                    f"{len(source.evaluation_results.results)} regression evaluations"
                )
        else:
            _fail(f"{source.name}: {source.error or 'source check failed'}")

    typer.echo("")
    typer.echo(f"Result: {report.status.upper()}")
    typer.echo(f"Report: {Path(report.latest_report_path).relative_to(repo)}")
    if json_output:
        typer.echo("")
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    raise typer.Exit(code=_status_to_exit_code(report.status))


@app.command("accept")
def accept_command(
    directory: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True),
    yes: bool = typer.Option(False, "--yes"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Accept pending source versions as the new trusted baseline."""
    try:
        repo = _resolve_repo(directory)
        pending_file = repo / ".staleai" / "pending.json"
        if not pending_file.exists() or not json.loads(pending_file.read_text(encoding="utf-8") or "{}"):
            raise PipelineError("No pending source updates found.")
        if not yes and not typer.confirm(
            f"Accept pending source updates as the new trusted baseline?", default=False
        ):
            raise typer.Exit(code=0)
        result = accept_pending_sources(repo)
    except typer.Exit:
        raise
    except (ConfigError, PipelineError, ValueError, json.JSONDecodeError) as exc:
        _print_error(str(exc), verbose, exc)
        raise typer.Exit(code=2) from exc

    for source in result.accepted_sources:
        _ok(f"Accepted {source['name']} ({source['sha']})")
    typer.echo(f"Updated baseline: {Path(result.snapshots_path).relative_to(repo)}")


def main() -> None:
    """Run the Typer application."""
    app()


if __name__ == "__main__":
    main()
