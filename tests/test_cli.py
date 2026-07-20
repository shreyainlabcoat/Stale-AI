from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.config import ConfigError, StaleAIConfig, load_config
from app.evals import build_agent_command, run_evaluations
from app.models import Evaluation
from app.pipeline import accept_pending_sources, pending_path, snapshots_path


runner = CliRunner()
OLD_TEXT = "Use legacy_client.create for completions."
NEW_TEXT = (
    "legacy_client.create is deprecated, removed, and replaced. "
    "Use modern_client.create for completions."
)


def _fetched(url: str, text: str, fetched_at: str = "2026-07-19T00:00:00+00:00") -> dict[str, str]:
    return {
        "url": url,
        "text": text,
        "sha": __import__("app.sources", fromlist=["content_sha"]).content_sha(text),
        "fetched_at": fetched_at,
    }


def _write_agent(repo: Path, mode: str = "pass") -> None:
    output = "modern_client.create" if mode == "pass" else "legacy_client.create"
    (repo / "agent.py").write_text(
        "import sys\n"
        f"print({output!r})\n",
        encoding="utf-8",
    )
    (repo / "sdk_notes.md").write_text(
        "Legacy usage: legacy_client.create\n",
        encoding="utf-8",
    )


def _init_repo(monkeypatch, tmp_path: Path, *, github_action: bool = False, repo_name: str = "repo") -> Path:
    repo = tmp_path / repo_name
    repo.mkdir()
    _write_agent(repo)
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, OLD_TEXT))
    result = runner.invoke(
        app,
        [
            "init",
            str(repo),
            "--agent-command",
            'python agent.py "{prompt}"',
            "--source-url",
            "https://example.invalid/docs",
            "--source-name",
            "OpenAI Python SDK",
            "--authority",
            "1.0",
            "--eval-count",
            "3",
            "--runs-per-eval",
            "3",
            "--timeout",
            "20",
            *(["--github-action"] if github_action else []),
        ],
    )
    assert result.exit_code == 0, result.output
    return repo


def test_valid_config_parses(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "staleai.yaml").write_text(
        "version: 1\n"
        "agent:\n"
        "  command:\n"
        "    - python\n"
        "    - agent.py\n"
        '    - "{prompt}"\n'
        "  timeout_seconds: 20\n"
        "sources:\n"
        "  - name: OpenAI Python SDK\n"
        "    url: https://example.invalid/docs\n"
        "    authority: 1.0\n"
        "evaluations:\n"
        "  count: 3\n"
        "  runs_per_eval: 3\n"
        "repair:\n"
        "  enabled: false\n"
        "  require_approval: true\n",
        encoding="utf-8",
    )
    config = load_config(repo)
    assert isinstance(config, StaleAIConfig)
    assert config.agent.command[-1] == "{prompt}"


def test_invalid_config_produces_useful_error(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "staleai.yaml").write_text(
        "version: 2\nagent:\n  command: []\nsources: []\n",
        encoding="utf-8",
    )
    try:
        load_config(repo)
    except ConfigError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected ConfigError")
    assert "version" in message
    assert "sources" in message


def test_agent_command_must_contain_prompt(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "staleai.yaml").write_text(
        "version: 1\n"
        "agent:\n"
        "  command:\n"
        "    - python\n"
        "    - agent.py\n"
        "  timeout_seconds: 20\n"
        "sources:\n"
        "  - name: Docs\n"
        "    url: https://example.invalid/docs\n"
        "    authority: 1.0\n",
        encoding="utf-8",
    )
    try:
        load_config(repo)
    except ConfigError as exc:
        assert "{prompt}" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_init_creates_config_and_snapshots(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    assert (repo / "staleai.yaml").exists()
    assert (repo / ".staleai" / "snapshots.json").exists()


def test_init_github_action_creates_workflow(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path, github_action=True)
    assert (repo / ".github" / "workflows" / "staleai.yml").exists()


def test_init_does_not_overwrite_without_force(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        [
            "init",
            str(repo),
            "--agent-command",
            'python agent.py "{prompt}"',
            "--source-url",
            "https://example.invalid/docs",
            "--source-name",
            "OpenAI Python SDK",
        ],
    )
    assert result.exit_code == 2
    assert "Configuration already exists" in result.output


def test_check_exits_zero_when_source_unchanged(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, OLD_TEXT))
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code == 0
    assert "Result: FRESH" in result.output


