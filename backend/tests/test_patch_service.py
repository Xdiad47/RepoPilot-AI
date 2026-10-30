import pytest

from app.core.errors import PatchRejected
from app.schemas.llm import EditIn, RegressionTestIn
from app.services.patch_service import (
    NOEOL,
    PatchService,
    apply_file_patch,
    compose,
    decompose,
    make_unified_diff,
    parse_unified_diff,
)
from app.services.repository_service import RepositoryService


@pytest.fixture
def index(settings, fixture_repo):
    return RepositoryService(settings).index(fixture_repo)


@pytest.fixture
def svc(settings):
    return PatchService(settings)


def edit(path="app/api.py", search='    domain = email.split("@")[1]\n', replace='    domain = email.partition("@")[2]\n'):
    return EditIn(path=path, search=search, replace=replace, explanation="why")


class TestBuildPatch:
    def test_happy_path_builds_a_valid_diff(self, svc, index):
        build = svc.build_patch([edit()], index)
        assert build.ok, build.problems
        assert build.diff.startswith("--- a/app/api.py\n+++ b/app/api.py\n@@")
        assert '-    domain = email.split("@")[1]' in build.diff
        assert '+    domain = email.partition("@")[2]' in build.diff
        change = build.changes[0]
        assert (change.additions, change.deletions) == (1, 1)
        assert 'partition("@")' in change.patched_content and 'split("@")' in change.original_content

    def test_diff_applies_cleanly_and_reproduces_edits(self, svc, index):
        build = svc.build_patch([edit()], index)
        assert svc.validate_diff(build.diff, index)["app/api.py"] == build.changes[0].patched_content

    def test_original_files_are_never_modified(self, svc, index):
        before = (index.root / "app/api.py").read_text()
        svc.build_patch([edit()], index)
        assert (index.root / "app/api.py").read_text() == before

    @pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "app/../../x.py", ".git/config"])
    def test_path_traversal_rejected(self, svc, index, path):
        build = svc.build_patch([edit(path=path)], index)
        assert not build.ok and build.diff == ""

    @pytest.mark.parametrize("path", [".env", "tests/test_api.py", "requirements.txt.lock", ".github/workflows/ci.yml", "Dockerfile", "conftest.py"])
    def test_protected_and_unknown_files_rejected(self, svc, index, path):
        assert not svc.build_patch([edit(path=path)], index).ok

    def test_search_not_found(self, svc, index):
        build = svc.build_patch([edit(search="nonexistent line\n")], index)
        assert not build.ok and "not found" in build.problems[0]

    def test_search_must_be_unique(self, svc, settings, tmp_path):
        (tmp_path / "dup.py").write_text("x = 1\nx = 1\n")
        idx = RepositoryService(settings).index(tmp_path)
        build = svc.build_patch([edit(path="dup.py", search="x = 1\n", replace="x = 2\n")], idx)
        assert not build.ok and "2 places" in build.problems[0]

    def test_noop_edit_rejected(self, svc, index):
        assert not svc.build_patch([edit(replace='    domain = email.split("@")[1]\n')], index).ok

    def test_empty_edits_rejected(self, svc, index):
        assert not svc.build_patch([], index).ok

    def test_syntax_errors_are_caught_before_anything_is_shown(self, svc, index):
        build = svc.build_patch([edit(replace="    domain = (\n")], index)
        assert not build.ok and "not be valid Python" in build.problems[0]

    def test_too_many_files(self, svc, settings, tmp_path):
        small = PatchService(settings.model_copy(update={"max_patch_files": 1}))
        for n in "ab":
            (tmp_path / f"{n}.py").write_text("x = 1\n")
        idx = RepositoryService(settings).index(tmp_path)
        build = small.build_patch([edit("a.py", "x = 1\n", "x = 2\n"), edit("b.py", "x = 1\n", "x = 3\n")], idx)
        assert not build.ok and "limit" in build.problems[0]

    def test_patch_size_limit(self, settings, index):
        tiny = PatchService(settings.model_copy(update={"max_patch_bytes": 1000}))
        build = tiny.build_patch([edit(replace="    pass  # " + "x" * 1500 + "\n")], index)
        assert not build.ok and "limit" in " ".join(build.problems)

    def test_trailing_whitespace_in_search_is_tolerated(self, svc, settings, tmp_path):
        (tmp_path / "w.py").write_text("a = 1   \nb = 2\n")
        idx = RepositoryService(settings).index(tmp_path)
        assert svc.build_patch([edit("w.py", "a = 1\n", "a = 5\n")], idx).ok

    def test_multiple_edits_in_one_file(self, svc, settings, tmp_path):
        (tmp_path / "m.py").write_text("a = 1\nb = 2\nc = 3\n")
        idx = RepositoryService(settings).index(tmp_path)
        build = svc.build_patch([edit("m.py", "a = 1\n", "a = 10\n"), edit("m.py", "c = 3\n", "c = 30\n")], idx)
        assert build.ok and build.changes[0].patched_content == "a = 10\nb = 2\nc = 30\n"

    def test_crlf_files_keep_their_line_endings(self, svc, settings, tmp_path):
        (tmp_path / "c.py").write_bytes(b"a = 1\r\nb = 2\r\n")
        idx = RepositoryService(settings).index(tmp_path)
        build = svc.build_patch([edit("c.py", "b = 2\n", "b = 3\n")], idx)
        assert build.ok and build.changes[0].patched_content == "a = 1\r\nb = 3\r\n"

    def test_mixed_line_endings_refused(self, svc, settings, tmp_path):
        (tmp_path / "x.py").write_bytes(b"a = 1\r\nb = 2\n")
        idx = RepositoryService(settings).index(tmp_path)
        assert not svc.build_patch([edit("x.py", "b = 2\n", "b = 3\n")], idx).ok

    def test_no_trailing_newline_preserved(self, svc, settings, tmp_path):
        (tmp_path / "n.py").write_text("a = 1\nb = 2")
        idx = RepositoryService(settings).index(tmp_path)
        build = svc.build_patch([edit("n.py", "b = 2", "b = 3")], idx)
        assert build.ok and build.changes[0].patched_content == "a = 1\nb = 3"
        assert "\\ No newline at end of file" in build.diff


