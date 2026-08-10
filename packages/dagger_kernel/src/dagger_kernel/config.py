"""Dagger configuration model.

Pydantic model for the `dagger.yaml` schema. Loads from a path and gives readable
errors on missing/extra fields. YAML parsing is delegated to the caller (CLI) so
the kernel itself has no hard YAML dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentBackendConfig(BaseModel):
    """Agent backend configuration. `backend` selects which implementation to load."""

    model_config = ConfigDict(extra="allow")

    backend: str = Field(description="Backend key: mock | opencode-http | claude-code")
    timeout: int = Field(default=14400, ge=1)
    max_retries: int = Field(default=3, ge=0)


class DomainConfig(BaseModel):
    """Per-domain overrides, keyed by domain id."""

    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(default_factory=list)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DaggerConfig(BaseModel):
    """Top-level Dagger configuration."""

    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Field(default=Path(".dagger"), description="State root for all runs.")
    workspaces_dir: Path = Field(
        default=Path(".dagger/workspaces"), description="Where WorkspaceProvider roots go."
    )
    concurrency: int = Field(default=2, ge=1)
    keep_scratch: bool = Field(default=False)
    agent: AgentBackendConfig = Field(default_factory=lambda: AgentBackendConfig(backend="mock"))
    domains: DomainConfig = Field(default=DomainConfig())

    @field_validator("data_dir", "workspaces_dir")
    @classmethod
    def _coerce_path(cls, v: Path) -> Path:
        return v

    def resolved_paths(self, base: Path | None = None) -> tuple[Path, Path]:
        """Return absolute (data_dir, workspaces_dir) anchored at `base` (default: cwd)."""
        anchor = base or Path.cwd()
        d = self.data_dir if self.data_dir.is_absolute() else anchor / self.data_dir
        w = (
            self.workspaces_dir
            if self.workspaces_dir.is_absolute()
            else anchor / self.workspaces_dir
        )
        return d, w


def load_config_from_dict(data: dict[str, Any]) -> DaggerConfig:
    """Construct a DaggerConfig from a parsed mapping. Raises pydantic.ValidationError on bad input."""
    return DaggerConfig.model_validate(data)


__all__ = ["AgentBackendConfig", "DomainConfig", "DaggerConfig", "load_config_from_dict"]
