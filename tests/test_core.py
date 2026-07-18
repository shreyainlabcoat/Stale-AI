from pathlib import Path

from app.analyzer import analyze
from app.models import AnalyzeRequest
from app.scanner import scan_repository


ROOT = Path(__file__).resolve().parents[1]


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
