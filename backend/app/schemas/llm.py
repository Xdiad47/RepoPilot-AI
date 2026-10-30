"""Shapes the LLM must return. Every field is validated; anything malformed is rejected, not trusted."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- Step 1: plan ---------------------------------------------------------------------------------------

class PlanHypothesis(_Lenient):
    title: str = Field(max_length=200)
    reasoning: str = Field(default="", max_length=1500)


class PlanResponse(_Lenient):
    understanding: str = Field(max_length=2000)
    hypotheses: list[PlanHypothesis] = Field(default_factory=list, max_length=6)
    search_terms: list[str] = Field(default_factory=list, max_length=15)
    files_to_inspect: list[str] = Field(default_factory=list, max_length=10)
    research_queries: list[str] = Field(default_factory=list, max_length=6)


# --- Step 2: diagnosis ------------------------------------------------------------------------------------

class EvidenceIn(_Lenient):
    file: str = Field(max_length=300)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(max_length=2000, description="Exact code copied from the file")
    explanation: str = Field(default="", max_length=1000)


class HypothesisIn(_Lenient):
    title: str = Field(max_length=200)
    explanation: str = Field(default="", max_length=1500)
    likelihood: Literal["high", "medium", "low"] = "medium"
    evidence_for: list[str] = Field(default_factory=list, max_length=6)
    evidence_against: list[str] = Field(default_factory=list, max_length=6)


class ResearchNoteIn(_Lenient):
    source_id: str = Field(max_length=20)
    relevance: str = Field(default="", max_length=600, description="How this source relates to the code that was shown")


class DiagnosisResponse(_Lenient):
    root_cause: str = Field(max_length=3000)
    confidence: Literal["high", "medium", "low"] = "low"
    hypotheses: list[HypothesisIn] = Field(default_factory=list, max_length=6)
    selected_hypothesis: str = Field(default="", max_length=200)
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=12)
    files_to_modify: list[str] = Field(default_factory=list, max_length=8)
    needs_more_context: list[str] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=8)
    research_summary: str = Field(default="", max_length=1500)
    research_notes: list[ResearchNoteIn] = Field(default_factory=list, max_length=10)


# --- Step 3: patch ----------------------------------------------------------------------------------------

class EditIn(_Lenient):
    path: str = Field(max_length=300)
    search: str = Field(min_length=1, max_length=20000, description="Exact existing text; must appear once")
    replace: str = Field(max_length=20000)
    explanation: str = Field(default="", max_length=800)


class RegressionTestIn(_Lenient):
    description: str = Field(default="", max_length=500)
    content: str = Field(max_length=8000)


class PatchResponse(_Lenient):
    edits: list[EditIn] = Field(default_factory=list, max_length=8)
    regression_test: RegressionTestIn | None = None
    risks: list[str] = Field(default_factory=list, max_length=8)
    cannot_fix_reason: str = Field(default="", max_length=1000)
