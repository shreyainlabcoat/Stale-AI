from pathlib import Path

from fastapi.testclient import TestClient

from app.analyzer import analyze
from app.main import app
from app.models import AnalyzeRequest
from app.scanner import scan_repository
from app.sources import content_sha, normalize


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_analyzer_detects_material_change(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    old = (ROOT / "sample_target" / "docs_v2.txt").read_text()
    new = (ROOT / "sample_target" / "docs_v3.txt").read_text()
    result = analyze(
        AnalyzeRequest(
            source_name="Official SDK docs",
            old_text=old,
            new_text=new,
            source_authority=0.95,
        )
    )
    assert result.decision in {"review", "generate_evals"}
    assert result.change.semantic_materiality >= 0.5


def test_scanner_finds_stale_reference(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    old = (ROOT / "sample_target" / "docs_v2.txt").read_text()
    new = (ROOT / "sample_target" / "docs_v3.txt").read_text()
    change = analyze(
        AnalyzeRequest(
            source_name="Official SDK docs",
            old_text=old,
            new_text=new,
            source_authority=0.95,
        )
    ).change
    scan = scan_repository("sample_target", change)
    assert scan.reference_count > 0
    assert "agent.py" in scan.impacted_files


def test_normalize_and_content_sha_ignore_whitespace_only_changes():
    first = "Alpha\n\nBeta\tGamma"
    second = "  Alpha Beta   Gamma  "
    assert normalize(first) == "Alpha Beta Gamma"
    assert normalize(first) == normalize(second)
    assert content_sha(first) == content_sha(second)


def test_check_source_reports_changed_state(monkeypatch, tmp_path):
    from app import sources

    snapshot_file = tmp_path / "data" / "snapshots.json"
    monkeypatch.setattr(sources, "DATA_DIR", snapshot_file.parent)
    monkeypatch.setattr(sources, "SNAPSHOT_FILE", snapshot_file)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    states = iter(
        [
            {
                "url": "https://example.invalid/source.txt",
                "text": "Current behavior is alpha.",
                "sha": content_sha("Current behavior is alpha."),
                "fetched_at": "2026-07-18T00:00:00+00:00",
            },
            {
                "url": "https://example.invalid/source.txt",
                "text": "Current behavior is alpha.",
                "sha": content_sha("Current behavior is alpha."),
                "fetched_at": "2026-07-18T00:01:00+00:00",
            },
            {
                "url": "https://example.invalid/source.txt",
                "text": "Current behavior is beta.",
                "sha": content_sha("Current behavior is beta."),
                "fetched_at": "2026-07-18T00:02:00+00:00",
            },
        ]
    )
    monkeypatch.setattr("app.main.fetch", lambda url: next(states))

    track_response = client.post(
        "/api/sources/track",
        json={"url": "https://example.invalid/source.txt", "authority": 0.9},
    )
    assert track_response.status_code == 200

    unchanged = client.post(
        "/api/sources/check",
        json={"url": "https://example.invalid/source.txt", "authority": 0.9},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["changed"] is False

    changed = client.post(
        "/api/sources/check",
        json={"url": "https://example.invalid/source.txt", "authority": 0.9},
    )
    assert changed.status_code == 200
    payload = changed.json()
    assert payload["changed"] is True
    assert payload["analysis"] is not None
    assert payload["analysis"]["change"]["new_behavior"]
