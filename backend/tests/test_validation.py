import os
import stat
import textwrap

import pytest

from app.schemas.models import TestRun, ValidationStatus
from app.services import validation_service as vs
from app.services.validation_service import SandboxRunner, ValidationService, classify, parse_pytest_output, unavailable


def run(label="patched", code=0, failed_tests=None, passed=3, failed=0, errors=0, output="", timed_out=False, duration=1.0):
    return TestRun(label=label, command=vs.PYTEST_COMMAND, exit_code=code, timed_out=timed_out, duration_seconds=duration,
                   output=output, passed=passed, failed=failed, errors=errors, failed_tests=failed_tests or [])


class TestParse:
    def test_summary_and_failures(self):
        out = "FAILED tests/test_a.py::test_x - AssertionError\nERROR tests/test_b.py::test_y\n2 failed, 5 passed, 1 error in 0.3s"
        assert parse_pytest_output(out) == (5, 2, 1, ["tests/test_a.py::test_x", "tests/test_b.py::test_y"])

    def test_only_passed(self):
        assert parse_pytest_output("...\n12 passed in 0.5s")[:3] == (12, 0, 0)

    def test_test_output_cannot_fake_the_summary(self):
        # A test that prints "999 passed" mid-output must not be counted; only the tail is parsed.
        noise = "999 passed\n" + "\n".join(f"line {i}" for i in range(20)) + "\n1 failed in 0.1s"
        assert parse_pytest_output(noise)[:3] == (0, 1, 0)

    def test_garbage(self):
        assert parse_pytest_output("") == (0, 0, 0, [])


class TestClassify:
    def test_pass_after_fail_confirms_the_fix(self):
        v = classify(run("baseline", 1, ["t::a"], passed=2, failed=1), run(code=0, passed=3))
        assert v.status == ValidationStatus.PASSED and v.bug_reproduced is True
        assert "failed before the patch" in v.summary and "t::a" in v.summary

    def test_pass_without_reproduction_is_flagged(self):
        v = classify(run("baseline", 0), run(code=0))
        assert v.status == ValidationStatus.PASSED and v.bug_reproduced is False
        assert "does not prove" in v.summary

    def test_pass_with_inconclusive_baseline(self):
        v = classify(run("baseline", 2), run(code=0))
        assert v.status == ValidationStatus.PASSED and v.bug_reproduced is None

    def test_pass_with_no_baseline(self):
        assert classify(None, run(code=0)).bug_reproduced is None

    def test_still_failing(self):
        v = classify(run("baseline", 1, ["t::a"]), run(code=1, failed_tests=["t::a"], failed=1, passed=1))
        assert v.status == ValidationStatus.FAILED and "still fail" in v.summary

    def test_patch_broke_passing_tests(self):
        v = classify(run("baseline", 0), run(code=1, failed_tests=["t::b"], failed=1))
        assert v.status == ValidationStatus.FAILED and "t::b" in v.summary and "introduced" in v.summary

    def test_timeout_is_inconclusive(self):
        v = classify(None, run(code=None, timed_out=True, duration=120))
        assert v.status == ValidationStatus.INCONCLUSIVE and v.reason == "timeout"

    @pytest.mark.parametrize("code,reason", [(2, "collection_or_interrupt"), (3, "internal_error"), (4, "usage_error"), (5, "no_tests"), (125, "execution_error"), (None, "execution_error")])
    def test_abnormal_exit_is_inconclusive(self, code, reason):
        v = classify(None, run(code=code))
        assert v.status == ValidationStatus.INCONCLUSIVE and v.reason == reason

    def test_missing_dependencies_are_not_blamed_on_the_patch(self):
        v = classify(run("baseline", 1), run(code=1, failed=1, output="E   ModuleNotFoundError: No module named 'flask'"))
        assert v.status == ValidationStatus.INCONCLUSIVE and v.reason == "missing_dependencies"

    def test_import_error_after_a_passing_baseline_is_a_real_failure(self):
        v = classify(run("baseline", 0), run(code=1, failed=1, output="ImportError: cannot import name x"))
        assert v.status == ValidationStatus.FAILED

    def test_never_passed_unless_exit_zero(self):
        for code in (1, 2, 3, 4, 5, 125, None):
            assert classify(run("baseline", 1), run(code=code)).status != ValidationStatus.PASSED

    def test_unavailable_is_not_run(self):
        v = unavailable("Sandbox is disabled.")
        assert v.status == ValidationStatus.NOT_RUN and "Validation unavailable" in v.summary and "not been tested" in v.summary


