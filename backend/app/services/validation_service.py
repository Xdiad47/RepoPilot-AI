"""Test validation inside a locked-down Docker container.

Rules enforced here:
* Repository code is NEVER run in the API process or directly on the host.
* The command is chosen by this module from a fixed allowlist - never by the model or the repository.
* The container has no network, a read-only root FS, no capabilities, an unprivileged uid, and CPU / memory /
  process / output / time limits. The source is mounted read-only and copied into a size-limited tmpfs.
* If the sandbox is disabled or unavailable the status is ``not_run`` ("Validation unavailable"), never a guess.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.schemas.models import TestRun, Validation, ValidationStatus

logger = logging.getLogger(__name__)

# The only command the sandbox will ever run. Extra arguments are not accepted from anywhere.
PYTEST_COMMAND = [
    "python", "-m", "pytest", "-q", "-rfE", "--tb=short", "--no-header", "--maxfail=50", "-p", "no:cacheprovider",
]

_SUMMARY_COUNT = re.compile(r"(\d+) (passed|failed|error|errors)\b")
_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)
_MISSING_DEPENDENCY = re.compile(r"(ModuleNotFoundError|ImportError)")


@dataclass
class SandboxStatus:
    enabled: bool
    available: bool
    reason: str


class SandboxRunner:
    """Runs one allowlisted command in a throwaway container."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._cached: tuple[float, SandboxStatus] | None = None

    async def status(self) -> SandboxStatus:
        if not self._s.sandbox_enabled:
            return SandboxStatus(False, False, "Sandbox is disabled (SANDBOX_ENABLED=false).")
        if self._cached and time.monotonic() - self._cached[0] < 30:
            return self._cached[1]
        status = await self._probe()
        self._cached = (time.monotonic(), status)
        return status

    async def _probe(self) -> SandboxStatus:
        if shutil.which("docker") is None:
            return SandboxStatus(True, False, "Docker is not installed on the server.")
        code, _ = await self._docker(["info", "--format", "{{.ServerVersion}}"], 10)
        if code != 0:
            return SandboxStatus(True, False, "The Docker daemon is not reachable.")
        code, _ = await self._docker(["image", "inspect", self._s.sandbox_image], 10)
        if code != 0:
            return SandboxStatus(
                True, False, f"Sandbox image '{self._s.sandbox_image}' is missing. Build it from deploy/sandbox/Dockerfile."
            )
        return SandboxStatus(True, True, "Docker sandbox is ready.")

    @staticmethod
    async def _docker(args: list[str], timeout: int) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, out.decode(errors="replace")
        except (TimeoutError, OSError):
            return 1, ""

    def docker_args(self, source_dir: Path, container_name: str) -> list[str]:
        """The complete, fixed ``docker run`` argument list (exposed for tests)."""
        s = self._s
        if any(ch in str(source_dir) for ch in ",\n\r\x00"):
            raise ValueError("Unsafe characters in sandbox source path.")
        return [
            "run", "--rm", "--name", container_name,
            "--network", "none",
            "--user", "65534:65534",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", str(s.sandbox_pids_limit),
            "--memory", f"{s.sandbox_memory_mb}m",
            "--memory-swap", f"{s.sandbox_memory_mb}m",
            "--cpus", str(s.sandbox_cpus),
            "--ulimit", "nofile=512:512",
            "--ulimit", "core=0",
            "--tmpfs", f"/work:rw,exec,nosuid,nodev,size={s.sandbox_tmpfs_mb}m,uid=65534,gid=65534,mode=0755",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,uid=65534,gid=65534",
            "--mount", f"type=bind,source={source_dir},target=/src,readonly",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTHONHASHSEED=0",
            "-e", "HOME=/tmp",
            "-e", "CI=true",
            "-w", "/work",
            s.sandbox_image,
            # Fixed wrapper: copy the read-only source into the tmpfs, then run the allowlisted command.
            "sh", "-c", 'cp -a /src/. /work/ && exec "$@"', "repopilot-run", *PYTEST_COMMAND,
        ]

    async def run(self, source_dir: Path, label: str) -> TestRun:
        name = f"repopilot-{uuid.uuid4().hex[:16]}"
        args = self.docker_args(source_dir, name)
        limit = self._s.sandbox_output_limit_kb * 1024
        half = max(1, limit // 2)
        started = time.monotonic()
        head = bytearray()  # first half of the output budget
        tail = bytearray()  # last half, so pytest's final summary survives truncation
        total = 0
        killed_for_output = False
        timed_out = False
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )

        async def pump() -> None:
            """Read until EOF. Past the budget we keep only the tail; far past it we stop the container."""
            nonlocal total, killed_for_output
            assert proc.stdout is not None
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    return
                total += len(data)
                room = half - len(head)
                if room > 0:
                    head.extend(data[:room])
                    data = data[room:]
                if data:
                    tail.extend(data)
                    if len(tail) > half:
                        del tail[: len(tail) - half]
                if total > limit * 4 and not killed_for_output:
                    killed_for_output = True
                    await self._stop(name, proc)  # keep reading afterwards so the pipe reaches EOF

        try:
            await asyncio.wait_for(pump(), timeout=self._s.test_timeout_seconds)
            await asyncio.wait_for(proc.wait(), timeout=15)
        except TimeoutError:
            timed_out = True
            await self._stop(name, proc)
            await self._drain(proc)

        truncated = total > limit
        output = head.decode("utf-8", errors="replace")
        if truncated:
            output += "\n[... output truncated by the RepoPilot sandbox limit ...]\n" + tail.decode("utf-8", errors="replace")
        elif tail:
            output += tail.decode("utf-8", errors="replace")
        exit_code = None if (timed_out or killed_for_output) else proc.returncode
        passed, failed, errors, failed_tests = parse_pytest_output(output)
        return TestRun(
            label=label,  # type: ignore[arg-type]
            command=PYTEST_COMMAND,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_seconds=round(time.monotonic() - started, 2),
            output=output,
            output_truncated=truncated,
            passed=passed,
            failed=failed,
            errors=errors,
            failed_tests=failed_tests,
        )

    async def _stop(self, name: str, proc: asyncio.subprocess.Process) -> None:
        """Remove the container and kill the docker client. Does not wait: the caller must drain the pipe."""
        await self._docker(["rm", "-f", name], 15)
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    @staticmethod
    async def _drain(proc: asyncio.subprocess.Process) -> None:
        """Discard remaining output so the subprocess transport can close cleanly."""
        try:
            assert proc.stdout is not None

            async def read_all() -> None:
                while await proc.stdout.read(65536):  # type: ignore[union-attr]
                    pass

            await asyncio.wait_for(read_all(), timeout=10)
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            logger.warning("docker client process did not exit after being stopped")


