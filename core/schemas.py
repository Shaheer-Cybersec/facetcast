"""
schemas - the data shapes every agent agrees on.

Evidence is the spine of Facetcast: every factual claim about a project must carry
the file and the commit (or content hash) it came from. core/evidence.py checks both
exist in what ingest actually read, with no model involved.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Evidence(BaseModel):
    """One claim, bound to where it came from in the project."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim: str = Field(min_length=1)        # "The installation needs Python 3.10+"
    source_path: str = Field(min_length=1)  # "README.md"
    source_ref: str = Field(min_length=1)   # commit SHA or content hash, e.g. "38ae3eb"

    @field_validator("source_path")
    @classmethod
    def repo_relative(cls, v: str) -> str:
        v = v.replace("\\", "/")            # Windows paths -> repo style
        if v.startswith("/") or ":" in v:
            raise ValueError("source_path must be relative to the project root")
        if ".." in v.split("/"):
            raise ValueError("source_path must not contain '..'")
        return v


class StageRecord(BaseModel):
    """What execute() reports for one agent run. Written to the run log."""
    id: str                                  # "A01"
    agent: str                               # "ingest"
    status: Literal["success", "failed", "skipped", "waiting"]
    duration_ms: int = 0
    error: Optional[str] = None


class Graphic(BaseModel):
    """A card the renderer draws itself (core/graphics.py)."""
    style: Literal["headline", "quote", "stat", "terminal"] = "headline"
    headline: str = Field(min_length=3, max_length=110, description="the one line the image says")
    subline: Optional[str] = Field(default=None, max_length=160)
    stat: Optional[str] = Field(default=None, max_length=24, description="big number or short term for 'stat'")
