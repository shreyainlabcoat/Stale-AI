from __future__ import annotations

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    cosmetic = "cosmetic"
    clarification = "clarification"
    new_feature = "new_feature"
    deprecation = "deprecation"
    breaking_change = "breaking_change"
    rename = "rename"
    behavioral_change = "behavioral_change"
    unknown = "unknown"


class ChangeCard(BaseModel):
    title: str
    summary: str
    change_type: ChangeType
    old_behavior: str
    new_behavior: str
    migration_guidance: str
    affected_terms: list[str] = Field(default_factory=list)
    deprecated_terms: list[str] = Field(default_factory=list)
    replacement_terms: list[str] = Field(default_factory=list)
    explicit_breaking_signal: float = Field(ge=0, le=1)
    semantic_materiality: float = Field(ge=0, le=1)
    source_authority: float = Field(ge=0, le=1)
    testability: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class AnalyzeRequest(BaseModel):
    source_name: str = "Official documentation"
    source_url: str | None = None
    old_text: str
    new_text: str
    source_authority: float = Field(default=0.9, ge=0, le=1)


class AnalyzeResponse(BaseModel):
    change: ChangeCard
    textual_change_ratio: float = Field(ge=0, le=1)
    danger_score: float = Field(ge=0, le=1)
    decision: Literal["ignore", "review", "generate_evals"]
    raw_diff: list[str]
    used_model: bool


class RepoMatch(BaseModel):
    file: str
    line: int
    text: str
    matched_term: str


class ScanRequest(BaseModel):
    repo_path: str
    change: ChangeCard


class TrackRequest(BaseModel):
    url: str
    label: str | None = None
    authority: float = Field(default=0.9, ge=0, le=1)


class TrackResponse(BaseModel):
    url: str
    label: str
    sha: str
    preview: str
    fetched_at: str


class CheckResponse(BaseModel):
    changed: bool
    url: str
    old_sha: str
    new_sha: str
    analysis: "AnalyzeResponse | None" = None
    old_text: str | None = None
    new_text: str | None = None


class ScanResponse(BaseModel):
    matches: list[RepoMatch]
    impacted_files: list[str]
    reference_count: int
    repository_impact: float = Field(ge=0, le=1)
    adjusted_score: float = Field(ge=0, le=1)
    decision: Literal["ignore", "review", "generate_evals"]


class Evaluation(BaseModel):
    id: str
    name: str
    prompt: str
    required_substrings: list[str] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)
    rationale: str


class GenerateEvalsRequest(BaseModel):
    change: ChangeCard
    matches: list[RepoMatch] = Field(default_factory=list)
    count: int = Field(default=3, ge=1, le=6)


class GenerateEvalsResponse(BaseModel):
    evaluations: list[Evaluation]
    used_model: bool


class RunEvalsRequest(BaseModel):
    repo_path: str
    agent_script: str = "agent.py"
    evaluations: list[Evaluation]
    change: ChangeCard | None = None
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    runs_per_eval: int = Field(default=1, ge=1, le=10)


class EvalResult(BaseModel):
    evaluation_id: str
    name: str
    passed: bool
    output: str
    missing_required: list[str]
    found_forbidden: list[str]
    judge_passed: bool | None = None
    judge_reason: str | None = None
    passed_runs: int = 0
    total_runs: int = 1
    pass_rate: float = Field(default=0, ge=0, le=1)
    wilson_low: float = Field(default=0, ge=0, le=1)
    wilson_high: float = Field(default=0, ge=0, le=1)
    brier_score: float = Field(default=0, ge=0, le=1)
    error: str | None = None


class RunEvalsResponse(BaseModel):
    passed: int
    failed: int
    pass_rate: float = Field(default=0, ge=0, le=1)
    average_brier_score: float = Field(default=0, ge=0, le=1)
    results: list[EvalResult]


class RepairRequest(BaseModel):
    repo_path: str
    change: ChangeCard
    failures: list[EvalResult]
    matches: list[RepoMatch] = Field(default_factory=list)
    run_codex: bool = True


class RepairResponse(BaseModel):
    status: Literal["patched", "plan_only", "codex_unavailable", "failed"]
    message: str
    codex_output: str = ""
    git_diff: str = ""