class TestDockerArgs:
    def args(self, settings, path="/srv/ws/abc/patched"):
        return SandboxRunner(settings).docker_args(__import__("pathlib").Path(path), "repopilot-test")

    def test_isolation_flags_present(self, settings):
        a = self.args(settings)
        joined = " ".join(a)
        assert a[:2] == ["run", "--rm"]
        assert "--network none" in joined
        assert "--user 65534:65534" in joined
        assert "--read-only" in a
        assert "--cap-drop ALL" in joined
        assert "no-new-privileges" in joined
        assert "--pids-limit" in a and "--memory" in a and "--cpus" in a
        assert f"--memory-swap {settings.sandbox_memory_mb}m" in joined  # no swap escape hatch
        assert "readonly" in joined  # source mounted read-only
        assert "--privileged" not in a and "--pid=host" not in joined

    def test_no_host_secrets_or_sockets_are_mounted(self, settings):
        joined = " ".join(self.args(settings))
        assert "docker.sock" not in joined and "--env-file" not in joined and "-v " not in joined
        assert joined.count("--mount") == 1

    def test_command_is_fixed_allowlist(self, settings):
        a = self.args(settings)
        assert a[-len(vs.PYTEST_COMMAND):] == vs.PYTEST_COMMAND
        assert a[a.index("sh"): a.index("sh") + 3] == ["sh", "-c", 'cp -a /src/. /work/ && exec "$@"']

    @pytest.mark.parametrize("bad", ["/tmp/a,b", "/tmp/a\nb"])
    def test_hostile_mount_paths_rejected(self, settings, bad):
        with pytest.raises(ValueError):
            self.args(settings, bad)


FAKE_DOCKER = textwrap.dedent(
    """\
    #!/bin/sh
    case "$1" in
      info) echo 27.0.0; exit 0 ;;
      image) [ "$FAKE_IMAGE" = "missing" ] && exit 1; exit 0 ;;
      rm) echo "$@" >> "$FAKE_LOG"; exit 0 ;;
      run)
        echo "$@" >> "$FAKE_LOG"
        case "$FAKE_MODE" in
          pass) echo "3 passed in 0.1s"; exit 0 ;;
          fail) echo "FAILED tests/test_a.py::test_x - AssertionError"; echo "1 failed, 2 passed in 0.1s"; exit 1 ;;
          hang) exec sleep 30 ;;
          flood) exec yes "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" ;;
          crash) echo "docker: error"; exit 125 ;;
        esac ;;
    esac
    """
)


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "docker"
    script.write_text(FAKE_DOCKER)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "docker.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_MODE", "pass")
    monkeypatch.delenv("FAKE_IMAGE", raising=False)
    return log


@pytest.fixture
def sandbox_settings(settings):
    return settings.model_copy(update={"sandbox_enabled": True, "test_timeout_seconds": 5})