class TestDiffValidation:
    GOOD = '--- a/app/validators.py\n+++ b/app/validators.py\n@@ -1,2 +1,2 @@\n def normalize_email(email):\n-    return email.strip().lower()\n+    return email.strip()\n'

    def test_good_diff(self, svc, index):
        assert svc.validate_diff(self.GOOD, index)["app/validators.py"] == "def normalize_email(email):\n    return email.strip()\n"

    @pytest.mark.parametrize(
        "diff",
        [
            "",
            "just some text",
            "--- a/x.py\n+++ b/x.py\n",
            "--- /dev/null\n+++ b/app/new.py\n@@ -0,0 +1 @@\n+x\n",
            "--- a/app/api.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n",
            "--- a/../../etc/passwd\n+++ b/../../etc/passwd\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/app/api.py\n+++ b/app/validators.py\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/app/validators.py\n+++ b/app/validators.py\n@@ -1,2 +1,2 @@\n def normalize_email(email):\n-    WRONG CONTEXT\n+    x\n",
            "--- a/app/validators.py\n+++ b/app/validators.py\n@@ -1,2 +1,5 @@\n def normalize_email(email):\n-    return email.strip().lower()\n+    return 1\n",
            "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/tests/test_api.py\n+++ b/tests/test_api.py\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/app/ghost.py\n+++ b/app/ghost.py\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/app/validators.py\n+++ b/app/validators.py\n@@ nonsense @@\n",
            "--- a/app/validators.py\n+++ b/app/validators.py\n@@ -1 +1 @@\n-def normalize_email(email):\n+x\x00\n",
        ],
    )
    def test_malformed_or_hostile_diffs_rejected(self, svc, index, diff):
        with pytest.raises(PatchRejected):
            svc.validate_diff(diff, index)

    def test_oversized_diff_rejected(self, settings, index):
        tiny = PatchService(settings.model_copy(update={"max_patch_bytes": 100}))
        with pytest.raises(PatchRejected, match="limit"):
            tiny.validate_diff(self.GOOD + "+" + "x" * 200 + "\n", index)

    def test_apply_to_directory_writes_only_the_disposable_copy(self, svc, index, tmp_path):
        import shutil

        copy = tmp_path / "copy"
        shutil.copytree(index.root, copy)
        changed = svc.apply_to_directory(self.GOOD, index, copy)
        assert changed == ["app/validators.py"]
        assert (copy / "app/validators.py").read_text().endswith("email.strip()\n")
        assert (index.root / "app/validators.py").read_text().endswith(".lower()\n")

    def test_removed_line_starting_with_dashes_is_not_a_header(self, svc, settings, tmp_path):
        (tmp_path / "s.sql").write_text("-- comment\nSELECT 1;\n")
        idx = RepositoryService(settings).index(tmp_path)
        diff = "--- a/s.sql\n+++ b/s.sql\n@@ -1,2 +1,2 @@\n--- comment\n+-- changed\n SELECT 1;\n"
        assert svc.validate_diff(diff, idx)["s.sql"] == "-- changed\nSELECT 1;\n"


class TestDiffRoundTrip:
    @pytest.mark.parametrize(
        "old,new",
        [
            ("a\nb\nc\n", "a\nB\nc\n"),
            ("a\nb\nc\n", "a\nb\nc\nd\n"),
            ("a\nb\nc\n", "b\nc\n"),
            ("", "x\ny\n"),
            ("x\n", ""),
            ("a\nb", "a\nb\n"),
            ("a\nb\n", "a\nb"),
            ("a\nb", "a\nc"),
            ("\n\n\n", "\n\n"),
            ("\n".join(str(i) for i in range(100)) + "\n", "\n".join(str(i) if i % 17 else "X" for i in range(100)) + "\n"),
        ],
    )
    def test_generated_diff_applies_back_exactly(self, old, new):
        old_lines, _ = decompose(old)
        new_lines, _ = decompose(new)
        diff, _, _ = make_unified_diff("f.txt", old_lines, new_lines)
        if old == new:
            assert diff == ""
            return
        (file_patch,) = parse_unified_diff(diff)
        assert compose(apply_file_patch(old_lines, file_patch), False) == new

    def test_noeol_marker_roundtrip_helpers(self):
        lines, crlf = decompose("a\nb")
        assert lines == ["a", "b" + NOEOL] and not crlf
        assert compose(lines, False) == "a\nb"


