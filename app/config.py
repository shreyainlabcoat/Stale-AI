from __future__ import annotations

import os
import shlex
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


CONFIG_FILENAME = "staleai.yaml"


class ConfigError(ValueError):
    """Raised when Stale AI configuration cannot be loaded or validated."""


class AgentConfig(BaseModel):
    command: list[str]
    timeout_seconds: int = Field(default=20, ge=1, le=600)

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: list[str]) -> list[str]:
        if not value or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError("agent.command must be a non-empty list of strings")
        prompt_occurrences = sum(item.count("{prompt}") for item in value)
        if prompt_occurrences != 1:
            raise ValueError('agent.command must contain "{prompt}" exactly once')
        return value


class TrustedSourceConfig(BaseModel):
    name: str
    url: str
    authority: float = Field(default=0.9, ge=0, le=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("source url must start with http:// or https://")
        return value


class EvaluationConfig(BaseModel):
    count: int = Field(default=3, ge=1, le=6)
    runs_per_eval: int = Field(default=3, ge=1, le=10)


class RepairConfig(BaseModel):
    enabled: bool = False
    require_approval: bool = True


class StaleAIConfig(BaseModel):
    version: int = 1
    agent: AgentConfig
    sources: list[TrustedSourceConfig]
    evaluations: EvaluationConfig = Field(default_factory=EvaluationConfig)
    repair: RepairConfig = Field(default_factory=RepairConfig)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("version must be 1")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[TrustedSourceConfig]) -> list[TrustedSourceConfig]:
        if not value:
            raise ValueError("at least one trusted source is required")
        return value

    @model_validator(mode="after")
    def validate_root(self) -> StaleAIConfig:
        if self.evaluations.count < 1 or self.evaluations.runs_per_eval < 1:
            raise ValueError("evaluation settings must be positive")
        return self


def config_path(repo: Path) -> Path:
    """Return the default configuration path for a repository."""
    return repo / CONFIG_FILENAME


def parse_agent_command(command: str) -> list[str]:
    """Parse a shell-like command string into an argument list without executing it."""
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        raise ConfigError(f"Invalid agent command: {exc}") from exc
    normalized: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"}:
            normalized.append(part[1:-1])
        else:
            normalized.append(part)
    return normalized


def load_config(repo: Path) -> StaleAIConfig:
    """Load and validate a repository-local Stale AI configuration."""
    path = config_path(repo)
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path.name}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path.name}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read {path.name}: {exc}") from exc

    try:
        return StaleAIConfig.model_validate(raw)
    except ValidationError as exc:
        messages = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "config"
            messages.append(f"{field}: {error['msg']}")
        raise ConfigError("Invalid configuration:\n" + "\n".join(messages)) from exc


def save_config(repo: Path, config: StaleAIConfig) -> Path:
    """Save a repository-local Stale AI configuration file."""
    path = config_path(repo)
    path.write_text(
        yaml.safe_dump(
            config.model_dump(mode="python"),
            sort_keys=False,
            allow_unicode=False,
        ),
        encoding="utf-8",
    )
    return path