def parse_pytest_output(output: str) -> tuple[int, int, int, list[str]]:
    """(passed, failed, errors, failed_test_ids) from pytest's -q output."""
    passed = failed = errors = 0
    # Look only at the final summary line(s) to avoid matching text printed by the tests.
    tail = "\n".join(output.strip().splitlines()[-6:])
    for count, kind in _SUMMARY_COUNT.findall(tail):
        if kind == "passed":
            passed = int(count)
        elif kind == "failed":
            failed = int(count)
        else:
            errors = int(count)
    failed_tests = sorted(set(_FAILED_LINE.findall(output)))[:50]
    return passed, failed, errors, failed_tests


def classify(baseline: TestRun | None, patched: TestRun) -> Validation:
    """Turn raw runs into an honest status. Never reports ``passed`` unless the patched run really exited 0."""
    runs = [r for r in (baseline, patched) if r is not None]

    if patched.timed_out:
        return Validation(
            status=ValidationStatus.INCONCLUSIVE, runs=runs, reason="timeout",
            summary=f"The test run exceeded the {int(patched.duration_seconds)}s time limit, so the result is inconclusive.",
        )
    if patched.exit_code not in (0, 1):
        reason = {2: "collection_or_interrupt", 3: "internal_error", 4: "usage_error", 5: "no_tests"}.get(
            patched.exit_code or -1, "execution_error"
        )
        detail = {
            "no_tests": "pytest collected no tests.",
            "collection_or_interrupt": "pytest could not collect or finish the tests (import/collection errors are common when dependencies are not installed in the offline sandbox).",
        }.get(reason, f"the test process ended abnormally (exit code {patched.exit_code}).")
        return Validation(
            status=ValidationStatus.INCONCLUSIVE, runs=runs, reason=reason, summary=f"Inconclusive: {detail}"
        )

    if patched.exit_code == 0:
        if baseline is not None and baseline.exit_code == 1:
            fixed = sorted(set(baseline.failed_tests) - set(patched.failed_tests))
            return Validation(
                status=ValidationStatus.PASSED, runs=runs, bug_reproduced=True, scope="full_suite", fixed_tests=fixed[:20],
                summary=(
                    f"Passed. The tests failed before the patch ({baseline.failed + baseline.errors} failing) and all "
                    f"{patched.passed} pass after it" + (f"; now passing: {', '.join(fixed[:5])}." if fixed else ".")
                ),
            )
        if baseline is not None and baseline.exit_code == 0:
            return Validation(
                status=ValidationStatus.PASSED, runs=runs, bug_reproduced=False, scope="full_suite",
                summary=(
                    f"The test suite passes after the patch ({patched.passed} passed), but it also passed before the "
                    "patch, so no existing test reproduced the reported bug. This does not prove the bug is fixed."
                ),
            )
        return Validation(
            status=ValidationStatus.PASSED, runs=runs, bug_reproduced=None, scope="full_suite",
            summary=f"The test suite passes after the patch ({patched.passed} passed). The pre-patch run was inconclusive, so the fix is not independently confirmed.",
        )

    # patched.exit_code == 1: tests failed
    if _MISSING_DEPENDENCY.search(patched.output) and (baseline is None or baseline.exit_code != 0):
        return Validation(
            status=ValidationStatus.INCONCLUSIVE, runs=runs, reason="missing_dependencies",
            summary="Inconclusive: tests failed with import errors. The offline sandbox only has pytest and the standard library, so project dependencies are unavailable.",
        )
    new_failures = sorted(set(patched.failed_tests) - set(baseline.failed_tests)) if baseline else []
    if baseline is not None and baseline.exit_code == 1 and not new_failures:
        fixed = sorted(set(baseline.failed_tests) - set(patched.failed_tests))
        if fixed:
            remaining = len(patched.failed_tests)
            return Validation(
                status=ValidationStatus.PASSED, runs=runs, bug_reproduced=True, scope="targeted",
                fixed_tests=fixed[:20], pre_existing_failures=remaining,
                summary=(
                    f"Targeted fix confirmed: {len(fixed)} test(s) that failed before the patch now pass "
                    f"({', '.join(fixed[:3])}) and no new failures were introduced. The full suite still has "
                    f"{remaining} failure(s) that already existed before the patch and are not addressed by it."
                ),
            )
    if baseline is not None and baseline.exit_code == 0:
        detail = "The patch introduced failures that did not exist before: " + ", ".join(new_failures[:5]) if new_failures else "The patch broke previously passing tests."
    elif baseline is not None and new_failures:
        detail = "Some failures remain and the patch introduced new ones: " + ", ".join(new_failures[:5])
    else:
        detail = "Tests still fail after the patch."
    return Validation(
        status=ValidationStatus.FAILED, runs=runs, reason="tests_failed",
        summary=f"Failed. {detail} ({patched.failed} failed, {patched.errors} errors, {patched.passed} passed.)",
    )


