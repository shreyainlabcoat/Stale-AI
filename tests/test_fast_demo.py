from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import settings
from app.analyzer import analyze
from app.evals import run_evaluations
from app.main import app
from app.models import AnalyzeRequest, Evaluation


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def _sample_evaluation() -> Evaluation:
    return Evaluation(
        id="eval-1",
        name="Smoke test",
        prompt="Describe the current behavior.",
        rationale="Fast demo mode smoke test.",
    )


def test_fast_demo_disabled_by_default(monkeypatch):
    monkeypatch.delenv("STALEAI_FAST_DEMO", raising=False)
    monkeypatch.delenv("STALEAI_SEMANTIC_JUDGE", raising=False)
    assert settings.fast_demo_enabled() is False
    assert settings.semantic_judge_enabled() is True


def test_semantic_judge_can_be_disabled_independently(monkeypatch):
    monkeypatch.delenv("STALEAI_FAST_DEMO", raising=False)
    monkeypatch.setenv("STALEAI_SEMANTIC_JUDGE", "false")
    assert settings.fast_demo_enabled() is False
    assert settings.semantic_judge_enabled() is False


def test_fast_demo_always_disables_semantic_judge(monkeypatch):
    monkeypatch.setenv("STALEAI_FAST_DEMO", "true")
    monkeypatch.setenv("STALEAI_SEMANTIC_JUDGE", "true")
    assert settings.semantic_judge_enabled() is False


def test_fast_demo_forces_single_run_and_skips_judge(monkeypatch):
    monkeypatch.setenv("STALEAI_FAST_DEMO", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    change = analyze(
        AnalyzeRequest(
            source_name="Current documentation",
            old_text="Use alpha mode.",
            new_text="Use beta mode.",
            source_authority=0.9,
        )
    ).change
    result = run_evaluations(
        repo_path="sample_target",
        agent_script="agent.py",
        evaluations=[_sample_evaluation()],
        change=change,
        timeout_seconds=15,
        runs_per_eval=3,
    )
    assert result.fast_demo_mode is True
    assert result.results[0].total_runs == 1
    assert result.results[0].judge_passed is None


def test_normal_mode_preserves_requested_runs(monkeypatch):
    monkeypatch.delenv("STALEAI_FAST_DEMO", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = run_evaluations(
        repo_path="sample_target",
        agent_script="agent.py",
        evaluations=[_sample_evaluation()],
        change=None,
        timeout_seconds=15,
        runs_per_eval=2,
    )
    assert result.fast_demo_mode is False
    assert result.results[0].total_runs == 2


def test_api_config_reports_fast_demo_state(monkeypatch):
    monkeypatch.setenv("STALEAI_FAST_DEMO", "true")
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["fast_demo"] is True
    assert payload["semantic_judge"] is False


def test_openai_sample_agent_skips_live_call_in_fast_demo_mode():
    agent_script = ROOT / "sample_target_openai" / "agent.py"
    completed = subprocess.run(
        [sys.executable, str(agent_script), "Show a chat completion example."],
        cwd=agent_script.parent,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            **__import__("os").environ,
            "STALEAI_FAST_DEMO": "true",
            "OPENAI_API_KEY": "sk-test-not-a-real-key",
        },
    )
    assert completed.returncode == 0
    assert "```python" in completed.stdout
    assert "live agent error" not in completed.stdout
