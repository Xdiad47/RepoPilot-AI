"""Static understanding of a repository: language, manifests, test frameworks, relevant-file ranking.

Nothing here executes repository code. Python files are parsed with ``ast`` (which does not run them).
"""

from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.services.repository_service import LANGUAGE_BY_EXTENSION, RepoIndex
from app.services.stack_detector import detect_stack

MANIFEST_NAMES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "tox.ini",
    "pytest.ini", "conftest.py", "package.json", "tsconfig.json", "go.mod", "Cargo.toml", "pom.xml",
    "build.gradle", "build.gradle.kts", "settings.gradle", "gradlew", "Gemfile", "composer.json", "pubspec.yaml",
    "Package.swift", "Podfile", "CMakeLists.txt", "Makefile", "AndroidManifest.xml", "Info.plist", "mix.exs",
}
MANIFEST_SUFFIXES = (".csproj", ".sln", ".pbxproj")

# Languages whose test execution RepoPilot can actually run in its sandbox today.
EXECUTABLE_TEST_LANGUAGES = {"Python"}

STOPWORDS = {
    "the", "and", "that", "this", "with", "when", "from", "have", "has", "was", "are", "not", "but", "for", "its",
    "can", "should", "would", "could", "does", "doesn", "into", "than", "then", "there", "their", "they", "them",
    "you", "your", "our", "out", "all", "any", "get", "got", "gets", "api", "bug", "issue", "error", "returns",
    "return", "returned", "find", "cause", "fix", "propose", "user", "users", "submits", "submit", "instead",
    "expected", "actual", "happens", "happen", "after", "before", "while", "because", "which", "what", "where",
    "about", "also", "just", "some", "only", "very", "using", "used", "use", "make", "makes", "need", "needs",
    "please", "like", "see", "been", "being", "were", "will", "none", "true", "false",
}

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([\w<>\.]+))?')
_JS_FRAME = re.compile(r"(?:at\s+(?:([\w$.<>\[\] ]+?)\s+\()?)([^\s()]+?\.(?:js|jsx|ts|tsx|mjs|cjs)):(\d+)(?::\d+)?\)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_QUOTED = re.compile(r"[`'\"]([^`'\"\n]{2,60})[`'\"]")
_EXTENSIONS = "|".join(sorted((e.lstrip(".") for e in LANGUAGE_BY_EXTENSION), key=len, reverse=True))
_PATHISH = re.compile(rf"[\w\-./]+\.(?:{_EXTENSIONS})\b")
# Stack-trace frames of other ecosystems: Java/Kotlin "(Main.java:42)", Go/Rust/Swift/Ruby "file.go:42[:7]", C# ".cs:line 42",
# Dart "foo.dart 12:5", PHP "x.php on line 12".
_GENERIC_FRAME = re.compile(rf"([\w\-./\\$@]+\.(?:{_EXTENSIONS})):(?:line\s+)?(\d+)(?::\d+)?")
_PHP_FRAME = re.compile(r"([\w\-./\\]+\.php)(?:\s+on\s+line\s+|\()(\d+)")
_DART_FRAME = re.compile(r"([\w\-./\\:]+\.dart)\s+(\d+):\d+")


_DEFINITION = re.compile(
    r"\s*(?:(?:export|default|public|private|protected|internal|static|final|abstract|open|override|suspend|async|pub|unsafe|inline|"
    r"virtual|data|sealed|const|extern|external|late|mutating|fileprivate)\s+)*"
    r"(?:function\*?|class|struct|enum|interface|trait|impl|object|protocol|extension|func|fn|def|fun|defmodule|module|namespace)\s+"
    r"([A-Za-z_$][\w$]*)|\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\("
)
# C-family / JVM / .NET method headers: "<modifiers> ReturnType name(args) {"
_TYPED_METHOD = re.compile(
    r"\s*(?:(?:public|private|protected|internal|static|final|virtual|override|async|inline|extern|unsafe|synchronized|abstract)\s+)*"
    r"[A-Za-z_][\w<>\[\],.:?*&\s]*?\s+\*?&?([A-Za-z_]\w*)\s*\([^;)]*\)?[^;]*\{\s*$"
)
_NOT_NAMES = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try", "synchronized", "using", "lock", "foreach", "elif"}


@dataclass
class Frame:
    path: str
    line: int
    function: str | None = None


@dataclass
class RankedFile:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    match_lines: list[int] = field(default_factory=list)


@dataclass
class RepoProfile:
    primary_language: str | None
    languages: dict[str, int]
    manifests: list[str]
    test_frameworks: list[str]
    tree_summary: str
    supported: bool
    support_note: str
    validation_language: str | None  # language we can run tests for (currently Python only)
    has_tests: bool
    frameworks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)  # inferred, informational unless the language is executable


