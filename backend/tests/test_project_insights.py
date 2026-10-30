from app.services.project_insights import assess_quality, summarize_structure
from app.services.repository_service import RepositoryService

FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def index_of(settings, root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return RepositoryService(settings).index(root)


class TestStructure:
    def test_folders_roles_and_entry_points(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {
            "README.md": "# x\n", "main.py": "print(1)\n", "app/core.py": "x = 1\n", "app/util.py": "y = 2\n",
            "tests/test_core.py": "def test_x():\n    pass\n", "docs/guide.md": "g\n", ".github/workflows/ci.yml": "on: push\n",
            "src/web/index.ts": "export {}\n", "src/web/page.ts": "export {}\n", "src/api/server.ts": "export {}\n",
        })
        folders, entries = summarize_structure(idx)
        roles = {f.path: f.role for f in folders}
        assert roles["tests"] == "tests" and roles["docs"] == "docs" and roles[".github"] == "ci"
        assert roles["app"] == "source" and roles["(root)"] == "source"
        assert "src/web" in roles and "src/api" in roles  # container folders are split one level further
        assert folders[0].path == "(root)"
        assert entries[0] == "main.py" and "src/web/index.ts" in entries and "src/api/server.ts" in entries
        assert next(f for f in folders if f.path == "app").languages == ["Python"]

    def test_bounded_for_huge_repositories(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {f"pkg{i}/mod.py": "x = 1\n" for i in range(40)} | {f"pkg{i}/main.py": "x = 1\n" for i in range(40)})
        folders, entries = summarize_structure(idx)
        assert len(folders) <= 14 and len(entries) <= 8

    def test_next_app_router_entry(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {"app/page.tsx": "export default 1\n", "app/layout.tsx": "export default 2\n"})
        assert set(summarize_structure(idx)[1]) == {"app/page.tsx", "app/layout.tsx"}


class TestQuality:
    def test_flags_secrets_by_location_and_never_copies_the_value(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {
            "README.md": "x\n", "tests/test_a.py": "def test_a():\n    pass\n",
            "config.py": f'AWS = "{FAKE_AWS}"\nTOKEN = "{FAKE_TOKEN}"\npassword = "hunter2-real-password"\n',
        })
        issues = assess_quality(idx)
        secrets = [i for i in issues if i.title == "Possible hard-coded secret"]
        assert {i.line for i in secrets} == {1, 2, 3} and all(i.path == "config.py" for i in secrets)
        blob = " ".join(i.detail + i.title for i in issues)
        assert FAKE_AWS not in blob and FAKE_TOKEN not in blob and "hunter2" not in blob

    def test_ignores_placeholders_environment_lookups_and_test_files(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {
            "README.md": "x\n",
            "app.py": 'password = os.environ["PASSWORD_VALUE"]\napi_key = "your_api_key_here"\nsecret = "changeme-please"\n',
            "tests/test_x.py": f'TOKEN = "{FAKE_TOKEN}"\n',
        })
        assert not [i for i in assess_quality(idx) if i.title == "Possible hard-coded secret"]

    def test_python_checks(self, settings, tmp_path):
        body = "\n".join(f"    x{i} = {i}" for i in range(85))
        idx = index_of(settings, tmp_path, {
            "README.md": "x\n", "tests/test_a.py": "def test_a():\n    pass\n",
            "m.py": f"def risky(items=[]):\n    try:\n        return eval('1')\n    except:\n        return 0\n\ndef long():\n{body}\n",
        })
        titles = {i.title for i in assess_quality(idx)}
        assert {"Bare except", "Mutable default argument", "Very long function", "Dynamic code execution"} <= titles

    def test_missing_tests_readme_and_markers(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {"a.go": "package a\n// TODO: later\n// FIXME: now\n", "b.go": "package a\n// HACK\n"})
        by_title = {i.title: i for i in assess_quality(idx)}
        assert by_title["No tests found"].severity == "warning" and "No README" in by_title
        assert "3 TODO/FIXME/HACK comments in 2 file(s)" in by_title["Unfinished work markers"].detail

    def test_clean_project_has_no_warnings(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {"README.md": "x\n", "a.py": "def f(x):\n    return x\n", "tests/test_a.py": "def test_f():\n    pass\n"})
        assert assess_quality(idx) == []

    def test_warnings_come_before_notes_and_the_list_is_bounded(self, settings, tmp_path):
        files = {"README.md": "x\n"} | {f"m{i}.py": "try:\n    pass\nexcept:\n    pass\n" for i in range(30)}
        issues = assess_quality(index_of(settings, tmp_path, files))
        assert len(issues) <= 12
        severities = [i.severity for i in issues]
        assert severities == sorted(severities, key=lambda s: s != "warning")

    def test_unparseable_python_does_not_crash(self, settings, tmp_path):
        assert isinstance(assess_quality(index_of(settings, tmp_path, {"README.md": "x\n", "bad.py": "def (:\n", "tests/test_a.py": "x\n"})), list)


class TestDynamicExecutionIsNotFlaggedFalsely:
    def test_python_strings_and_attribute_calls_are_not_calls_to_eval(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {
            "README.md": "x\n", "tests/test_a.py": "x\n",
            "m.py": 'MSG = "eval() is dangerous"\n\ndef f(db):\n    db.exec("select 1")\n    return model.eval()\n',
        })
        assert not [i for i in assess_quality(idx) if i.title == "Dynamic code execution"]

    def test_a_real_python_call_is_flagged_with_its_line(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {"README.md": "x\n", "tests/test_a.py": "x\n", "m.py": "x = 1\nresult = eval(user_input)\n"})
        hit = next(i for i in assess_quality(idx) if i.title == "Dynamic code execution")
        assert (hit.path, hit.line) == ("m.py", 2)

    def test_javascript_ignores_strings_comments_and_methods(self, settings, tmp_path):
        idx = index_of(settings, tmp_path, {
            "README.md": "x\n", "tests/a.test.js": "x\n",
            "a.js": '// eval(x)\nconst m = "never call eval(x)";\nobj.eval(1);\n',
            "b.js": "const v = eval(code);\n",
        })
        hits = [i for i in assess_quality(idx) if i.title == "Dynamic code execution"]
        assert [(h.path, h.line) for h in hits] == [("b.js", 1)]
