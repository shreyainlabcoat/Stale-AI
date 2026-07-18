from __future__ import annotations

import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .analyzer import analyze
from .codex_runner import repair_with_codex
from .evals import generate_evaluations, run_evaluations
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    CheckResponse,
    GenerateEvalsRequest,
    GenerateEvalsResponse,
    RepairRequest,
    RepairResponse,
    RunEvalsRequest,
    RunEvalsResponse,
    ScanRequest,
    ScanResponse,
    TrackRequest,
    TrackResponse,
)
from .scanner import scan_repository
from .sources import fetch, get_snapshot, put_snapshot

load_dotenv()

app = FastAPI(title="Stale AI", version="0.1.0")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (PROJECT_ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_route(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return analyze(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/sources/track", response_model=TrackResponse)
def track_source(req: TrackRequest) -> TrackResponse:
    try:
        fetched = fetch(req.url)
        label = req.label or req.url
        put_snapshot(
            req.url,
            label=label,
            authority=req.authority,
            text=fetched["text"],
            sha=fetched["sha"],
            fetched_at=fetched["fetched_at"],
        )
        return TrackResponse(
            url=req.url,
            label=label,
            sha=fetched["sha"],
            preview=fetched["text"][:500],
            fetched_at=fetched["fetched_at"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/sources/check", response_model=CheckResponse)
def check_source(req: TrackRequest) -> CheckResponse:
    snapshot = get_snapshot(req.url)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No tracked snapshot found for URL.")

    try:
        fetched = fetch(req.url)
        old_sha = str(snapshot["sha"])
        new_sha = fetched["sha"]
        if old_sha == new_sha:
            return CheckResponse(
                changed=False,
                url=req.url,
                old_sha=old_sha,
                new_sha=new_sha,
                analysis=None,
            )

        analysis = analyze(
            AnalyzeRequest(
                source_name=str(snapshot["label"]),
                source_url=req.url,
                old_text=str(snapshot["text"]),
                new_text=fetched["text"],
                source_authority=float(snapshot["authority"]),
            )
        )
        put_snapshot(
            req.url,
            label=str(snapshot["label"]),
            authority=float(snapshot["authority"]),
            text=fetched["text"],
            sha=new_sha,
            fetched_at=fetched["fetched_at"],
        )
        return CheckResponse(
            changed=True,
            url=req.url,
            old_sha=old_sha,
            new_sha=new_sha,
            analysis=analysis,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/scan", response_model=ScanResponse)
def scan_route(req: ScanRequest) -> ScanResponse:
    try:
        return scan_repository(req.repo_path, req.change)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/generate-evals", response_model=GenerateEvalsResponse)
def evals_route(req: GenerateEvalsRequest) -> GenerateEvalsResponse:
    try:
        return generate_evaluations(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/run-evals", response_model=RunEvalsResponse)
def run_evals_route(req: RunEvalsRequest) -> RunEvalsResponse:
    try:
        return run_evaluations(
            repo_path=req.repo_path,
            agent_script=req.agent_script,
            evaluations=req.evaluations,
            change=req.change,
            timeout_seconds=req.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/repair", response_model=RepairResponse)
def repair_route(req: RepairRequest) -> RepairResponse:
    try:
        return repair_with_codex(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/reset-sample")
def reset_sample() -> dict[str, str]:
    source = PROJECT_ROOT / "sample_target" / "original_agent.py"
    target = PROJECT_ROOT / "sample_target" / "agent.py"
    shutil.copyfile(source, target)
    return {"status": "reset"}
