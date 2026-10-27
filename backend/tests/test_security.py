import os

import pytest

from app.core.errors import InvalidRepositoryURL, UnsafePathError
from app.core.security import (
    is_valid_investigation_id,
    normalize_repo_path,
    parse_github_url,
    protected_reason,
    resolve_inside,
)


class TestGithubUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://github.com/octocat/Hello-World", ("octocat", "Hello-World")),
            ("https://github.com/octocat/Hello-World/", ("octocat", "Hello-World")),
            ("https://github.com/octocat/Hello-World.git", ("octocat", "Hello-World")),
            ("  https://www.github.com/octocat/repo.name_x  ", ("octocat", "repo.name_x")),
            ("HTTPS://GITHUB.COM/octocat/Hello-World", ("octocat", "Hello-World")),
        ],
    )
    def test_accepts_valid(self, url, expected):
        assert parse_github_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            "http://github.com/o/r",
            "git@github.com:o/r.git",
            "ssh://git@github.com/o/r",
            "file:///etc/passwd",
            "https://gitlab.com/o/r",
            "https://github.com.evil.com/o/r",
            "https://evil.com/github.com/o/r",
            "https://user:pw@github.com/o/r",
            "https://github.com:8443/o/r",
            "https://github.com/o",
            "https://github.com/o/r/tree/main",
            "https://github.com/o/r?x=1",
            "https://github.com/o/r#frag",
            "https://github.com//o/r",
            "https://github.com/o/..",
            "https://github.com/-bad/r",
            "https://github.com/o/r r",
            "https://github.com/o/r;rm -rf /",
            "https://github.com/o/$(whoami)",
            "https://github.com/o/r\nhttps://evil.com",
            "https://github.com/" + "a" * 300 + "/r",
        ],
    )
    def test_rejects_invalid(self, url):
        with pytest.raises(InvalidRepositoryURL):
            parse_github_url(url)

    def test_error_message_is_helpful(self):
        with pytest.raises(InvalidRepositoryURL) as exc:
            parse_github_url("https://gitlab.com/o/r")
        assert "github.com" in exc.value.message


class TestPaths:
    @pytest.mark.parametrize("path", ["../etc/passwd", "a/../../b", "/etc/passwd", "~/x", "C:\\x", "a\\b", ".git/config", "a/.git/x", "a\x00b", "", "x" * 400])
    def test_rejects_unsafe(self, path):
        with pytest.raises(UnsafePathError):
            normalize_repo_path(path)

    def test_normalizes(self):
        assert normalize_repo_path("a/./b/c.py") == "a/b/c.py"

    def test_resolve_inside_stays_in_root(self, tmp_path):
        (tmp_path / "ok").mkdir()
        (tmp_path / "ok" / "f.py").write_text("x")
        assert resolve_inside(tmp_path, "ok/f.py") == (tmp_path / "ok" / "f.py").resolve()

    def test_symlink_escape_is_blocked(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("s")
        root = tmp_path / "root"
        root.mkdir()
        os.symlink(outside, root / "link")
        with pytest.raises(UnsafePathError):
            resolve_inside(root, "link/secret.txt")

    def test_symlinked_file_is_blocked(self, tmp_path):
        (tmp_path / "real.txt").write_text("x")
        root = tmp_path / "root"
        root.mkdir()
        os.symlink(tmp_path / "real.txt", root / "f.txt")
        with pytest.raises(UnsafePathError):
            resolve_inside(root, "f.txt")

    def test_investigation_id_format(self):
        assert is_valid_investigation_id("a" * 32)
        for bad in ["", "A" * 32, "a" * 31, "../" + "a" * 29, "g" * 32]:
            assert not is_valid_investigation_id(bad)


class TestProtectedFiles:
    @pytest.mark.parametrize(
        "path",
        [
            ".env", ".env.production", "config/.env", "id_rsa", "deploy/server.pem", "keys/private.key",
            ".github/workflows/ci.yml", ".gitlab-ci.yml", "Dockerfile", "docker/Dockerfile.prod", "docker-compose.yml",
            "package-lock.json", "poetry.lock", "conftest.py", "pytest.ini", "pyproject.toml", "package.json",
            "tests/test_a.py", "app/test_b.py", "src/c_test.py", "web/a.test.ts", "__tests__/x.js",
            "firebase-service-account.json",
        ],
    )
    def test_protected(self, path):
        assert protected_reason(path) is not None

    @pytest.mark.parametrize("path", ["app/api.py", "src/index.js", "lib/utils/helpers.py", "README.md", "server/routes/users.ts"])
    def test_allowed(self, path):
        assert protected_reason(path) is None
