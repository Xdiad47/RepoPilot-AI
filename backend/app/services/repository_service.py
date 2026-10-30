"""Repository access: GitHub metadata, hardened shallow clone, file indexing, per-investigation workspaces.

The repository is treated as hostile input. We never execute anything from it here; we only read files.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import Settings
from app.core.errors import (
    CloneFailed,
    GitHubUnavailable,
    RepositoryNotFound,
    RepositoryTooLarge,
    UnsafePathError,
)
from app.core.security import is_valid_investigation_id, normalize_repo_path, resolve_inside

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor", "venv", ".venv", "env", ".env",
    "virtualenv", "__pycache__", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
    "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit", ".gradle", ".idea", ".vscode",
    "coverage", "htmlcov", ".cache", ".parcel-cache", ".turbo", "Pods", "DerivedData", "obj",
}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz", ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2",
    ".xz", ".7z", ".rar", ".jar", ".war", ".class", ".so", ".dll", ".dylib", ".exe", ".bin", ".o", ".a", ".pyc",
    ".pyo", ".whl", ".egg", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".wav",
    ".ogg", ".psd", ".sqlite", ".db", ".pkl", ".npy", ".npz", ".h5", ".onnx", ".pt", ".pth", ".safetensors", ".parquet",
}
LOCK_AND_GENERATED = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "uv.lock", "Cargo.lock",
    "composer.lock", "Gemfile.lock", "go.sum",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".swift": "Swift",
    ".scala": "Scala", ".sh": "Shell", ".lua": "Lua", ".dart": "Dart", ".r": "R",
    ".kts": "Kotlin", ".m": "Objective-C", ".mm": "Objective-C++", ".cxx": "C++", ".hh": "C++", ".hxx": "C++",
    ".vue": "Vue", ".svelte": "Svelte", ".ex": "Elixir", ".exs": "Elixir", ".hs": "Haskell", ".clj": "Clojure",
    ".jl": "Julia", ".pl": "Perl", ".pm": "Perl", ".ps1": "PowerShell", ".groovy": "Groovy", ".zig": "Zig",
    ".fs": "F#", ".vb": "Visual Basic",
}


@dataclass
class RepoFile:
    path: str  # repo-relative POSIX path
    size: int
    language: str | None


@dataclass
class RepoMetadata:
    owner: str
    name: str
    description: str | None
    default_branch: str | None
    stars: int | None
    size_kb: int
    html_url: str
    language: str | None


@dataclass
class RepoIndex:
    root: Path
    files: list[RepoFile] = field(default_factory=list)
    skipped: int = 0

    def by_path(self) -> dict[str, RepoFile]:
        return {f.path: f for f in self.files}

    def read_text(self, rel: str, max_bytes: int | None = None) -> str:
        """Read a file inside the repo as text (never follows symlinks outside the root)."""
        target = resolve_inside(self.root, rel)
        if max_bytes is None:
            data = target.read_bytes()
        else:
            with target.open("rb") as handle:
                data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")


class Workspace:
    """A private directory for exactly one investigation."""

    def __init__(self, root: Path, investigation_id: str) -> None:
        if not is_valid_investigation_id(investigation_id):
            raise UnsafePathError("Invalid investigation id.")
        self.root = root.resolve()
        self.id = investigation_id
        self.path = self.root / investigation_id

    @property
    def repo_dir(self) -> Path:
        return self.path / "repo"

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.mkdir(mode=0o700, exist_ok=False)

    def copy_repo(self, name: str) -> Path:
        """Make a disposable copy of the cloned repo (symlinks are never followed or copied)."""
        if not name.isalnum():
            raise UnsafePathError("Invalid copy name.")
        dest = self.path / name
        shutil.copytree(self.repo_dir, dest, symlinks=False, ignore=_skip_symlinks)
        return dest

    def cleanup(self) -> None:
        # Only ever delete the exact directory we created, and only if it is still inside the root.
        try:
            target = self.path.resolve()
            if target.parent == self.root and is_valid_investigation_id(target.name) and target.exists():
                shutil.rmtree(target, ignore_errors=True)
        except OSError:
            logger.warning("Workspace cleanup failed for %s", self.id)


def _skip_symlinks(directory: str, names: list[str]) -> list[str]:
    return [n for n in names if os.path.islink(os.path.join(directory, n))]


def make_readable_for_sandbox(directory: Path) -> None:
    """Sandbox containers run as an unprivileged uid; let them read (not write) the copy."""
    for current, _dirs, files in os.walk(directory):
        os.chmod(current, 0o755)  # noqa: S103 - intentional: the sandbox uid must read the disposable copy
        for name in files:
            os.chmod(os.path.join(current, name), 0o644)


def purge_stale_workspaces(root: Path) -> int:
    """On startup, remove leftovers from a crashed run. Only deletes 32-hex directories directly under root."""
    removed = 0
    if not root.exists():
        return 0
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink() and is_valid_investigation_id(child.name):
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


class RepositoryService:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport

    # --- GitHub metadata ---------------------------------------------------------------------------
    async def fetch_metadata(self, owner: str, repo: str) -> RepoMetadata:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "RepoPilot-AI",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._s.github_token:
            headers["Authorization"] = f"Bearer {self._s.github_token}"
        try:
            async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
                response = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        except httpx.HTTPError:
            raise GitHubUnavailable("Could not reach the GitHub API. Please try again shortly.") from None

        if response.status_code == 404:
            raise RepositoryNotFound()
        if response.status_code in (403, 429):
            raise GitHubUnavailable(
                "GitHub API rate limit reached for this server. Please try again later."
            )
        if response.status_code != 200:
            raise GitHubUnavailable(f"GitHub API returned an unexpected status ({response.status_code}).")

        data = response.json()
        if data.get("private"):
            raise RepositoryNotFound()
        size_kb = int(data.get("size") or 0)
        limit_kb = self._s.max_repository_size_mb * 1024
        if size_kb > limit_kb:
            raise RepositoryTooLarge(
                f"Repository is about {size_kb // 1024} MB; the limit is {self._s.max_repository_size_mb} MB."
            )
        return RepoMetadata(
            owner=owner,
            name=data.get("name") or repo,
            description=data.get("description"),
            default_branch=data.get("default_branch"),
            stars=data.get("stargazers_count"),
            size_kb=size_kb,
            html_url=data.get("html_url") or f"https://github.com/{owner}/{repo}",
            language=data.get("language"),
        )

    # --- Clone -------------------------------------------------------------------------------------
    async def clone(self, owner: str, repo: str, workspace: Workspace) -> str:
        """Shallow-clone into workspace.repo_dir and return the commit SHA. The .git directory is removed."""
        dest = workspace.repo_dir
        url = f"https://github.com/{owner}/{repo}.git"  # rebuilt from validated parts only
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(workspace.path),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_ALLOW_PROTOCOL": "https",
            "LC_ALL": "C",
        }
        cmd = [
            "git", "-c", "core.symlinks=false", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "clone", "--depth", "1", "--single-branch", "--no-tags", "--no-recurse-submodules", "--quiet",
            "--", url, str(dest),
        ]
        await self._run_git(cmd, env, self._s.clone_timeout_seconds, "clone")
        sha_out = await self._run_git(["git", "-C", str(dest), "rev-parse", "HEAD"], env, 15, "rev-parse")
        shutil.rmtree(dest / ".git", ignore_errors=True)
        return sha_out.strip()[:40]

    async def _run_git(self, cmd: list[str], env: dict[str, str], timeout: int, what: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise CloneFailed("git is not installed on the server.") from None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            _kill_group(proc)
            await proc.wait()
            raise CloneFailed(f"Git {what} timed out after {timeout}s.") from None
        if proc.returncode != 0:
            logger.warning("git %s failed (exit %s): %s", what, proc.returncode, err.decode(errors="replace")[:300])
            raise CloneFailed("Git could not clone the repository (it may be unavailable or empty).")
        return out.decode(errors="replace")

    # --- Indexing ----------------------------------------------------------------------------------
    def index(self, root: Path) -> RepoIndex:
        """Walk the clone, applying exclusions and size/count limits. Raises RepositoryTooLarge on overflow."""
        max_file_bytes = self._s.max_file_size_kb * 1024
        max_total_bytes = self._s.max_repository_size_mb * 1024 * 1024
        index = RepoIndex(root=root)
        total = 0
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not os.path.islink(os.path.join(current, d)))
            for name in sorted(names):
                full = Path(current) / name
                if full.is_symlink() or not full.is_file():
                    index.skipped += 1
                    continue
                try:
                    size = full.stat().st_size
                except OSError:
                    index.skipped += 1
                    continue
                total += size
                if total > max_total_bytes:
                    raise RepositoryTooLarge(
                        f"Repository contents exceed the {self._s.max_repository_size_mb} MB limit."
                    )
                ext = full.suffix.lower()
                if ext in BINARY_EXTENSIONS or name in LOCK_AND_GENERATED or name.endswith((".min.js", ".min.css", ".map")):
                    index.skipped += 1
                    continue
                if size > max_file_bytes or size == 0:
                    index.skipped += 1
                    continue
                if _looks_binary(full):
                    index.skipped += 1
                    continue
                rel = normalize_repo_path(full.relative_to(root).as_posix())
                index.files.append(RepoFile(path=rel, size=size, language=LANGUAGE_BY_EXTENSION.get(ext)))
                if len(index.files) > self._s.max_source_files:
                    raise RepositoryTooLarge(
                        f"Repository has more than {self._s.max_source_files} text files; it is too large to analyze."
                    )
        return index


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(2048)
    except OSError:
        return True


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
