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
    GenerateEvalsRequest,
    GenerateEvalsResponse,
    RepairRequest,
    RepairResponse,
    RunEvalsRequest,
    RunEvalsResponse,
    ScanRequest,
    ScanResponse,
)
from .scanner import scan_repository

load_dotenv()

app = FastAPI(title="DriftFix MVP", version="0.1.0")
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