class TestRegressionTest:
    def test_accepts_a_valid_pytest_file(self, svc, index):
        test, problem = svc.prepare_regression_test(
            RegressionTestIn(description="d", content="def test_x():\n    assert 1 + 1 == 2\n"), index
        )
        assert problem is None and test.path == "tests/test_repopilot_regression.py"

    def test_unique_name_when_taken(self, svc, settings, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests/test_repopilot_regression.py").write_text("x = 1\n")
        idx = RepositoryService(settings).index(tmp_path)
        test, _ = svc.prepare_regression_test(RegressionTestIn(content="def test_a():\n    pass\n"), idx)
        assert test.path == "tests/test_repopilot_regression_2.py"

    @pytest.mark.parametrize(
        "content",
        [
            "def test_x(:\n",
            "x = 1\n",
            "import subprocess\ndef test_x():\n    subprocess.run(['ls'])\n",
            "import socket\ndef test_x():\n    pass\n",
            "import os\ndef test_x():\n    os.system('id')\n",
            "def test_x():\n    eval('1')\n",
        ],
    )
    def test_rejects_unsafe_or_invalid(self, svc, index, content):
        test, problem = svc.prepare_regression_test(RegressionTestIn(content=content), index)
        assert test is None and problem

    def test_none_proposal(self, svc, index):
        assert svc.prepare_regression_test(None, index) == (None, None)


class TestIndentationTolerance:
    """Models often mangle indentation. A unique match that differs only in indentation is accepted, and the
    replacement is written in the FILE's indentation style."""

    GO = "package shop\n\nfunc Apply(total float64, percent float64) float64 {\n\treturn total - total*percent/10\n}\n"
    PY = "def f(x):\n    if x:\n        return x - 1\n    return 0\n"

    def build(self, settings, tmp_path, name, content, *edits):
        repo = tmp_path / "ind_repo"
        repo.mkdir(exist_ok=True)
        (repo / name).write_text(content, encoding="utf-8")
        index = RepositoryService(settings).index(repo)
        return PatchService(settings).build_patch([EditIn(path=name, search=s, replace=r, explanation="e") for s, r in edits], index)

    def test_missing_indentation_is_restored_from_the_file_tab(self, settings, tmp_path):
        build = self.build(settings, tmp_path, "cart.go", self.GO, ("return total - total*percent/10", "return total - total*percent/100"))
        assert build.ok, build.problems
        assert "-\treturn total - total*percent/10\n" in build.diff
        assert "+\treturn total - total*percent/100\n" in build.diff
        assert "+    " not in build.diff

    def test_spaces_in_the_search_are_mapped_onto_the_files_tabs(self, settings, tmp_path):
        build = self.build(
            settings, tmp_path, "cart.go", self.GO,
            ("    return total - total*percent/10\n", "    if percent > 100 {\n        percent = 100\n    }\n    return total - total*percent/100\n"),
        )
        assert build.ok, build.problems
        patched = build.changes[0].patched_content
        assert "\tif percent > 100 {\n\t\tpercent = 100\n\t}\n\treturn total - total*percent/100\n" in patched

    def test_tabs_in_the_replacement_become_the_files_spaces(self, settings, tmp_path):
        build = self.build(settings, tmp_path, "m.py", self.PY, ("return x - 1", "if x > 5:\n\treturn x\nreturn x - 1"))
        assert build.ok, build.problems
        patched = build.changes[0].patched_content
        assert "        if x > 5:\n            return x\n        return x - 1\n" in patched

    def test_exact_indentation_is_untouched(self, settings, tmp_path):
        build = self.build(settings, tmp_path, "m.py", self.PY, ("        return x - 1\n", "        return x - 2\n"))
        assert build.ok and "+        return x - 2\n" in build.diff

    def test_an_ambiguous_indentation_insensitive_match_is_rejected(self, settings, tmp_path):
        two = "def a():\n    return 1\n\ndef b():\n        return 1\n"
        build = self.build(settings, tmp_path, "m.py", two, ("return 1", "return 2"))
        assert not build.ok and "matches 2 places" in build.problems[0]

    def test_text_that_really_is_absent_is_still_rejected(self, settings, tmp_path):
        build = self.build(settings, tmp_path, "m.py", self.PY, ("return x - 99", "return 0"))
        assert not build.ok and "not found" in build.problems[0]

    def test_python_syntax_is_still_checked_after_reindenting(self, settings, tmp_path):
        build = self.build(settings, tmp_path, "m.py", self.PY, ("return x - 1", "return (x - 1"))
        assert not build.ok and "not be valid Python" in build.problems[0]
