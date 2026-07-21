from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from app.config import StaleAIConfig


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = ROOT / "examples" / "github-audit-log-demo"
AGENT_DIR = DEMO_ROOT / "agent"
PROMPT = "How should I retrieve the audit log for a GitHub organization?"


def _run_agent(script_name: str, prompt: str = PROMPT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, script_name, prompt],
        cwd=AGENT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def test_stale_agent_recommends_graphql():
    completed = _run_agent("agent.py")
    assert completed.returncode == 0
    assert "GraphQL" in completed.stdout


def test_stale_agent_contains_deprecated_identifiers():
    completed = _run_agent("agent.py")
    assert "organization.auditLog" in completed.stdout
    assert "actorLogin" in completed.stdout


def test_repaired_agent_recommends_rest_endpoint():
    completed = _run_agent("repaired_agent.py")
    assert completed.returncode == 0
    assert "REST" in completed.stdout
    assert "GET /orgs/{org}/audit-log" in completed.stdout


def test_repaired_agent_does_not_contain_deprecated_identifiers():
    completed = _run_agent("repaired_agent.py")
    assert "organization.auditLog" not in completed.stdout
    assert "actorLogin" not in completed.stdout


def test_both_agents_accept_prompt_argument():
    stale = _run_agent("agent.py", "How should I retrieve the audit log for a GitHub organization?")
    repaired = _run_agent("repaired_agent.py", "How should I retrieve the audit log for a GitHub organization?")
    assert stale.returncode == 0
    assert repaired.returncode == 0


def test_validate_demo_script_exits_successfully():
    completed = subprocess.run(
        [sys.executable, str(DEMO_ROOT / "validate_demo.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "Demo validation passed." in completed.stdout


def test_staleai_yaml_example_matches_schema():
    config_text = (DEMO_ROOT / "staleai.yaml.example").read_text(encoding="utf-8")
    config_text = config_text.replace(
        "https://raw.githubusercontent.com/YOUR_USERNAME/staleai-github-source/main/audit-log.md",
        "https://example.invalid/audit-log.md",
    )
    config = yaml.safe_load(config_text)
    validated = StaleAIConfig.model_validate(config)
    assert validated.agent.command == ["python", "agent.py", "{prompt}"]
    assert validated.sources[0].authority == 1.0
