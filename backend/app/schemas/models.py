"""Public API models (requests, responses, events)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import InvalidRepositoryURL
from app.core.security import parse_github_url


def utcnow() -> datetime:
    return datetime.now(UTC)


class ValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    INCONCLUSIVE = "inconclusive"


class InvestigationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


Stage = Literal["queued", "clone", "analyze", "retrieve", "plan", "diagnose", "patch", "validate", "finalize"]
EventStatus = Literal["started", "completed", "failed", "info"]


# --- Request -----------------------------------------------------------------------------------------

class RepairRequest(BaseModel):
    repository_url: str = Field(min_length=1, max_length=300)
    bug_description: str = Field(min_length=10, max_length=4000)
    stack_trace: str | None = Field(default=None, max_length=8000)

    @field_validator("repository_url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        try:
            owner, repo = parse_github_url(value)
        except InvalidRepositoryURL as exc:
            raise ValueError(exc.message) from None
        return f"https://github.com/{owner}/{repo}"

    @field_validator("bug_description")
    @classmethod
    def _strip_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Describe the bug in at least 10 characters.")
        return value

    @field_validator("stack_trace")
    @classmethod
    def _blank_trace_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


# --- Repository ---------------------------------------------------------------------------------------

class RepositoryInfo(BaseModel):
    url: str
    owner: str
    name: str
    description: str | None = None
    default_branch: str | None = None
    commit_sha: str | None = None
    stars: int | None = None
    size_kb: int | None = None
    primary_language: str | None = None
    languages: dict[str, int] = Field(default_factory=dict, description="Source file count per language")
    source_file_count: int = 0
    manifests: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    tree_summary: str = ""
    supported: bool = False
    support_note: str = ""


# --- Result -------------------------------------------------------------------------------------------

class Evidence(BaseModel):
    file: str
    start_line: int
    end_line: int
    snippet: str = Field(description="Actual lines read from the repository")
    explanation: str
    verified: bool = Field(description="True when the model's quoted code was found at the cited location")


class Hypothesis(BaseModel):
    title: str
    explanation: str
    likelihood: Literal["high", "medium", "low"] = "medium"
    selected: bool = False
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)


class RelevantFile(BaseModel):
    path: str
    reason: str
    lines: list[int] = Field(default_factory=list, description="Notable line numbers")


class FileChange(BaseModel):
    path: str
    explanation: str
    additions: int
    deletions: int
    original_content: str | None = None
    patched_content: str | None = None


class RegressionTest(BaseModel):
    path: str
    description: str
    content: str
    executed: bool = False


class TestRun(BaseModel):
    __test__ = False  # not a pytest class

    label: Literal["baseline", "patched"]
    command: list[str]
    exit_code: int | None
    timed_out: bool = False
    duration_seconds: float = 0
    output: str = ""
    output_truncated: bool = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    failed_tests: list[str] = Field(default_factory=list)


class Validation(BaseModel):
    status: ValidationStatus = ValidationStatus.NOT_RUN
    summary: str = "Validation was not run."
    reason: str | None = None
    bug_reproduced: bool | None = Field(
        default=None, description="True when the pre-patch run failed and the patched run passed"
    )
    scope: Literal["full_suite", "targeted"] | None = Field(
        default=None,
        description="full_suite: the whole suite passes. targeted: the previously failing tests now pass and nothing "
        "regressed, but unrelated failures that already existed remain.",
    )
    fixed_tests: list[str] = Field(default_factory=list, description="Tests that failed before the patch and pass after it")
    pre_existing_failures: int = Field(default=0, description="Failures present both before and after the patch")
    runs: list[TestRun] = Field(default_factory=list)


class Attempt(BaseModel):
    iteration: int
    outcome: str
    detail: str = ""


class RepairResult(BaseModel):
    outcome: Literal["patch_proposed", "insufficient_evidence", "no_valid_patch"]
    root_cause: str
    confidence: Literal["high", "medium", "low"]
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    relevant_files: list[RelevantFile] = Field(default_factory=list)
    changes: list[FileChange] = Field(default_factory=list)
    diff: str = ""
    regression_test: RegressionTest | None = None
    validation: Validation = Field(default_factory=Validation)
    risks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    llm_model: str = ""


# --- Investigation -----------------------------------------------------------------------------------

class InvestigationEvent(BaseModel):
    seq: int
    timestamp: datetime
    stage: Stage
    status: EventStatus
    message: str
    detail: dict[str, str | int | float | bool | None] | None = None


class ErrorInfo(BaseModel):
    code: str
    message: str
    stage: Stage | None = None


class Investigation(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    status: InvestigationStatus
    created_at: datetime
    updated_at: datetime
    repository_url: str
    bug_description: str
    stack_trace: str | None = None
    repository: RepositoryInfo | None = None
    result: RepairResult | None = None
    error: ErrorInfo | None = None
    events: list[InvestigationEvent] = Field(default_factory=list)


class RepairAccepted(BaseModel):
    repair_id: str
    status: InvestigationStatus
    status_url: str
    events_url: str


class ErrorBody(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
