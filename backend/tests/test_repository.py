import os

import httpx
import pytest

from app.core.errors import CloneFailed, GitHubUnavailable, RepositoryNotFound, RepositoryTooLarge, UnsafePathError
from app.services.repository_analyzer import RepositoryAnalyzer
from app.services.repository_service import RepositoryService, Workspace, purge_stale_workspaces

ID_A = "a" * 32
ID_B = "b" * 32


def make_service(settings, handler):
    return RepositoryService(settings, transport=httpx.MockTransport(handler))


class TestMetadata:
    async def test_ok(self, settings):
        def handler(request):
            assert request.url.path == "/repos/octocat/hello"
            return httpx.Response(200, json={"name": "hello", "private": False, "size": 100, "default_branch": "main",
                                             "stargazers_count": 5, "html_url": "https://github.com/octocat/hello"})
        meta = await make_service(settings, handler).fetch_metadata("octocat", "hello")
        assert meta.size_kb == 100 and meta.default_branch == "main"

    async def test_not_found(self, settings):
        with pytest.raises(RepositoryNotFound):
            await make_service(settings, lambda r: httpx.Response(404)).fetch_metadata("o", "r")

    async def test_private_is_rejected(self, settings):
        with pytest.raises(RepositoryNotFound):
            await make_service(settings, lambda r: httpx.Response(200, json={"private": True, "size": 1})).fetch_metadata("o", "r")

    async def test_too_large(self, settings):
        big = settings.max_repository_size_mb * 1024 + 1
        with pytest.raises(RepositoryTooLarge):
            await make_service(settings, lambda r: httpx.Response(200, json={"private": False, "size": big})).fetch_metadata("o", "r")

    async def test_rate_limited(self, settings):
        with pytest.raises(GitHubUnavailable):
            await make_service(settings, lambda r: httpx.Response(403)).fetch_metadata("o", "r")

    async def test_network_error(self, settings):
        def boom(request):
            raise httpx.ConnectError("down")
        with pytest.raises(GitHubUnavailable):
            await make_service(settings, boom).fetch_metadata("o", "r")


class TestGit:
    async def test_timeout_is_enforced(self, settings):
        svc = RepositoryService(settings)
        with pytest.raises(CloneFailed, match="timed out"):
            await svc._run_git(["sleep", "5"], {"PATH": os.environ["PATH"]}, 1, "clone")

    async def test_failure_hides_internal_output(self, settings):
        svc = RepositoryService(settings)
        with pytest.raises(CloneFailed) as exc:
            await svc._run_git(["sh", "-c", "echo secret-detail >&2; exit 3"], {"PATH": os.environ["PATH"]}, 5, "clone")
        assert "secret-detail" not in exc.value.message

    async def test_missing_git_binary(self, settings):
        svc = RepositoryService(settings)
        with pytest.raises(CloneFailed):
            await svc._run_git(["definitely-not-a-real-binary"], {"PATH": ""}, 5, "clone")


class TestIndexing:
    def build_tree(self, root):
        files = {
            "src/app.py": "print('hi')\n",
            "src/util.js": "export const a = 1;\n",
            "README.md": "# x\n",
            "node_modules/lib/index.js": "x",
            "venv/lib/site.py": "x",
            "__pycache__/a.pyc": "x",
            ".git/config": "x",
            "dist/bundle.min.js": "x",
            "assets/logo.png": "\x89PNG",
            "package-lock.json": "{}",
            "data/blob.dat": "abc\x00def",
            "empty.py": "",
        }
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="latin-1")

    def test_excludes_noise(self, settings, tmp_path):
        root = tmp_path / "r"
        self.build_tree(root)
        paths = {f.path for f in RepositoryService(settings).index(root).files}
        assert paths == {"src/app.py", "src/util.js", "README.md"}

    def test_symlinks_are_never_followed(self, settings, tmp_path):
        root = tmp_path / "r"
        root.mkdir()
        (tmp_path / "secret.txt").write_text("top secret")
        os.symlink(tmp_path / "secret.txt", root / "leak.py")
        (tmp_path / "outdir").mkdir()
        (tmp_path / "outdir" / "x.py").write_text("x=1")
        os.symlink(tmp_path / "outdir", root / "linkdir")
        (root / "ok.py").write_text("x = 1\n")
        index = RepositoryService(settings).index(root)
        assert [f.path for f in index.files] == ["ok.py"]

    def test_file_count_limit(self, settings, tmp_path):
        small = settings.model_copy(update={"max_source_files": 10})
        root = tmp_path / "r"
        root.mkdir()
        for i in range(11):
            (root / f"f{i}.py").write_text("x = 1\n")
        with pytest.raises(RepositoryTooLarge):
            RepositoryService(small).index(root)

    def test_total_size_limit(self, settings, tmp_path):
        small = settings.model_copy(update={"max_repository_size_mb": 1})
        root = tmp_path / "r"
        root.mkdir()
        for i in range(6):
            (root / f"f{i}.txt").write_bytes(b"a" * 250_000)
        with pytest.raises(RepositoryTooLarge):
            RepositoryService(small).index(root)

    def test_large_single_files_skipped(self, settings, tmp_path):
        root = tmp_path / "r"
        root.mkdir()
        (root / "big.py").write_text("x = 1\n" * 100_000)
        (root / "ok.py").write_text("x = 1\n")
        assert [f.path for f in RepositoryService(settings).index(root).files] == ["ok.py"]