def unavailable(reason: str) -> Validation:
    return Validation(
        status=ValidationStatus.NOT_RUN, reason="validation_unavailable",
        summary=f"Validation unavailable. {reason} The patch is a proposal only: it has not been tested.",
    )


class ValidationService:
    def __init__(self, settings: Settings, runner: SandboxRunner | None = None) -> None:
        self._s = settings
        self.runner = runner or SandboxRunner(settings)

    async def availability(self, *, language_supported: bool, has_tests: bool, frameworks: list[str]) -> tuple[bool, str]:
        """Can we validate this repo at all? Returns (can_run, reason_if_not)."""
        status = await self.runner.status()
        if not status.enabled or not status.available:
            return False, status.reason
        if not language_supported:
            return False, "Automated test validation currently supports Python repositories only."
        if not has_tests and not frameworks:
            return False, "No test suite was detected in this repository."
        return True, ""

    async def run_baseline(self, source_dir: Path) -> TestRun:
        return await self.runner.run(source_dir, "baseline")

    async def run_patched(self, source_dir: Path) -> TestRun:
        return await self.runner.run(source_dir, "patched")

    @staticmethod
    def write_regression_test(directory: Path, rel_path: str, content: str) -> None:
        """Add the model-proposed test to a disposable copy (path chosen by us, not the model)."""
        target = directory / rel_path
        if directory.resolve() not in target.resolve().parents:
            raise ValueError("Regression test path escapes the workspace.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        os.chmod(target, 0o644)
