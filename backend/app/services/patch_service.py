"""Patch construction and validation.

Design: asking an LLM to hand-write a unified diff is unreliable (wrong line numbers, bad context). Instead the
model returns *edits* (exact ``search`` text -> ``replace`` text). We apply them in memory, generate the unified
diff ourselves, and then independently re-validate that diff: strict parse, path/size/protected-file checks, and a
zero-fuzz dry-run applying the diff to the original files. Only a diff that passes is ever shown or applied.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.core.errors import PatchRejected, UnsafePathError
from app.core.security import normalize_repo_path, protected_reason, resolve_inside
from app.schemas.llm import EditIn, RegressionTestIn
from app.schemas.models import FileChange, RegressionTest
from app.services.repository_service import RepoIndex

NOEOL = "\x00NOEOL"  # sentinel carried on a file's last line when it has no trailing newline
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_MAX_ORIGINAL_BYTES_IN_RESULT = 60_000

_REGRESSION_DENYLIST = re.compile(
    r"\b(subprocess|socket|ctypes|os\.system|os\.popen|os\.exec\w*|os\.spawn\w*|__import__|importlib|eval|exec|"
    r"shutil\.rmtree|urllib|requests|httpx|http\.client)\b"
)


# --- line model -------------------------------------------------------------------------------------------

def decompose(text: str) -> tuple[list[str], bool]:
    """Split text into lines (without terminators). Returns (lines, uses_crlf).

    The last line carries NOEOL when the file does not end with a newline.
    """
    if "\r\n" in text:
        if re.search(r"(?<!\r)\n", text):
            raise PatchRejected("File has mixed line endings; refusing to patch it.")
        crlf = True
        text = text.replace("\r\n", "\n")
    else:
        crlf = False
    if text == "":
        return [], crlf
    parts = text.split("\n")
    if parts[-1] == "":
        parts.pop()
    else:
        parts[-1] += NOEOL
    return parts, crlf


def compose(lines: list[str], crlf: bool) -> str:
    if not lines:
        return ""
    out = list(lines)
    eof_newline = True
    if out[-1].endswith(NOEOL):
        out[-1] = out[-1][: -len(NOEOL)]
        eof_newline = False
    text = "\n".join(out) + ("\n" if eof_newline else "")
    return text.replace("\n", "\r\n") if crlf else text


# --- diff generation --------------------------------------------------------------------------------------

def _range(start: int, end: int) -> str:
    length = end - start
    if length == 0:
        return f"{start},0"
    if length == 1:
        return f"{start + 1}"
    return f"{start + 1},{length}"


def make_unified_diff(path: str, old: list[str], new: list[str]) -> tuple[str, int, int]:
    """Return (diff_text, additions, deletions) for one file; empty diff when identical."""
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    out: list[str] = []
    additions = deletions = 0

    def emit(prefix: str, line: str) -> None:
        text = line[: -len(NOEOL)] if line.endswith(NOEOL) else line
        out.append(prefix + text)
        if line.endswith(NOEOL):
            out.append("\\ No newline at end of file")

    for group in matcher.get_grouped_opcodes(3):
        a0, a1 = group[0][1], group[-1][2]
        b0, b1 = group[0][3], group[-1][4]
        out.append(f"@@ -{_range(a0, a1)} +{_range(b0, b1)} @@")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in old[i1:i2]:
                    emit(" ", line)
            else:
                if tag in ("replace", "delete"):
                    for line in old[i1:i2]:
                        emit("-", line)
                        deletions += 1
                if tag in ("replace", "insert"):
                    for line in new[j1:j2]:
                        emit("+", line)
                        additions += 1
    if not out:
        return "", 0, 0
    return f"--- a/{path}\n+++ b/{path}\n" + "\n".join(out) + "\n", additions, deletions


# --- diff parsing / strict application --------------------------------------------------------------------

@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_len: int
    lines: list[tuple[str, str]] = field(default_factory=list)  # (prefix, text-with-NOEOL-if-marked)


@dataclass
class FilePatch:
    path: str
    hunks: list[Hunk] = field(default_factory=list)


def parse_unified_diff(diff: str) -> list[FilePatch]:
    if not diff or not diff.strip():
        raise PatchRejected("The patch is empty.")
    if "\x00" in diff:
        raise PatchRejected("The patch contains binary data.")
    lines = diff.rstrip("\n").split("\n")
    patches: list[FilePatch] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("--- "):
            raise PatchRejected(f"Malformed patch: unexpected line {line[:60]!r}")
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise PatchRejected("Malformed patch: missing '+++' header.")
        old_path, new_path = line[4:].strip(), lines[i + 1][4:].strip()
        if old_path == "/dev/null" or new_path == "/dev/null":
            raise PatchRejected("Creating or deleting files is not allowed in a repair patch.")
        if not old_path.startswith("a/") or not new_path.startswith("b/") or old_path[2:] != new_path[2:]:
            raise PatchRejected("Malformed patch headers (expected matching 'a/<path>' and 'b/<path>').")
        try:
            path = normalize_repo_path(new_path[2:])
        except UnsafePathError as exc:
            raise PatchRejected(exc.message) from None
        patch = FilePatch(path=path)
        i += 2
        while i < len(lines) and lines[i].startswith("@@"):
            m = _HUNK_RE.match(lines[i])
            if not m:
                raise PatchRejected(f"Malformed hunk header: {lines[i][:60]!r}")
            hunk = Hunk(
                old_start=int(m.group(1)),
                old_len=int(m.group(2)) if m.group(2) is not None else 1,
                new_len=int(m.group(4)) if m.group(4) is not None else 1,
            )
            i += 1
            while i < len(lines) and _is_body_line(hunk, lines[i]):
                body = lines[i]
                if body.startswith("\\"):
                    if not hunk.lines:
                        raise PatchRejected("Malformed patch: stray 'No newline' marker.")
                    prefix, text = hunk.lines[-1]
                    hunk.lines[-1] = (prefix, text + NOEOL)
                elif body[:1] in (" ", "+", "-"):
                    hunk.lines.append((body[0], body[1:]))
                else:
                    raise PatchRejected(f"Malformed patch line: {body[:60]!r}")
                i += 1
            old_count = sum(1 for p, _ in hunk.lines if p in " -")
            new_count = sum(1 for p, _ in hunk.lines if p in " +")
            if old_count != hunk.old_len or new_count != hunk.new_len:
                raise PatchRejected("Malformed patch: hunk line counts do not match its header.")
            patch.hunks.append(hunk)
        if not patch.hunks:
            raise PatchRejected(f"Malformed patch: no hunks for {path}.")
        patches.append(patch)
    return patches


def _is_body_line(hunk: Hunk, line: str) -> bool:
    """Does ``line`` belong to the current hunk body (rather than starting a new hunk or file)?

    A removed line whose text starts with '-- ' looks like a '--- ' file header, so while the hunk still
    expects more old-side lines we treat it as body.
    """
    if line.startswith("@@"):
        return False
    if line.startswith("--- "):
        return sum(1 for p, _ in hunk.lines if p in " -") < hunk.old_len
    return True


def apply_file_patch(old_lines: list[str], patch: FilePatch) -> list[str]:
    """Strict (zero-fuzz) application of one file's hunks."""
    result: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        start = hunk.old_start - 1 if hunk.old_len > 0 else hunk.old_start
        if start < cursor or start > len(old_lines):
            raise PatchRejected(f"Hunk for {patch.path} is out of order or out of range.")
        expected = [t for p, t in hunk.lines if p in " -"]
        if old_lines[start : start + len(expected)] != expected:
            raise PatchRejected(f"Hunk for {patch.path} does not match the file content at line {start + 1}.")
        result.extend(old_lines[cursor:start])
        result.extend(t for p, t in hunk.lines if p in " +")
        cursor = start + len(expected)
    result.extend(old_lines[cursor:])
    # A NOEOL marker can only legitimately sit on the final line.
    for line in result[:-1]:
        if line.endswith(NOEOL):
            raise PatchRejected(f"Hunk for {patch.path} places a 'no newline' marker mid-file.")
    return result


