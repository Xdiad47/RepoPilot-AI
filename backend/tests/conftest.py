"""Shared fixtures: a small buggy Python repo, a scripted fake LLM, and a network-free repository service."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.llm import (
    DiagnosisResponse,
    EditIn,
    EvidenceIn,
    HypothesisIn,
    PatchResponse,
    PlanHypothesis,
    PlanResponse,
    RegressionTestIn,
)
from app.services.repository_service import RepoMetadata, RepositoryService, Workspace

BUGGY_API = '''from .validators import normalize_email


def register(payload):
    email = payload["email"]
    domain = email.split("@")[1]
    return {"email": normalize_email(email), "domain": domain}
'''

VALIDATORS = '''def normalize_email(email):
    return email.strip().lower()
'''

TEST_API = '''from app.api import register


def test_register_ok():
    assert register({"email": "A@B.com"})["domain"] == "B.com"
'''

FILES = {
    "app/__init__.py": "",
    "app/api.py": BUGGY_API,
    "app/validators.py": VALIDATORS,
    "tests/test_api.py": TEST_API,
    "requirements.txt": "pytest\n",
    "README.md": "# demo\n",
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="test-key-0123456789",
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        sandbox_enabled=False,
        max_repair_iterations=3,
        rate_limit_per_hour=3,
        daily_global_limit=100,
    )


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / "fixture_repo"
    for rel, content in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class FakeRepositoryService(RepositoryService):
    """Copies a local fixture instead of cloning from GitHub."""

    def __init__(self, settings: Settings, source: Path, *, size_kb: int = 10) -> None:
        super().__init__(settings)
        self.source = source
        self.size_kb = size_kb

    async def fetch_metadata(self, owner: str, repo: str) -> RepoMetadata:
        return RepoMetadata(owner, repo, "demo repo", "main", 3, self.size_kb, f"https://github.com/{owner}/{repo}", "Python")

    async def clone(self, owner: str, repo: str, workspace: Workspace) -> str:
        shutil.copytree(self.source, workspace.repo_dir)
        return "a" * 40


class ScriptedLLM:
    """Returns pre-baked responses keyed by schema type; records every prompt it receives."""

    def __init__(self, script: dict[type, list]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.prompts: list[tuple[type, str, str]] = []
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.model = "scripted"

    async def complete_json(self, system: str, user: str, schema, **_):
        self.calls += 1
        self.prompts.append((schema, system, user))
        queue = self.script[schema]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def good_plan() -> PlanResponse:
    return PlanResponse(
        understanding="register() crashes when the email is empty.",
        hypotheses=[PlanHypothesis(title="Unchecked split", reasoning="split('@')[1] fails without '@'")],
        search_terms=["register", "email"],
        files_to_inspect=["app/api.py"],
    )


def good_diagnosis(quote: str = 'domain = email.split("@")[1]', line: int = 6) -> DiagnosisResponse:
    return DiagnosisResponse(
        root_cause="register() indexes email.split('@')[1] without checking that the email contains '@'.",
        confidence="high",
        hypotheses=[
            HypothesisIn(title="Unchecked split", explanation="IndexError on empty email", likelihood="high",
                         evidence_for=["split()[1] on empty string"]),
            HypothesisIn(title="Bad normalization", explanation="normalize_email is fine", likelihood="low",
                         evidence_against=["normalize_email only strips and lowercases"]),
        ],
        selected_hypothesis="Unchecked split",
        evidence=[EvidenceIn(file="app/api.py", start_line=line, end_line=line, quote=quote, explanation="crashes here")],
        files_to_modify=["app/api.py"],
        risks=["Callers may rely on the old exception"],
    )


def good_patch(with_test: bool = True) -> PatchResponse:
    return PatchResponse(
        edits=[
            EditIn(
                path="app/api.py",
                search='    domain = email.split("@")[1]\n',
                replace='    if "@" not in email:\n        raise ValueError("invalid email")\n    domain = email.split("@")[1]\n',
                explanation="Reject emails without '@' before splitting.",
            )
        ],
        regression_test=RegressionTestIn(
            description="Empty email must raise ValueError, not IndexError",
            content=(
                "import pytest\nfrom app.api import register\n\n"
                "def test_empty_email_raises_value_error():\n"
                '    with pytest.raises(ValueError):\n        register({"email": ""})\n'
            ),
        )
        if with_test
        else None,
        risks=["Behaviour change for malformed emails"],
    )


# --- shared test doubles ------------------------------------------------------------------------------

from app.schemas.models import RepairResult, TestRun, Validation  # noqa: E402
from app.services.validation_service import PYTEST_COMMAND, SandboxStatus  # noqa: E402


def make_run(label="patched", code=0, failed_tests=None, passed=3, failed=0, errors=0, output="", timed_out=False):
    return TestRun(label=label, command=PYTEST_COMMAND, exit_code=code, timed_out=timed_out, duration_seconds=0.5,
                   output=output, passed=passed, failed=failed, errors=errors, failed_tests=failed_tests or [])


class StubRunner:
    """Stands in for the Docker runner; records what each directory looked like when it was 'executed'."""

    def __init__(self, runs, *, available=True, boom: Exception | None = None):
        self.runs = list(runs)
        self.available = available
        self.boom = boom
        self.calls: list[dict] = []

    async def status(self):
        return SandboxStatus(True, self.available, "ready" if self.available else "Docker daemon is not reachable.")

    async def run(self, source_dir, label):
        if self.boom:
            raise self.boom
        api = (source_dir / "app/api.py")
        reg = source_dir / "tests/test_repopilot_regression.py"
        self.calls.append({"label": label, "dir": source_dir, "api": api.read_text() if api.exists() else None, "has_regression": reg.exists()})
        return self.runs.pop(0)


class FakeAgent:
    """Minimal agent double for manager/API tests."""

    def __init__(self, behavior="ok", gate=None):
        self.behavior = behavior
        self.gate = gate
        self.seen_workspace_exists = None

    async def run(self, request, workspace, progress):
        import asyncio

        self.seen_workspace_exists = workspace.path.exists()
        progress.emit("clone", "started", "Cloning")
        if self.gate is not None:
            await self.gate.wait()
        if self.behavior == "hang":
            await asyncio.sleep(60)
        if self.behavior == "app_error":
            from app.core.errors import UnsupportedRepository
            raise UnsupportedRepository("Go repositories are not supported yet.")
        if self.behavior == "crash":
            raise RuntimeError("secret internal detail at /root/private/path")
        progress.set_result(
            RepairResult(
                outcome="patch_proposed", root_cause="root cause", confidence="high",
                diff="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n",
                validation=Validation(), llm_model="fake",
            )
        )
        progress.emit("finalize", "completed", "Done")