class RepositoryAnalyzer:
    # --- Profile -----------------------------------------------------------------------------------
    def profile(self, index: RepoIndex) -> RepoProfile:
        counts: Counter[str] = Counter(f.language for f in index.files if f.language)
        primary = counts.most_common(1)[0][0] if counts else None
        manifests = sorted({
            f.path for f in index.files
            if f.path.rsplit("/", 1)[-1] in MANIFEST_NAMES or f.path.endswith(MANIFEST_SUFFIXES)
        }, key=lambda p: (p.count("/"), p))[:25]
        stack = detect_stack(index)
        frameworks = sorted(set(self._detect_test_frameworks(index, primary)) | set(stack.test_frameworks), key=str.lower)
        commands = list(stack.test_commands)
        if primary == "Python":
            commands = [*(["pytest"] if "pytest" in frameworks else []),
                        *(["python -m unittest"] if "unittest" in frameworks and "pytest" not in frameworks else []), *commands]
        has_tests = any(self._is_test_path(f.path) for f in index.files)

        if primary is None:
            supported, note = False, "No recognizable source files were found in this repository."
        elif primary == "Python":
            supported = True
            note = "Python is fully supported: analysis, patch generation and (when the sandbox is enabled) test validation."
        else:
            supported = True
            ran = f" Detected test command: {commands[0]}." if commands else ""
            note = (
                f"{primary} is analysed and patched from repository evidence. Test execution is Python-only today, "
                f"so validation will be reported as not run.{ran}"
            )

        return RepoProfile(
            primary_language=primary,
            languages=dict(counts.most_common(8)),
            manifests=manifests,
            test_frameworks=frameworks,
            tree_summary=self._tree_summary(index),
            supported=supported,
            support_note=note,
            validation_language="Python" if primary in EXECUTABLE_TEST_LANGUAGES else None,
            has_tests=has_tests,
            frameworks=stack.frameworks,
            dependencies=stack.dependencies,
            test_commands=commands[:5],
        )

    @staticmethod
    def _is_test_path(path: str) -> bool:
        lowered = path.lower()
        name = lowered.rsplit("/", 1)[-1]
        parts = lowered.split("/")
        stem = name.rsplit(".", 1)[0]
        return (
            any(p in {"test", "tests", "__tests__", "spec", "specs", "androidtest", "unittest", "uitests", "testing"} for p in parts[:-1])
            or name.startswith("test_")
            or name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts", ".test.tsx", ".spec.tsx", ".test.jsx", ".spec.jsx",
                              "_test.go", "_test.dart", "_test.rs", "_spec.rb", "_test.rb", "_test.exs", "_test.cc", "_test.cpp"))
            or stem.endswith(("test", "tests", "spec")) and not stem.endswith(("latest", "contest"))
            and name.rsplit(".", 1)[-1] in {"java", "kt", "swift", "cs", "php", "scala", "m"}
        )

    def _detect_test_frameworks(self, index: RepoIndex, primary: str | None) -> list[str]:
        found: set[str] = set()
        paths = {f.path for f in index.files}
        names = {p.rsplit("/", 1)[-1] for p in paths}
        if primary == "Python":
            if "pytest.ini" in names or "conftest.py" in names:
                found.add("pytest")
            for manifest in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.cfg", "tox.ini", "Pipfile"):
                for p in paths:
                    if p.rsplit("/", 1)[-1] == manifest and "pytest" in self._safe_read(index, p, 40_000).lower():
                        found.add("pytest")
            py_tests = [p for p in paths if p.endswith(".py") and self._is_test_path(p)]
            for p in py_tests[:40]:
                text = self._safe_read(index, p, 20_000)
                if re.search(r"^\s*import unittest|^\s*from unittest", text, re.M):
                    found.add("unittest")
                if re.search(r"^\s*import pytest|^\s*from pytest", text, re.M) or re.search(r"^def test_\w+", text, re.M):
                    found.add("pytest")
        elif primary in {"JavaScript", "TypeScript"}:
            for p in paths:
                if p.rsplit("/", 1)[-1] == "package.json":
                    try:
                        data = json.loads(self._safe_read(index, p, 100_000))
                    except json.JSONDecodeError:
                        continue
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    for fw in ("jest", "vitest", "mocha", "jasmine", "ava"):
                        if fw in deps:
                            found.add(fw)
        return sorted(found)

    @staticmethod
    def _safe_read(index: RepoIndex, rel: str, max_bytes: int) -> str:
        try:
            return index.read_text(rel, max_bytes=max_bytes)
        except Exception:  # noqa: BLE001 - unreadable file is simply skipped for detection
            return ""

    @staticmethod
    def _tree_summary(index: RepoIndex, max_lines: int = 60) -> str:
        top: Counter[str] = Counter()
        for f in index.files:
            parts = f.path.split("/")
            top["/".join(parts[:2]) + "/" if len(parts) > 2 else (parts[0] + "/" if len(parts) > 1 else parts[0])] += 1
        lines = [f"{name} ({n} files)" if name.endswith("/") else name for name, n in sorted(top.items())]
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... and {len(lines) - max_lines} more entries"]
        return "\n".join(lines)

    # --- Bug-report understanding ------------------------------------------------------------------
    def extract_frames(self, text: str, index: RepoIndex) -> list[Frame]:
        """Find stack-trace frames that map to real files in the repo (suffix match)."""
        paths = [f.path for f in index.files]
        frames: list[Frame] = []
        seen: set[tuple[str, int]] = set()

        def resolve(candidate: str) -> str | None:
            candidate = candidate.replace("\\", "/")
            matches = [p for p in paths if candidate.endswith(p) or p.endswith(candidate.lstrip("./"))]
            if not matches:
                base = candidate.rsplit("/", 1)[-1]
                matches = [p for p in paths if p.rsplit("/", 1)[-1] == base]
            return min(matches, key=len) if matches else None

        for m in _PY_FRAME.finditer(text or ""):
            path = resolve(m.group(1))
            if path and (path, int(m.group(2))) not in seen:
                seen.add((path, int(m.group(2))))
                frames.append(Frame(path, int(m.group(2)), m.group(3)))
        for m in _JS_FRAME.finditer(text or ""):
            path = resolve(m.group(2))
            if path and (path, int(m.group(3))) not in seen:
                seen.add((path, int(m.group(3))))
                frames.append(Frame(path, int(m.group(3)), (m.group(1) or "").strip() or None))
        for pattern in (_GENERIC_FRAME, _PHP_FRAME, _DART_FRAME):
            for m in pattern.finditer(text or ""):
                path = resolve(m.group(1))
                line = int(m.group(2))
                if path and (path, line) not in seen:
                    seen.add((path, line))
                    frames.append(Frame(path, line))
        return frames

    def extract_keywords(self, text: str, extra: list[str] | None = None, limit: int = 25) -> list[str]:
        """Identifiers, quoted strings and filenames from the bug report, ranked by usefulness."""
        text = text or ""
        weighted: Counter[str] = Counter()
        for m in _QUOTED.finditer(text):
            for ident in _IDENT.findall(m.group(1)):
                weighted[ident.lower()] += 3
        for m in _PATHISH.finditer(text):
            weighted[m.group(0).rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()] += 4
        for ident in _IDENT.findall(text):
            low = ident.lower()
            if low in STOPWORDS or len(low) < 3:
                continue
            bonus = 2 if ("_" in ident or (ident != ident.lower() and ident != ident.upper())) else 1
            weighted[low] += bonus
            if "_" in ident:
                for piece in ident.split("_"):
                    if len(piece) > 3 and piece.lower() not in STOPWORDS:
                        weighted[piece.lower()] += 1
        for term in extra or []:
            for ident in _IDENT.findall(term):
                weighted[ident.lower()] += 3
        return [w for w, _ in weighted.most_common(limit)]

    # --- Ranking -----------------------------------------------------------------------------------
    def rank_files(
        self,
        index: RepoIndex,
        keywords: list[str],
        frames: list[Frame],
        limit: int = 20,
    ) -> list[RankedFile]:
        """Targeted search: score files by stack-frame hits, definition-name hits, filename hits and keyword density."""
        frame_files: dict[str, list[int]] = {}
        for fr in frames:
            frame_files.setdefault(fr.path, []).append(fr.line)
        kw = [k for k in keywords if k]
        ranked: list[RankedFile] = []

        for f in index.files:
            if not f.language:
                continue
            is_test = self._is_test_path(f.path)
            score = 0.0
            reasons: list[str] = []
            lines: list[int] = []
            if f.path in frame_files:
                score += 12
                lines += frame_files[f.path]
                reasons.append(f"appears in the stack trace (line {', '.join(map(str, sorted(set(frame_files[f.path]))))})")
            name = f.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
            name_hits = [k for k in kw if k in name or name in k and len(name) > 3]
            if name_hits:
                score += 3 + len(name_hits)
                reasons.append(f"file name matches '{name_hits[0]}'")

            text = self._safe_read(index, f.path, 200_000)
            if not text:
                continue
            lowered = text.lower()
            total_hits = 0
            matched_terms: list[str] = []
            for k in kw:
                n = lowered.count(k)
                if n:
                    total_hits += min(n, 10)
                    matched_terms.append(k)
                    if len(lines) < 12:
                        for ln, line in enumerate(text.splitlines(), 1):
                            if k in line.lower():
                                lines.append(ln)
                                if len(lines) >= 12:
                                    break
            if matched_terms:
                score += math.log1p(total_hits) * 2 + len(matched_terms)
                reasons.append("mentions " + ", ".join(f"'{t}'" for t in matched_terms[:4]))

            if f.language == "Python":
                for sym in self._python_symbols(text):
                    if any(k in sym[0].lower() for k in kw):
                        score += 5
                        lines.append(sym[1])
                        reasons.append(f"defines '{sym[0]}' (line {sym[1]})")
                        break
            if is_test:
                score *= 0.4  # tests are context, rarely the place to patch
            if score > 0:
                ranked.append(RankedFile(f.path, round(score, 2), reasons[:4], sorted(set(lines))[:12]))

        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked[:limit]

    # --- Code navigation ---------------------------------------------------------------------------
    @staticmethod
    def _python_symbols(text: str) -> list[tuple[str, int, int]]:
        """(name, start_line, end_line) for every function/class, via ast. Empty if the file doesn't parse."""
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            return []
        out: list[tuple[str, int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((node.name, node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno))
        return sorted(out, key=lambda s: s[1])

    def outline(self, path: str, text: str) -> str:
        if path.endswith((".py", ".pyi")):
            symbols = self._python_symbols(text)
            return "\n".join(f"  {name} (lines {start}-{end})" for name, start, end in symbols[:80])
        found = []
        for ln, line in enumerate(text.splitlines(), 1):
            m = _DEFINITION.match(line) or _TYPED_METHOD.match(line)
            if m:
                name = next(g for g in m.groups() if g)
                if name not in _NOT_NAMES:
                    found.append(f"  {name} (line {ln})")
        return "\n".join(found[:80])

    def render_context(
        self,
        path: str,
        text: str,
        focus_lines: list[int],
        char_budget: int,
    ) -> str:
        """Numbered source for one file. Whole file when it fits, otherwise outline + windows around focus lines."""
        lines = text.splitlines()
        numbered = [f"{i:>5}| {line}" for i, line in enumerate(lines, 1)]
        whole = "\n".join(numbered)
        if len(whole) <= char_budget:
            return whole

        windows: list[tuple[int, int]] = []
        for ln in sorted(set(focus_lines)):
            start, end = max(1, ln - 20), min(len(lines), ln + 40)
            if path.endswith(".py"):  # snap to the enclosing function when possible
                for _, s, e in self._python_symbols(text):
                    if s <= ln <= e and e - s <= 120:
                        start, end = min(start, s), max(end, e)
            if windows and start <= windows[-1][1] + 3:
                windows[-1] = (windows[-1][0], max(windows[-1][1], end))
            else:
                windows.append((start, end))
        if not windows:
            windows = [(1, min(len(lines), 80))]

        out: list[str] = []
        used = 0
        cursor = 1
        for start, end in windows:
            if start > cursor:
                out.append(f"      | ... (lines {cursor}-{start - 1} omitted) ...")
            chunk = "\n".join(numbered[start - 1 : end])
            if used + len(chunk) > char_budget:
                chunk = chunk[: max(0, char_budget - used)]
                out.append(chunk + "\n      | ... (truncated) ...")
                return "\n".join(out)
            out.append(chunk)
            used += len(chunk)
            cursor = end + 1
        if cursor <= len(lines):
            out.append(f"      | ... (lines {cursor}-{len(lines)} omitted) ...")
        return "\n".join(out)

    @staticmethod
    def slice_lines(text: str, start: int, end: int) -> str:
        lines = text.splitlines()
        start = max(1, start)
        end = min(len(lines), max(start, end))
        return "\n".join(lines[start - 1 : end])
