"""Pure security helpers: URL validation, path-traversal prevention, protected-file rules.

Everything here is side-effect free so it can be unit tested exhaustively.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from app.core.errors import InvalidRepositoryURL, UnsafePathError

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_GITHUB_HOSTS = {"github.com", "www.github.com"}
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")


def parse_github_url(url: str) -> tuple[str, str]:
    """Validate a public GitHub repository URL and return (owner, repo).

    Only ``https://github.com/<owner>/<repo>[.git]`` is accepted. The clone URL is later rebuilt from
    the returned parts, so nothing from the raw user string reaches ``git`` unchecked.
    """
    raw = (url or "").strip()
    example = "Use a URL like https://github.com/owner/repository"
    if not raw:
        raise InvalidRepositoryURL(f"Repository URL is required. {example}")
    if len(raw) > 300 or any(ch.isspace() or ord(ch) < 32 for ch in raw):
        raise InvalidRepositoryURL(f"Repository URL is malformed. {example}")
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError:
        raise InvalidRepositoryURL(f"Repository URL is malformed. {example}") from None
    if parsed.scheme != "https":
        raise InvalidRepositoryURL(f"Only https:// GitHub URLs are supported. {example}")
    if parsed.username or parsed.password or port is not None:
        raise InvalidRepositoryURL(f"Credentials or ports are not allowed in the URL. {example}")
    if (parsed.hostname or "").lower() not in _GITHUB_HOSTS:
        raise InvalidRepositoryURL(f"Only github.com repositories are supported. {example}")
    if parsed.query or parsed.fragment or parsed.params or "//" in parsed.path:
        raise InvalidRepositoryURL(f"Repository URL must not contain query strings or fragments. {example}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        raise InvalidRepositoryURL(f"URL must point to a repository root (owner/repo). {example}")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _OWNER_RE.match(owner) or owner.endswith("-"):
        raise InvalidRepositoryURL("Repository owner name is not valid.")
    if not _REPO_RE.match(repo) or repo in {".", ".."}:
        raise InvalidRepositoryURL("Repository name is not valid.")
    return owner, repo


def is_valid_investigation_id(value: str) -> bool:
    return bool(_HEX32_RE.match(value or ""))


def normalize_repo_path(rel: str) -> str:
    """Return a clean POSIX repo-relative path or raise UnsafePathError."""
    if not isinstance(rel, str) or not rel.strip():
        raise UnsafePathError("Empty file path.")
    if len(rel) > 300 or "\x00" in rel or "\\" in rel:
        raise UnsafePathError(f"Unsafe file path: {rel[:80]!r}")
    if rel.startswith("/") or rel.startswith("~") or re.match(r"^[A-Za-z]:", rel):
        raise UnsafePathError(f"Absolute paths are not allowed: {rel[:80]!r}")
    parts = PurePosixPath(rel).parts
    if not parts or ".." in parts or ".git" in parts:
        raise UnsafePathError(f"Path traversal or VCS paths are not allowed: {rel[:80]!r}")
    return PurePosixPath(*parts).as_posix()


def resolve_inside(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root``, guaranteeing the result (and every component) stays inside it."""
    norm = normalize_repo_path(rel)
    root_resolved = root.resolve()
    current = root_resolved
    for part in PurePosixPath(norm).parts:
        current = current / part
        if current.is_symlink():
            raise UnsafePathError(f"Symbolic links are not allowed: {norm}")
    resolved = current.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise UnsafePathError(f"Path escapes the workspace: {norm}")
    return resolved


# --- Protected files: the patch may never touch these -------------------------------------------------

_SECRET_NAMES = {
    ".env", ".npmrc", ".pypirc", ".netrc", ".htpasswd", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json", "secrets.yml", "secrets.yaml", "service-account.json",
}
_SECRET_GLOBS = ["*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", ".env.*", "*service-account*.json"]
_VCS_CI_PARTS = {".git", ".github", ".gitlab", ".circleci", ".husky"}
_VCS_CI_NAMES = {".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "jenkinsfile", "bitbucket-pipelines.yml", ".gitattributes", ".gitmodules"}
_DEPLOY_GLOBS = ["Dockerfile*", "docker-compose*.yml", "docker-compose*.yaml", "*.tf", "vercel.json", "netlify.toml", "fly.toml", "Procfile"]
_LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "uv.lock", "cargo.lock",
    "composer.lock", "gemfile.lock", "go.sum",
}
# Files that configure *how tests run*: letting a patch edit them would let it "pass" by weakening the check.
_TEST_CONFIG_NAMES = {
    "conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "package.json", "noxfile.py",
    "jest.config.js", "jest.config.ts", "vitest.config.ts", "vitest.config.js", ".mocharc.json",
    # build and dependency manifests of other ecosystems: they decide which tests run and what gets installed
    "pubspec.yaml", "build.gradle", "build.gradle.kts", "settings.gradle", "pom.xml", "cargo.toml", "go.mod",
    "gemfile", "composer.json", "package.swift", "cmakelists.txt", "podfile", "phpunit.xml", "mix.exs",
}
_TEST_DIR_PARTS = {"test", "tests", "__tests__", "spec", "specs", "testing", "androidtest", "unittest", "uitests"}
_TEST_FILE_GLOBS = [
    "test_*.py", "*_test.py", "*.test.js", "*.test.ts", "*.test.jsx", "*.test.tsx", "*.spec.js", "*.spec.ts", "*.spec.jsx",
    "*.spec.tsx", "*_test.go", "*_test.dart", "*_test.rs", "*_spec.rb", "*_test.rb", "*_test.exs", "*_test.cc", "*_test.cpp",
    "*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt", "*Spec.kt", "*Tests.swift", "*Test.swift", "*Tests.cs", "*Test.cs",
    "*Test.php", "*Tests.php", "*Spec.scala", "*Test.scala",
]


def _matches_any(name: str, globs: list[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, g.lower()) for g in globs)


def protected_reason(rel: str) -> str | None:
    """Why a path may not be modified by a patch, or None when it is allowed."""
    parts = PurePosixPath(rel).parts
    name = parts[-1] if parts else ""
    lowered = name.lower()
    if lowered in _SECRET_NAMES or _matches_any(name, _SECRET_GLOBS):
        return "secrets and credential files cannot be modified"
    if any(p.lower() in _VCS_CI_PARTS for p in parts) or lowered in _VCS_CI_NAMES:
        return "version-control and CI/CD configuration cannot be modified"
    if _matches_any(name, _DEPLOY_GLOBS):
        return "container and deployment configuration cannot be modified"
    if lowered in _LOCKFILES:
        return "lock files are generated and cannot be modified"
    if lowered in _TEST_CONFIG_NAMES:
        return "test-runner and build configuration cannot be modified (it could weaken validation)"
    if any(p.lower() in _TEST_DIR_PARTS for p in parts[:-1]) or _matches_any(name, _TEST_FILE_GLOBS):
        return "existing tests cannot be modified by a repair (propose a new regression test instead)"
    return None