def test_check_exits_zero_when_changed_evals_pass(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, NEW_TEXT, "2026-07-19T00:05:00+00:00"))
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code == 0
    assert "Result: PASSED" in result.output


def test_check_exits_one_when_evaluations_fail(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    _write_agent(repo, mode="fail")
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, NEW_TEXT, "2026-07-19T00:05:00+00:00"))
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code == 1
    assert "Result: STALE" in result.output


def test_check_exits_two_for_invalid_configuration(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "staleai.yaml").write_text("version: 1\nsources: []\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code == 2
    assert "Invalid configuration" in result.output


def test_check_does_not_update_approved_snapshot(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    original = json.loads(snapshots_path(repo).read_text(encoding="utf-8"))
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, NEW_TEXT, "2026-07-19T00:05:00+00:00"))
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code in {0, 1}
    current = json.loads(snapshots_path(repo).read_text(encoding="utf-8"))
    assert current == original


def test_check_writes_changed_content_to_pending(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, NEW_TEXT, "2026-07-19T00:05:00+00:00"))
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code in {0, 1}
    pending = json.loads(pending_path(repo).read_text(encoding="utf-8"))
    assert pending["https://example.invalid/docs"]["sha"] != json.loads(
        snapshots_path(repo).read_text(encoding="utf-8")
    )["https://example.invalid/docs"]["sha"]


def test_accept_updates_approved_snapshot(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, NEW_TEXT, "2026-07-19T00:05:00+00:00"))
    assert runner.invoke(app, ["check", str(repo)]).exit_code in {0, 1}
    before = json.loads(snapshots_path(repo).read_text(encoding="utf-8"))
    pending_before = json.loads(pending_path(repo).read_text(encoding="utf-8"))
    result = runner.invoke(app, ["accept", str(repo), "--yes"])
    after = json.loads(snapshots_path(repo).read_text(encoding="utf-8"))
    pending_after = json.loads(pending_path(repo).read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert before != after
    assert after["https://example.invalid/docs"]["sha"] == pending_before["https://example.invalid/docs"]["sha"]
    assert pending_after == {}


def test_accept_preserves_unrelated_baselines(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".staleai").mkdir()
    snapshots = {
        "https://one.invalid": {"label": "One", "sha": "a", "url": "https://one.invalid"},
        "https://two.invalid": {"label": "Two", "sha": "b", "url": "https://two.invalid"},
    }
    pending = {
        "https://one.invalid": {"label": "One", "sha": "c", "url": "https://one.invalid"}
    }
    snapshots_path(repo).write_text(json.dumps(snapshots), encoding="utf-8")
    pending_path(repo).write_text(json.dumps(pending), encoding="utf-8")
    result = accept_pending_sources(repo)
    updated = json.loads(snapshots_path(repo).read_text(encoding="utf-8"))
    assert result.accepted_sources[0]["sha"] == "c"
    assert updated["https://one.invalid"]["sha"] == "c"
    assert updated["https://two.invalid"]["sha"] == "b"


def test_generic_agent_command_substitutes_prompt_correctly():
    command = build_agent_command(["python", "agent.py", "{prompt}"], "hello world")
    assert command == ["python", "agent.py", "hello world"]


def test_commands_execute_without_shell(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("print('ok')\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "modern_client.create"
        stderr = ""

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr("app.evals.subprocess.run", fake_run)
    run_evaluations(
        repo_path=str(repo),
        agent_script="agent.py",
        evaluations=[Evaluation(id="1", name="n", prompt="hello", rationale="r")],
        change=None,
        timeout_seconds=10,
        runs_per_eval=1,
        agent_command=["python", "agent.py", "{prompt}"],
        base_dir=repo.parent,
    )
    assert captured["kwargs"]["shell"] is False
    assert captured["args"][0] == ["python", "agent.py", "hello"]


def test_paths_with_spaces_work(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path, repo_name="repo with spaces")
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, OLD_TEXT))
    result = runner.invoke(app, ["check", str(repo)])
    assert result.exit_code == 0


def test_json_report_does_not_include_api_keys(monkeypatch, tmp_path: Path):
    repo = _init_repo(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    monkeypatch.setattr("app.pipeline.fetch", lambda url: _fetched(url, OLD_TEXT))
    result = runner.invoke(app, ["check", str(repo), "--json"])
    assert result.exit_code == 0
    report_text = (repo / ".staleai" / "reports" / "latest.json").read_text(encoding="utf-8")
    assert "super-secret" not in report_text