# --- results ----------------------------------------------------------------------------------------------

@dataclass
class PatchBuild:
    diff: str = ""
    changes: list[FileChange] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.diff) and not self.problems


class PatchService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    # --- edits -> validated diff ---------------------------------------------------------------------
    def build_patch(self, edits: list[EditIn], index: RepoIndex) -> PatchBuild:
        build = PatchBuild()
        if not edits:
            build.problems.append("The model returned no edits.")
            return build

        known = index.by_path()
        originals: dict[str, str] = {}
        working: dict[str, list[str]] = {}
        crlf_flags: dict[str, bool] = {}
        explanations: dict[str, list[str]] = {}

        for n, edit in enumerate(edits, 1):
            label = f"edit {n}"
            try:
                path = normalize_repo_path(edit.path)
                resolve_inside(index.root, path)
            except UnsafePathError as exc:
                build.problems.append(f"{label}: {exc.message}")
                continue
            reason = protected_reason(path)
            if reason:
                build.problems.append(f"{label}: {path} is protected — {reason}.")
                continue
            if path not in known:
                build.problems.append(f"{label}: {path} is not an existing text file in the repository.")
                continue
            if path not in working:
                try:
                    text = index.read_text(path)
                    originals[path] = text
                    working[path], crlf_flags[path] = decompose(text)
                except (PatchRejected, OSError, UnicodeError) as exc:
                    build.problems.append(f"{label}: cannot read {path} ({getattr(exc, 'message', exc)}).")
                    continue
            if edit.search == edit.replace:
                build.problems.append(f"{label}: replacement is identical to the original text.")
                continue
            problem = self._apply_edit(working, path, edit)
            if problem:
                build.problems.append(f"{label} ({path}): {problem}")
                continue
            if edit.explanation:
                explanations.setdefault(path, []).append(edit.explanation.strip())

        if len(working) > self._s.max_patch_files:
            build.problems.append(f"The patch touches {len(working)} files; the limit is {self._s.max_patch_files}.")
        if build.problems:
            return build

        diffs: list[str] = []
        patched_text: dict[str, str] = {}
        for path, new_lines in working.items():
            old_lines, _ = decompose(originals[path])
            diff, adds, dels = make_unified_diff(path, old_lines, new_lines)
            if not diff:
                continue
            problem = self._check_syntax(path, compose(new_lines, crlf_flags[path]))
            if problem:
                build.problems.append(problem)
                continue
            diffs.append(diff)
            patched_text[path] = compose(new_lines, crlf_flags[path])
            build.changes.append(
                FileChange(
                    path=path,
                    explanation=" ".join(explanations.get(path, [])) or "Modified by the repair.",
                    additions=adds,
                    deletions=dels,
                    original_content=originals[path][:_MAX_ORIGINAL_BYTES_IN_RESULT],
                    patched_content=patched_text[path][:_MAX_ORIGINAL_BYTES_IN_RESULT],
                )
            )
        if build.problems:
            return build
        if not diffs:
            build.problems.append("The edits produced no change to any file.")
            return build

        build.diff = "".join(diffs)
        try:
            checked = self.validate_diff(build.diff, index)
        except PatchRejected as exc:
            build.problems.append(f"Generated diff failed validation: {exc.message}")
            build.diff = ""
            return build
        # Self-consistency: applying the diff must reproduce exactly what the edits produced.
        for path, text in patched_text.items():
            if checked.get(path) != text:
                build.problems.append("Internal consistency check failed: the diff does not reproduce the edits.")
                build.diff = ""
                return build
        return build

    @staticmethod
    def _apply_edit(working: dict[str, list[str]], path: str, edit: EditIn) -> str | None:
        lines = working[path]
        search_lines, _ = decompose(edit.search.replace("\r\n", "\n"))
        search_lines = [s.removesuffix(NOEOL) for s in search_lines]
        replace_lines, _ = decompose(edit.replace.replace("\r\n", "\n"))
        replace_lines = [s.removesuffix(NOEOL) for s in replace_lines]
        # tolerate a trailing newline difference in the model's snippet
        while search_lines and search_lines[-1] == "" and len(search_lines) > 1:
            search_lines.pop()
        plain = [ln.removesuffix(NOEOL) for ln in lines]

        def matches(norm) -> list[int]:
            n = len(search_lines)
            target = [norm(s) for s in search_lines]
            return [i for i in range(len(plain) - n + 1) if [norm(x) for x in plain[i : i + n]] == target]

        hits = matches(lambda s: s)
        if not hits:
            hits = matches(lambda s: s.rstrip())  # tolerate trailing-whitespace differences only
        if not hits:
            return "the 'search' text was not found in the file (it must be copied exactly)."
        if len(hits) > 1:
            return f"the 'search' text matches {len(hits)} places; include more surrounding lines to make it unique."
        i = hits[0]
        n = len(search_lines)
        was_last = i + n == len(lines) and lines[-1].endswith(NOEOL)
        new_block = list(replace_lines)
        if was_last and new_block:
            new_block[-1] += NOEOL  # keep the file's "no trailing newline" state
        lines[i : i + n] = new_block
        return None

    @staticmethod
    def _check_syntax(path: str, text: str) -> str | None:
        if path.endswith((".py", ".pyi")):
            try:
                ast.parse(text)
            except SyntaxError as exc:
                return f"{path}: the patched file would not be valid Python (line {exc.lineno}: {exc.msg})."
        return None

    # --- diff validation / application ----------------------------------------------------------------
    def validate_diff(self, diff: str, index: RepoIndex) -> dict[str, str]:
        """Validate a unified diff against the real files and return {path: patched_text}. Never writes."""
        if len(diff.encode("utf-8", errors="replace")) > self._s.max_patch_bytes:
            raise PatchRejected(f"The patch is larger than the {self._s.max_patch_bytes} byte limit.")
        patches = parse_unified_diff(diff)
        if len(patches) > self._s.max_patch_files:
            raise PatchRejected(f"The patch touches more than {self._s.max_patch_files} files.")
        seen: set[str] = set()
        known = index.by_path()
        result: dict[str, str] = {}
        for patch in patches:
            if patch.path in seen:
                raise PatchRejected(f"{patch.path} appears twice in the patch.")
            seen.add(patch.path)
            reason = protected_reason(patch.path)
            if reason:
                raise PatchRejected(f"{patch.path} is protected: {reason}.")
            if patch.path not in known:
                raise PatchRejected(f"{patch.path} is not an existing text file in the repository.")
            try:
                resolve_inside(index.root, patch.path)
            except UnsafePathError as exc:
                raise PatchRejected(exc.message) from None
            old_lines, crlf = decompose(index.read_text(patch.path))
            result[patch.path] = compose(apply_file_patch(old_lines, patch), crlf)
        return result

    def apply_to_directory(self, diff: str, index: RepoIndex, target_root: Path) -> list[str]:
        """Apply an already-validated diff to a *disposable copy* of the repo. Returns the changed paths."""
        patched = self.validate_diff(diff, index)
        changed: list[str] = []
        for path, text in patched.items():
            destination = resolve_inside(target_root, path)  # must exist in the copy and stay inside it
            destination.write_text(text, encoding="utf-8", newline="")
            changed.append(path)
        return changed

    # --- regression test -------------------------------------------------------------------------------
    def prepare_regression_test(self, proposal: RegressionTestIn | None, index: RepoIndex) -> tuple[RegressionTest | None, str | None]:
        """Validate a model-proposed pytest file. Returns (test, rejection_reason)."""
        if proposal is None or not proposal.content.strip():
            return None, None
        content = proposal.content.strip("\n") + "\n"
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return None, f"proposed regression test is not valid Python (line {exc.lineno}: {exc.msg})"
        if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in ast.walk(tree)):
            return None, "proposed regression test contains no test_ function"
        banned = _REGRESSION_DENYLIST.search(content)
        if banned:
            return None, f"proposed regression test uses a disallowed construct ({banned.group(1)})"
        known = index.by_path()
        directory = "tests/" if any(p.startswith("tests/") for p in known) else ("test/" if any(p.startswith("test/") for p in known) else "")
        name = "test_repopilot_regression.py"
        path = directory + name
        counter = 2
        while path in known:
            path = f"{directory}test_repopilot_regression_{counter}.py"
            counter += 1
        return RegressionTest(path=path, description=proposal.description.strip(), content=content), None