class TestWorkspace:
    def test_isolated_per_investigation(self, settings):
        a, b = Workspace(settings.workspace_root, ID_A), Workspace(settings.workspace_root, ID_B)
        a.create()
        b.create()
        (a.path / "x.txt").write_text("a")
        assert a.path != b.path and not (b.path / "x.txt").exists()
        a.cleanup()
        assert not a.path.exists() and b.path.exists()
        b.cleanup()

    def test_rejects_bad_ids(self, settings):
        for bad in ["../x", "a" * 31, "/etc", "A" * 32]:
            with pytest.raises(UnsafePathError):
                Workspace(settings.workspace_root, bad)

    def test_cleanup_never_leaves_root(self, settings, tmp_path):
        ws = Workspace(settings.workspace_root, ID_A)
        ws.create()
        victim = tmp_path / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("k")
        ws.path = victim  # simulate a corrupted path
        ws.cleanup()
        assert (victim / "keep.txt").exists()

    def test_copy_skips_symlinks(self, settings, tmp_path):
        ws = Workspace(settings.workspace_root, ID_A)
        ws.create()
        ws.repo_dir.mkdir()
        (ws.repo_dir / "a.py").write_text("x")
        os.symlink("/etc/hosts", ws.repo_dir / "link.py")
        dest = ws.copy_repo("patched")
        assert (dest / "a.py").exists() and not (dest / "link.py").exists()
        ws.cleanup()

    def test_purge_only_removes_workspace_dirs(self, settings):
        root = settings.workspace_root
        root.mkdir(parents=True)
        (root / ID_A).mkdir()
        (root / "important-notes").mkdir()
        assert purge_stale_workspaces(root) == 1
        assert not (root / ID_A).exists() and (root / "important-notes").exists()


class TestAnalyzerProfile:
    def index_of(self, settings, root):
        return RepositoryService(settings).index(root)

    def test_detects_python_and_pytest(self, settings, fixture_repo):
        profile = RepositoryAnalyzer().profile(self.index_of(settings, fixture_repo))
        assert profile.primary_language == "Python" and profile.supported
        assert "pytest" in profile.test_frameworks and profile.has_tests
        assert "requirements.txt" in profile.manifests

    def test_unsupported_language_is_reported_honestly(self, settings, tmp_path):
        (tmp_path / "main.go").write_text("package main\n")
        (tmp_path / "util.go").write_text("package main\n")
        profile = RepositoryAnalyzer().profile(self.index_of(settings, tmp_path))
        assert profile.primary_language == "Go" and not profile.supported
        assert "not supported" in profile.support_note

    def test_javascript_is_analysis_only(self, settings, tmp_path):
        (tmp_path / "index.js").write_text("module.exports = 1;\n")
        (tmp_path / "package.json").write_text('{"devDependencies": {"jest": "^29"}}')
        profile = RepositoryAnalyzer().profile(self.index_of(settings, tmp_path))
        assert profile.supported and profile.validation_language is None
        assert profile.test_frameworks == ["jest"]

    def test_empty_repo_is_unsupported(self, settings, tmp_path):
        (tmp_path / "README.md").write_text("hi")
        assert not RepositoryAnalyzer().profile(self.index_of(settings, tmp_path)).supported


class TestRanking:
    def test_stack_trace_file_ranks_first(self, settings, fixture_repo):
        analyzer = RepositoryAnalyzer()
        index = RepositoryService(settings).index(fixture_repo)
        trace = 'Traceback (most recent call last):\n  File "/srv/app/app/api.py", line 5, in register\nIndexError: list index out of range'
        frames = analyzer.extract_frames(trace, index)
        assert [(f.path, f.line) for f in frames] == [("app/api.py", 5)]
        ranked = analyzer.rank_files(index, analyzer.extract_keywords("register crashes with empty email"), frames)
        assert ranked[0].path == "app/api.py"

    def test_keywords_prefer_identifiers(self, settings):
        kws = RepositoryAnalyzer().extract_keywords("The `normalize_email` function fails when user_name is empty in api.py")
        assert "normalize_email" in kws[:3] and "the" not in kws

    def test_unknown_frames_are_ignored(self, settings, fixture_repo):
        index = RepositoryService(settings).index(fixture_repo)
        frames = RepositoryAnalyzer().extract_frames('File "/nowhere/ghost.py", line 3, in x', index)
        assert frames == []

    def test_render_context_windows_large_files(self):
        analyzer = RepositoryAnalyzer()
        text = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(400))
        out = analyzer.render_context("big.py", text, [301], 3000)
        assert "omitted" in out and "def f100" in out and len(out) < 4000
