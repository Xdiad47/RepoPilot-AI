"""Deterministic understanding of a project's shape and health. No LLM, no code execution.

* ``summarize_structure``: which folders hold what, and where the program starts.
* ``assess_quality``: cheap, honest heuristics (hard-coded secrets, risky calls, huge files, missing tests). They are
  observations to look at, never a security audit, and a detected secret is reported by location only (the value is
  never copied into the result).
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from app.schemas.models import FolderSummary, QualityIssue
from app.services.repository_service import RepoIndex

CONTAINER_DIRS = {"src", "app", "apps", "packages", "services", "modules", "cmd", "internal", "libs", "projects"}
ROLE_BY_NAME = {
    "tests": "tests", "test": "tests", "spec": "tests", "specs": "tests", "__tests__": "tests", "androidtest": "tests",
    "docs": "docs", "doc": "docs", "documentation": "docs", "examples": "docs", "example": "docs",
    ".github": "ci", ".circleci": "ci", ".gitlab": "ci",
    "scripts": "tooling", "tools": "tooling", "bin": "tooling", "deploy": "tooling", "docker": "tooling",
    "config": "config", "configs": "config", "conf": "config", "settings": "config",
    "assets": "assets", "static": "assets", "public": "assets", "images": "assets", "res": "assets",
}
ENTRY_POINT_NAMES = {
    "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "__main__.py", "server.py", "run.py",
    "index.js", "index.ts", "server.js", "server.ts", "main.js", "main.ts", "app.js", "app.ts", "index.jsx", "index.tsx",
    "main.go", "main.rs", "lib.rs", "Main.java", "Application.java", "Program.cs", "Startup.cs", "main.dart",
    "App.swift", "AppDelegate.swift", "MainActivity.kt", "Application.kt", "main.kt", "index.php", "config.ru", "main.c", "main.cpp",
}
NEXT_ENTRY = re.compile(r"(^|/)app/(page|layout)\.(tsx|jsx|ts|js)$")

MAX_FOLDERS = 14
MAX_ENTRY_POINTS = 8
MAX_ISSUES = 12
MAX_FILES_SCANNED = 400
MAX_FILE_BYTES = 200_000
BIG_FILE_LINES = 800
LONG_FUNCTION_LINES = 80


def _depth(path: str) -> int:
    return path.count("/")


def summarize_structure(index: RepoIndex) -> tuple[list[FolderSummary], list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for f in index.files:
        parts = PurePosixPath(f.path).parts
        if len(parts) == 1:
            key = "(root)"
        elif parts[0].lower() in CONTAINER_DIRS and len(parts) > 2:
            key = "/".join(parts[:2])
        else:
            key = parts[0]
        groups[key].append(f.path)

    by_path = index.by_path()
    folders: list[FolderSummary] = []
    for key, paths in groups.items():
        langs = Counter(by_path[p].language for p in paths if by_path[p].language)
        name = PurePosixPath(key).parts[-1].lower() if key != "(root)" else ""
        role = ROLE_BY_NAME.get(name) or ("source" if langs else "other")
        folders.append(FolderSummary(path=key, files=len(paths), languages=[lang for lang, _ in langs.most_common(3)], role=role))  # type: ignore[arg-type]
    folders.sort(key=lambda f: (f.path != "(root)", -f.files, f.path))

    entries = sorted(
        {f.path for f in index.files if f.path.rsplit("/", 1)[-1] in ENTRY_POINT_NAMES or NEXT_ENTRY.search(f.path)},
        key=lambda p: (_depth(p), p),
    )
    return folders[:MAX_FOLDERS], entries[:MAX_ENTRY_POINTS]


# --- Code health --------------------------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("an API key", re.compile(r"\b(?:sk|gsk|tvly)[-_][A-Za-z0-9_\-]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
]
_ASSIGNED_SECRET = re.compile(r"""(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*["']([^"'\s]{8,})["']""")
_PLACEHOLDER = re.compile(r"(?i)(change.?me|example|your[_-]|xxx|placeholder|dummy|sample|test|<.*>|\$\{|%s|todo|\*\*\*|process\.env|os\.environ|getenv)")
_MARKER = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
_TEST_PATH_PARTS = {"test", "tests", "__tests__", "spec", "specs", "androidtest"}
_JS_EVAL = re.compile(r"(?<![\w.$])eval\(")
_EVAL_ISSUE = QualityIssue(severity="warning", title="Dynamic code execution", detail="eval()/exec() runs text as code. If any part of it comes from a user this is a serious vulnerability.")


def _in_string(line: str, index: int) -> bool:
    """Crude check that ``index`` sits inside a quoted string (odd number of quote marks before it)."""
    before = line[:index]
    return any(before.count(q) % 2 == 1 for q in ('"', "'", "`"))


def _is_test(path: str) -> bool:
    low = path.lower()
    name = low.rsplit("/", 1)[-1]
    return (
        any(p in _TEST_PATH_PARTS for p in low.split("/")[:-1])
        or name.startswith("test_")
        or re.search(r"(_test|\.test|\.spec|_spec)\.[a-z]+$", name) is not None
        or re.search(r"tests?\.(java|kt|swift|cs|php|scala)$", name) is not None
    )


def assess_quality(index: RepoIndex) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    source = [f for f in index.files if f.language]
    paths = {f.path for f in index.files}

    if source and not any(_is_test(f.path) for f in index.files):
        issues.append(QualityIssue(severity="warning", title="No tests found", detail="No test files were detected, so changes cannot be checked automatically."))
    if source and not any(p.rsplit("/", 1)[-1].lower().startswith("readme") for p in paths if "/" not in p):
        issues.append(QualityIssue(severity="info", title="No README", detail="The repository root has no README describing the project."))

    markers: Counter[str] = Counter()
    secrets: list[QualityIssue] = []
    risky: list[QualityIssue] = []
    big: list[QualityIssue] = []
    python_issues: list[QualityIssue] = []

    for f in sorted(source, key=lambda f: (_depth(f.path), f.path))[:MAX_FILES_SCANNED]:
        try:
            text = index.read_text(f.path, max_bytes=MAX_FILE_BYTES)
        except Exception:  # noqa: BLE001, S112 - an unreadable file is simply not assessed
            continue
        lines = text.splitlines()
        test_file = _is_test(f.path)

        if len(lines) > BIG_FILE_LINES and not test_file:
            big.append(QualityIssue(severity="info", title="Very large file", path=f.path, detail=f"{len(lines)} lines in one file. Large files are harder to review and test."))

        for n, line in enumerate(lines, 1):
            if _MARKER.search(line):
                markers[f.path] += 1
            if test_file or len(secrets) >= 4:
                continue
            for label, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    secrets.append(QualityIssue(severity="warning", title="Possible hard-coded secret", path=f.path, line=n, detail=f"This line looks like {label}. Secrets in source control should be rotated and moved to environment variables. The value is not shown here."))
                    break
            else:
                match = _ASSIGNED_SECRET.search(line)
                if match and not _PLACEHOLDER.search(match.group(1)) and not _PLACEHOLDER.search(line):
                    secrets.append(QualityIssue(severity="warning", title="Possible hard-coded secret", path=f.path, line=n, detail="A password, token or key appears to be assigned a literal value. The value is not shown here."))

        if f.language in ("JavaScript", "TypeScript") and not test_file:
            for n, line in enumerate(lines, 1):
                match = _JS_EVAL.search(line)
                if match and not line.lstrip().startswith("//") and not _in_string(line, match.start()):
                    risky.append(_EVAL_ISSUE.model_copy(update={"path": f.path, "line": n}))
                    break
        if f.language == "Python" and not test_file:
            python_issues.extend(_python_issues(f.path, text))

    if markers:
        top, count = markers.most_common(1)[0]
        total = sum(markers.values())
        issues.append(QualityIssue(severity="info", title="Unfinished work markers", detail=f"{total} TODO/FIXME/HACK comments in {len(markers)} file(s); the most in {top} ({count})."))

    combined = [*secrets, *risky[:3], *python_issues[:6], *big[:2], *issues]
    combined.sort(key=lambda i: i.severity != "warning")  # stable: warnings first, original order kept within a group
    return combined[:MAX_ISSUES]


def _python_issues(path: str, text: str) -> list[QualityIssue]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return []
    out: list[QualityIssue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            out.append(_EVAL_ISSUE.model_copy(update={"path": path, "line": node.lineno}))
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            out.append(QualityIssue(severity="warning", title="Bare except", path=path, line=node.lineno, detail="`except:` also catches KeyboardInterrupt and hides real errors. Catch a specific exception."))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]
            if any(isinstance(d, (ast.List, ast.Dict, ast.Set)) for d in defaults):
                out.append(QualityIssue(severity="warning", title="Mutable default argument", path=path, line=node.lineno, detail=f"`{node.name}()` uses a list/dict/set as a default value. It is shared between calls, a classic source of bugs."))
            length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
            if length > LONG_FUNCTION_LINES:
                out.append(QualityIssue(severity="info", title="Very long function", path=path, line=node.lineno, detail=f"`{node.name}()` is {length} lines long. Long functions are hard to test and easy to break."))
    return out