class TestSandboxRunner:
    async def test_disabled_by_default(self, settings):
        status = await SandboxRunner(settings).status()
        assert not status.enabled and not status.available and "disabled" in status.reason

    async def test_available(self, fake_docker, sandbox_settings):
        assert (await SandboxRunner(sandbox_settings).status()).available

    async def test_missing_image_means_unavailable(self, fake_docker, sandbox_settings, monkeypatch):
        monkeypatch.setenv("FAKE_IMAGE", "missing")
        status = await SandboxRunner(sandbox_settings).status()
        assert not status.available and "image" in status.reason

    async def test_no_docker_binary(self, sandbox_settings, monkeypatch):
        monkeypatch.setenv("PATH", "/nonexistent")
        status = await SandboxRunner(sandbox_settings).status()
        assert not status.available and "not installed" in status.reason

    async def test_passing_run_reports_real_exit_code(self, fake_docker, sandbox_settings, tmp_path):
        result = await SandboxRunner(sandbox_settings).run(tmp_path, "patched")
        assert (result.exit_code, result.passed, result.timed_out) == (0, 3, False)
        assert "3 passed" in result.output

    async def test_failing_run(self, fake_docker, sandbox_settings, monkeypatch, tmp_path):
        monkeypatch.setenv("FAKE_MODE", "fail")
        result = await SandboxRunner(sandbox_settings).run(tmp_path, "patched")
        assert result.exit_code == 1 and result.failed == 1 and result.failed_tests == ["tests/test_a.py::test_x"]

    async def test_timeout_kills_container(self, fake_docker, sandbox_settings, monkeypatch, tmp_path):
        monkeypatch.setenv("FAKE_MODE", "hang")
        settings = sandbox_settings.model_copy(update={"test_timeout_seconds": 5})
        object.__setattr__(settings, "test_timeout_seconds", 1)
        result = await SandboxRunner(settings).run(tmp_path, "patched")
        assert result.timed_out and result.exit_code is None
        assert any(line.startswith("rm -f repopilot-") for line in fake_docker.read_text().splitlines())
        assert classify(None, result).status == ValidationStatus.INCONCLUSIVE

    async def test_output_flood_is_truncated(self, fake_docker, sandbox_settings, monkeypatch, tmp_path):
        monkeypatch.setenv("FAKE_MODE", "flood")
        result = await SandboxRunner(sandbox_settings).run(tmp_path, "patched")
        assert result.output_truncated
        assert len(result.output) <= sandbox_settings.sandbox_output_limit_kb * 1024 + 100
        assert classify(None, result).status != ValidationStatus.PASSED

    async def test_docker_failure_is_inconclusive_not_failed(self, fake_docker, sandbox_settings, monkeypatch, tmp_path):
        monkeypatch.setenv("FAKE_MODE", "crash")
        result = await SandboxRunner(sandbox_settings).run(tmp_path, "patched")
        assert result.exit_code == 125
        assert classify(None, result).status == ValidationStatus.INCONCLUSIVE

    async def test_run_uses_unique_container_names(self, fake_docker, sandbox_settings, tmp_path):
        runner = SandboxRunner(sandbox_settings)
        await runner.run(tmp_path, "baseline")
        await runner.run(tmp_path, "patched")
        names = [line.split("--name ")[1].split()[0] for line in fake_docker.read_text().splitlines() if line.startswith("run")]
        assert len(set(names)) == 2


class TestAvailability:
    async def test_disabled(self, settings):
        ok, why = await ValidationService(settings).availability(language_supported=True, has_tests=True, frameworks=["pytest"])
        assert not ok and "disabled" in why

    async def test_non_python(self, fake_docker, sandbox_settings):
        ok, why = await ValidationService(sandbox_settings).availability(language_supported=False, has_tests=True, frameworks=[])
        assert not ok and "Python" in why

    async def test_no_tests(self, fake_docker, sandbox_settings):
        ok, why = await ValidationService(sandbox_settings).availability(language_supported=True, has_tests=False, frameworks=[])
        assert not ok and "No test suite" in why

    async def test_ready(self, fake_docker, sandbox_settings):
        ok, _ = await ValidationService(sandbox_settings).availability(language_supported=True, has_tests=True, frameworks=["pytest"])
        assert ok

    def test_regression_test_cannot_escape_directory(self, tmp_path):
        ValidationService.write_regression_test(tmp_path, "tests/test_a.py", "def test_a(): pass\n")
        assert (tmp_path / "tests/test_a.py").exists()
        with pytest.raises(ValueError):
            ValidationService.write_regression_test(tmp_path, "../escape.py", "x")


class TestTargetedFix:
    def test_fixing_one_of_several_preexisting_failures(self):
        v = classify(run("baseline", 1, ["t::a", "t::b", "t::c"], failed=3), run(code=1, failed_tests=["t::b", "t::c"], failed=2, passed=5))
        assert v.status == ValidationStatus.PASSED and v.scope == "targeted" and v.bug_reproduced is True
        assert v.fixed_tests == ["t::a"] and v.pre_existing_failures == 2
        assert "already existed" in v.summary and "t::a" in v.summary

    def test_a_new_failure_voids_the_targeted_pass(self):
        v = classify(run("baseline", 1, ["t::a", "t::b"], failed=2), run(code=1, failed_tests=["t::b", "t::z"], failed=2))
        assert v.status == ValidationStatus.FAILED and "t::z" in v.summary

    def test_nothing_fixed_is_a_failure(self):
        v = classify(run("baseline", 1, ["t::a"], failed=1), run(code=1, failed_tests=["t::a"], failed=1))
        assert v.status == ValidationStatus.FAILED

    def test_full_suite_pass_is_labelled_full_suite(self):
        assert classify(run("baseline", 1, ["t::a"], failed=1), run(code=0)).scope == "full_suite"
