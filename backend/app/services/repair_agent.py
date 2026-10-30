"""The repair agent: clone -> analyze -> plan -> retrieve -> diagnose -> patch -> validate.

Every progress event is emitted by a real step that actually ran. Nothing is claimed that was not checked:
evidence quotes are verified against the real files, patches against the real code, and validation status comes
from real exit codes (or is ``not_run``).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
from collections import Counter
from typing import Protocol

from app.core.config import Settings
from app.core.errors import AppError, LLMOutputError, LLMUnavailable, UnsupportedRepository
from app.core.security import normalize_repo_path, parse_github_url, protected_reason
from app.prompts import templates
from app.schemas.llm import DiagnosisResponse, EvidenceIn, PatchResponse, PlanResponse
from app.schemas.models import (
    Attempt,
    Evidence,
    Hypothesis,
    RelevantFile,
    RepairRequest,
    RepairResult,
    RepositoryInfo,
    ResearchReport,
    Validation,
    ValidationStatus,
)
from app.services import validation_service as vs
from app.services.llm_service import LLMService
from app.services.patch_service import PatchBuild, PatchService
from app.services.project_insights import assess_quality, summarize_structure
from app.services.repository_analyzer import RankedFile, RepoProfile, RepositoryAnalyzer
from app.services.repository_service import (
    RepoIndex,
    RepositoryService,
    Workspace,
    make_readable_for_sandbox,
)
from app.services.research_service import (
    ResearchService,
    clean_text,
    fallback_queries,
    official_domains,
    relevant_frameworks,
    sanitize_queries,
)
from app.services.validation_service import ValidationService

logger = logging.getLogger(__name__)

EventDetail = dict[str, str | int | float | bool | None]

# Output-token caps per step. Providers count the requested ceiling against tokens-per-minute limits,
# so each step asks only for what it needs.
MIN_QUOTE_CHARS = 8  # shorter quotes (e.g. a lone `return`) are too generic to count as evidence
PLAN_MAX_TOKENS = 1400
DIAGNOSE_MAX_TOKENS = 2600
PATCH_MAX_TOKENS = 2800


class Progress(Protocol):
    def emit(self, stage: str, status: str, message: str, detail: EventDetail | None = None) -> None: ...
    def set_repository(self, info: RepositoryInfo) -> None: ...
    def set_result(self, result: RepairResult) -> None: ...


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def locate_quote(lines: list[str], quote: str, cited_line: int = 1) -> tuple[int, int] | None:
    """Find where ``quote`` really appears in a file, ignoring whitespace and blank-line differences.

    Returns 1-based (start_line, end_line), preferring the occurrence closest to ``cited_line``, or None when the
    quoted code does not exist in the file (i.e. the model's evidence is not real).
    """
    wanted = _norm(quote)
    if not wanted:
        return None
    parts: list[str] = []
    spans: list[tuple[int, int]] = []  # (offset in the joined text, 1-based line number)
    pos = 0
    for number, raw in enumerate(lines, 1):
        text = _norm(raw)
        if not text:
            continue
        if parts:
            pos += 1  # the joining space
        spans.append((pos, number))
        parts.append(text)
        pos += len(text)
    haystack = " ".join(parts)

    def line_at(offset: int) -> int:
        lo, hi = 0, len(spans) - 1
        while lo < hi:  # last span that starts at or before offset
            mid = (lo + hi + 1) // 2
            if spans[mid][0] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return spans[lo][1]

    hits: list[int] = []
    at = haystack.find(wanted)
    while at != -1:
        hits.append(at)
        at = haystack.find(wanted, at + 1)
    if not hits:
        return None
    best = min(hits, key=lambda h: abs(line_at(h) - cited_line))
    return line_at(best), line_at(best + len(wanted) - 1)


class RepairAgent:
    def __init__(
        self,
        settings: Settings,
        llm: LLMService,
        repos: RepositoryService,
        analyzer: RepositoryAnalyzer,
        patches: PatchService,
        validator: ValidationService,
        research: ResearchService | None = None,
    ) -> None:
        self._s = settings
        self._research = research or ResearchService(settings)
        self._llm = llm
        self._repos = repos
        self._analyzer = analyzer
        self._patches = patches
        self._validator = validator

    # ======================================================================================================
    async def run(self, request: RepairRequest, workspace: Workspace, progress: Progress) -> None:
        owner, repo = parse_github_url(request.repository_url)

        # ---- 1. clone ---------------------------------------------------------------------------------
        progress.emit("clone", "started", f"Checking {owner}/{repo} on GitHub")
        meta = await self._repos.fetch_metadata(owner, repo)
        progress.emit(
            "clone", "info",
            f"Public repository found: {meta.size_kb} KB, default branch '{meta.default_branch}'",
            {"size_kb": meta.size_kb, "stars": meta.stars},
        )
        progress.emit("clone", "started", "Shallow-cloning into an isolated workspace")
        sha = await self._repos.clone(owner, repo, workspace)
        index = await asyncio.to_thread(self._repos.index, workspace.repo_dir)
        progress.emit(
            "clone", "completed",
            f"Cloned commit {sha[:8]}; indexed {len(index.files)} text files ({index.skipped} skipped)",
            {"files": len(index.files), "skipped": index.skipped},
        )

        # ---- 2. analyze -------------------------------------------------------------------------------
        progress.emit("analyze", "started", "Detecting language, dependencies and test framework")
        profile = await asyncio.to_thread(self._analyzer.profile, index)
        structure, entry_points = await asyncio.to_thread(summarize_structure, index)
        quality = await asyncio.to_thread(assess_quality, index)
        info = RepositoryInfo(
            url=request.repository_url, owner=owner, name=meta.name, description=meta.description,
            default_branch=meta.default_branch, commit_sha=sha, stars=meta.stars, size_kb=meta.size_kb,
            primary_language=profile.primary_language, languages=profile.languages,
            source_file_count=len(index.files), manifests=profile.manifests, test_frameworks=profile.test_frameworks,
            tree_summary=profile.tree_summary, supported=profile.supported, support_note=profile.support_note,
            frameworks=profile.frameworks, dependencies=profile.dependencies, test_commands=profile.test_commands,
            validation_supported=profile.validation_language is not None,
            structure=structure, entry_points=entry_points, quality=quality,
        )
        progress.set_repository(info)
        if not profile.supported:
            raise UnsupportedRepository(profile.support_note)
        progress.emit(
            "analyze", "completed",
            self._project_label(profile)
            + (f" ({', '.join(profile.frameworks[:4])})" if profile.frameworks else "")
            + f"; test framework: {', '.join(profile.test_frameworks) or 'none detected'}",
            {"language": profile.primary_language, "frameworks": ", ".join(profile.frameworks),
             "test_frameworks": ", ".join(profile.test_frameworks)},
        )
        progress.emit(
            "analyze", "info",
            f"Mapped {len(structure)} folders and {len(entry_points)} entry points; "
            f"{sum(1 for q in quality if q.severity == 'warning')} code-health warnings, "
            f"{sum(1 for q in quality if q.severity == 'info')} notes",
        )

        # ---- 3. targeted search -----------------------------------------------------------------------
        progress.emit("retrieve", "started", "Searching the repository for code related to the bug report")
        combined = f"{request.bug_description}\n{request.stack_trace or ''}"
        frames = await asyncio.to_thread(self._analyzer.extract_frames, combined, index)
        keywords = self._analyzer.extract_keywords(combined)
        candidates = await asyncio.to_thread(self._analyzer.rank_files, index, keywords, frames, 20)
        progress.emit(
            "retrieve", "completed",
            f"Found {len(candidates)} candidate files ({len(frames)} stack-trace frames matched the repo)",
            {"candidates": len(candidates), "frames": len(frames), "top": candidates[0].path if candidates else None},
        )

        # ---- 4. plan ----------------------------------------------------------------------------------
        progress.emit("plan", "started", "Building an investigation plan")
        plan = await self._llm.complete_json(
            templates.SYSTEM,
            templates.plan_prompt(
                bug=request.bug_description,
                trace=request.stack_trace,
                overview=self._overview(info, profile),
                candidates=self._candidate_table(candidates),
            ),
            PlanResponse,
            max_tokens=PLAN_MAX_TOKENS,
        )
        extra_terms = [t for t in plan.search_terms if isinstance(t, str)][:10]
        if extra_terms:
            more = await asyncio.to_thread(
                self._analyzer.rank_files, index, self._analyzer.extract_keywords(combined, extra_terms), frames, 20
            )
            candidates = self._merge_candidates(candidates, more)
        inspect = self._choose_files(plan.files_to_inspect, candidates, index, limit=6)
        progress.emit(
            "plan", "completed",
            f"{len(plan.hypotheses)} initial hypotheses; will inspect {len(inspect)} files",
            {"hypotheses": len(plan.hypotheses), "files": ", ".join(inspect)},
        )
        if not inspect:
            self._finish_without_patch(
                progress, info, "insufficient_evidence", plan.understanding or "No relevant code could be located.",
                [], [], candidates, ["No source file in the repository matched the bug report."],
            )
            return

        # ---- 5. web research --------------------------------------------------------------------------
        languages = self._investigated_languages(index, candidates, profile)
        research = await self._run_research(request, profile, languages, plan.research_queries, progress)

        # ---- 6. diagnose ------------------------------------------------------------------------------
        focus = {c.path: list(c.match_lines) for c in candidates}
        for fr in frames:
            focus.setdefault(fr.path, []).append(fr.line)
        hypotheses_text = "\n".join(f"- {h.title}: {h.reasoning}" for h in plan.hypotheses) or "(none)"
        progress.emit("diagnose", "started", "Reading the relevant files and comparing hypotheses")
        loaded = list(inspect)
        diagnosis = await self._diagnose(request, plan, hypotheses_text, index, loaded, focus, research, extra_round=False)
        extra_paths = self._choose_files(diagnosis.needs_more_context, [], index, limit=3, exclude=set(loaded))
        if extra_paths:
            progress.emit("diagnose", "info", f"The analysis asked for more context; reading {len(extra_paths)} more files")
            loaded += extra_paths
            diagnosis = await self._diagnose(request, plan, hypotheses_text, index, loaded, focus, research, extra_round=True)
        self._apply_research_notes(research, diagnosis)

        evidence = self._verify_evidence(index, diagnosis.evidence)
        verified = [e for e in evidence if e.verified]
        hypotheses = self._build_hypotheses(diagnosis)
        confidence = diagnosis.confidence
        if evidence and len(verified) * 2 < len(evidence):
            confidence = "low"
        progress.emit(
            "diagnose", "completed",
            f"Root cause identified ({confidence} confidence); {len(verified)}/{len(evidence)} evidence quotes verified in the code",
            {"confidence": confidence, "verified_evidence": len(verified), "total_evidence": len(evidence)},
        )
        if not verified:
            self._finish_without_patch(
                progress, info, "insufficient_evidence", diagnosis.root_cause, hypotheses, evidence, candidates,
                ["None of the code quotes cited by the AI could be found in the repository, so no patch was generated."],
                confidence="low", risks=diagnosis.risks, research=research,
            )
            return

        evidence_files = {e.file for e in verified}
        targets = [
            p for p in self._choose_files(diagnosis.files_to_modify, [], index, limit=self._s.max_patch_files)
            if not protected_reason(p)
        ]
        if not any(p in evidence_files for p in targets):
            targets = [p for p in sorted(evidence_files) if not protected_reason(p)][: self._s.max_patch_files]
        if not targets:
            self._finish_without_patch(
                progress, info, "no_valid_patch", diagnosis.root_cause, hypotheses, evidence, candidates,
                ["The faulty code is in files that a repair is not allowed to modify (tests, configuration or lock files)."],
                confidence=confidence, risks=diagnosis.risks, research=research,
            )
            return

        # ---- 6/7. patch + validate (bounded retry loop) -----------------------------------------------
        outcome = await self._patch_and_validate(
            request, workspace, progress, index, profile, diagnosis, evidence, verified, targets, focus, research
        )
        result = self._assemble(
            outcome, diagnosis, hypotheses, evidence, confidence, candidates, profile, research
        )
        progress.set_result(result)
        usage = f"{self._llm.calls} LLM calls, {self._llm.prompt_tokens + self._llm.completion_tokens} tokens"
        progress.emit(
            "finalize", "completed",
            f"Investigation complete: {result.outcome.replace('_', ' ')}; validation {result.validation.status.value} ({usage})",
            {"outcome": result.outcome, "validation": result.validation.status.value, "llm_calls": self._llm.calls},
        )

    # ======================================================================================================
    # diagnosis helpers
    @staticmethod
    def _investigated_languages(index: RepoIndex, candidates: list[RankedFile], profile: RepoProfile) -> list[str]:
        """Languages of the files most likely involved; in a multi-project repository this is not the primary language."""
        known = index.by_path()
        langs = list(dict.fromkeys(known[c.path].language for c in candidates[:4] if c.path in known and known[c.path].language))
        return langs or ([profile.primary_language] if profile.primary_language else [])

    async def _run_research(
        self, request: RepairRequest, profile: RepoProfile, languages: list[str], proposed: list[str], progress: Progress
    ) -> ResearchReport:
        """Search the web for documentation and known issues. Never fails the investigation."""
        limit = self._s.research_max_queries
        stack = relevant_frameworks(languages, profile.frameworks)
        queries = sanitize_queries(
            [*proposed, *fallback_queries(request.bug_description, request.stack_trace, languages[0] if languages else None, stack)],
            limit,
        )
        if not self._research.configured:
            note = "Web research is not configured on this server (no Tavily API key), so it was skipped."
            progress.emit("research", "info", note)
            return ResearchReport(status="skipped", note=note)
        if not queries:
            note = "No usable search query could be derived from the bug report."
            progress.emit("research", "info", f"Web research skipped: {note}")
            return ResearchReport(status="skipped", note=note)

        progress.emit("research", "started", f"Searching the web with Tavily ({len(queries)} {'query' if len(queries) == 1 else 'queries'})")
        outcome = await self._research.search(queries, official_domains(languages, profile.frameworks))
        for query, count in outcome.per_query.items():
            progress.emit("research", "info", f"“{query}” returned {count} {'result' if count == 1 else 'results'}", {"results": count})
        if outcome.status != "completed":
            progress.emit("research", "failed", f"Web research unavailable: {outcome.note} Continuing with repository evidence only.")
            return ResearchReport(status="unavailable", queries=outcome.queries, note=outcome.note)
        official = sum(1 for src in outcome.sources if src.kind == "official")
        progress.emit(
            "research", "completed",
            f"Found {len(outcome.sources)} sources ({official} official documentation)",
            {"sources": len(outcome.sources), "official": official},
        )
        return ResearchReport(status="completed", queries=outcome.queries, sources=outcome.sources)

    @staticmethod
    def _research_for_prompt(report: ResearchReport | None, *, used_only: bool = False, limit: int = 6) -> list[dict[str, str]]:
        if report is None or report.status != "completed":
            return []
        picked = [s for s in report.sources if s.used or not used_only][:limit]
        return [
            {"id": s.id, "kind": s.kind, "title": s.title, "domain": s.domain, "snippet": s.snippet[:220]} for s in picked
        ]

    @staticmethod
    def _apply_research_notes(report: ResearchReport, diagnosis: DiagnosisResponse) -> None:
        """Attach the model's comparison to the sources it cited. Notes citing unknown sources are discarded."""
        if report.status != "completed":
            return
        by_id = {s.id: s for s in report.sources}
        for note in diagnosis.research_notes:
            source = by_id.get(note.source_id.strip().upper())
            relevance = clean_text(note.relevance, 600)
            if source and relevance:
                source.used, source.relevance = True, relevance
        if any(s.used for s in report.sources):
            report.summary = clean_text(diagnosis.research_summary, 1500)
        else:
            report.note = "The diagnosis did not rely on any of the sources that were found."

    async def _diagnose(
        self, request: RepairRequest, plan: PlanResponse, hypotheses_text: str, index: RepoIndex,
        paths: list[str], focus: dict[str, list[int]], research: ResearchReport, *, extra_round: bool,
    ) -> DiagnosisResponse:
        blocks = self._file_blocks(index, paths, focus, self._s.max_context_chars)
        return await self._llm.complete_json(
            templates.SYSTEM,
            templates.diagnose_prompt(
                bug=request.bug_description, trace=request.stack_trace, understanding=plan.understanding,
                hypotheses=hypotheses_text, file_blocks=blocks, extra_round=extra_round,
                research=templates.research_block(self._research_for_prompt(research)),
            ),
            DiagnosisResponse,
            max_tokens=DIAGNOSE_MAX_TOKENS,
        )

    def _file_blocks(self, index: RepoIndex, paths: list[str], focus: dict[str, list[int]], budget: int) -> str:
        """Numbered source for each file, sharing a total character budget. Large files are windowed."""
        if not paths:
            return ""
        per_file = max(3000, budget // len(paths))
        blocks = []
        for path in paths:
            try:
                text = index.read_text(path)
            except Exception:  # noqa: BLE001, S112 - unreadable file simply isn't shown
                continue
            outline = self._analyzer.outline(path, text)
            body = self._analyzer.render_context(path, text, focus.get(path, []), per_file)
            header = f"File: {path} ({len(text.splitlines())} lines)" + (f"\nOutline:\n{outline}" if outline and len(text) > per_file else "")
            blocks.append(templates.fence_file(path, f"{header}\n{body}"))
        return "\n\n".join(blocks)

    def _verify_evidence(self, index: RepoIndex, items: list[EvidenceIn]) -> list[Evidence]:
        """Check each quote against the real file; correct line numbers when the quote is found elsewhere."""
        out: list[Evidence] = []
        known = index.by_path()
        for item in items:
            try:
                path = normalize_repo_path(item.file)
            except Exception:  # noqa: BLE001, S112 - unusable model-suggested path is skipped
                continue
            if path not in known:
                out.append(Evidence(file=path, start_line=item.start_line, end_line=item.end_line, snippet="",
                                    explanation=item.explanation, verified=False))
                continue
            text = index.read_text(path)
            lines = text.splitlines()
            quote = "\n".join(re.sub(r"^\s*\d+\|\s?", "", ln) for ln in item.quote.splitlines())
            start, end = item.start_line, max(item.start_line, item.end_line)
            found = locate_quote(lines, quote, item.start_line) if len(_norm(quote)) >= MIN_QUOTE_CHARS else None
            verified = found is not None
            if found:
                # Report where the quote REALLY is, not where the model said it was.
                start, end = found
            start = min(max(1, start), max(1, len(lines)))
            end = min(max(start, end), max(1, len(lines)))
            out.append(Evidence(
                file=path, start_line=start, end_line=end, snippet=self._analyzer.slice_lines(text, start, end)[:2000],
                explanation=item.explanation, verified=verified,
            ))
        return out

    @staticmethod
    def _build_hypotheses(diagnosis: DiagnosisResponse) -> list[Hypothesis]:
        selected = _norm(diagnosis.selected_hypothesis).lower()
        out = [
            Hypothesis(
                title=h.title, explanation=h.explanation, likelihood=h.likelihood,
                evidence_for=h.evidence_for, evidence_against=h.evidence_against,
                selected=bool(selected) and _norm(h.title).lower() == selected,
            )
            for h in diagnosis.hypotheses
        ]
        if out and not any(h.selected for h in out):
            out[0].selected = True
        return out

    # ======================================================================================================
    # patch + validate
    async def _patch_and_validate(
        self, request: RepairRequest, workspace: Workspace, progress: Progress, index: RepoIndex,
        profile: RepoProfile, diagnosis: DiagnosisResponse, evidence: list[Evidence], verified: list[Evidence],
        targets: list[str], focus: dict[str, list[int]], research: ResearchReport,
    ) -> dict:
        s = self._s
        python = profile.primary_language == "Python"
        can_run, why_not = await self._validator.availability(
            language_supported=python, has_tests=profile.has_tests, frameworks=profile.test_frameworks,
        )
        if not python and profile.primary_language:
            known = index.by_path()
            langs = Counter(known[e.file].language for e in verified if e.file in known and known[e.file].language)
            language = langs.most_common(1)[0][0] if langs else profile.primary_language
            commands = self._commands_near(profile.test_commands, [e.file for e in verified])
            detected = f" Detected test command: {commands[0]}." if commands else ""
            can_run, why_not = False, f"RepoPilot executes Python tests only, so the {language} tests were not run.{detected}"
        research_text = templates.research_block(self._research_for_prompt(research, used_only=True, limit=3))
        patch_paths = list(dict.fromkeys(targets + [e.file for e in verified if not protected_reason(e.file)]))[:6]
        patch_focus = {**focus}
        for e in verified:
            patch_focus.setdefault(e.file, []).append(e.start_line)
        file_blocks = self._file_blocks(index, patch_paths, patch_focus, s.max_context_chars)
        evidence_text = "\n".join(f"- {e.file}:{e.start_line}-{e.end_line}: {e.explanation}" for e in verified)

        attempts: list[Attempt] = []
        feedback = ""
        final: dict | None = None
        baseline_cache: dict[str, vs.TestRun] = {}

        for iteration in range(1, s.max_repair_iterations + 1):
            progress.emit("patch", "started", f"Generating patch (attempt {iteration} of {s.max_repair_iterations})")
            try:
                response = await self._llm.complete_json(
                    templates.SYSTEM,
                    templates.patch_prompt(
                        bug=request.bug_description, root_cause=diagnosis.root_cause, evidence=evidence_text,
                        file_blocks=file_blocks, feedback=feedback, want_regression_test=python,
                        language=profile.primary_language or "", research=research_text,
                    ),
                    PatchResponse,
                    max_tokens=PATCH_MAX_TOKENS,
                )
            except (LLMUnavailable, LLMOutputError) as exc:
                # The diagnosis is already real and verified; keep it and say plainly that patching failed.
                attempts.append(Attempt(iteration=iteration, outcome="llm_error", detail=exc.message))
                progress.emit("patch", "failed", exc.message)
                break
            if not response.edits:
                reason = response.cannot_fix_reason or "The AI did not propose any edits."
                attempts.append(Attempt(iteration=iteration, outcome="no_patch", detail=reason))
                progress.emit("patch", "failed", f"No patch produced: {reason}")
                break

            build: PatchBuild = await asyncio.to_thread(self._patches.build_patch, response.edits, index)
            if not build.ok:
                detail = "; ".join(build.problems[:4])
                attempts.append(Attempt(iteration=iteration, outcome="patch_invalid", detail=detail))
                progress.emit("patch", "failed", f"Patch rejected by validation: {detail}")
                feedback = f"Your edits were rejected by the patch validator: {detail}"
                continue

            regression, reg_problem = (None, None)
            if python:
                regression, reg_problem = self._patches.prepare_regression_test(response.regression_test, index)
            adds = sum(c.additions for c in build.changes)
            dels = sum(c.deletions for c in build.changes)
            progress.emit(
                "patch", "completed",
                f"Patch validated: {len(build.changes)} file(s), +{adds} −{dels}"
                + (f"; regression test rejected ({reg_problem})" if reg_problem else ""),
                {"files": len(build.changes), "additions": adds, "deletions": dels},
            )

            if not can_run:
                progress.emit("validate", "info", f"Validation unavailable: {why_not}")
                validation = vs.unavailable(why_not)
                attempts.append(Attempt(iteration=iteration, outcome="patch_proposed", detail="Not validated."))
                final = {"build": build, "regression": regression, "validation": validation,
                         "risks": response.risks, "reg_problem": reg_problem}
                break

            validation = await self._validate(workspace, progress, index, build, regression, baseline_cache)
            attempts.append(Attempt(iteration=iteration, outcome=f"validation_{validation.status.value}", detail=validation.summary))
            final = {"build": build, "regression": regression, "validation": validation,
                     "risks": response.risks, "reg_problem": reg_problem}
            if validation.status == ValidationStatus.FAILED and iteration < s.max_repair_iterations:
                patched_run = next((r for r in validation.runs if r.label == "patched"), None)
                tail = (patched_run.output[-3500:] if patched_run else "")
                feedback = f"The patch was applied and the tests were run. {validation.summary}\nTest output (tail):\n{tail}"
                progress.emit("validate", "info", "Tests failed; asking the AI to revise the patch")
                continue
            break

        return {"final": final, "attempts": attempts, "validation_note": why_not if not can_run else ""}

    async def _validate(
        self, workspace: Workspace, progress: Progress, index: RepoIndex, build: PatchBuild,
        regression, baseline_cache: dict[str, vs.TestRun],
    ) -> Validation:
        progress.emit("validate", "started", "Running tests in the isolated sandbox (no network, resource-limited)")
        key = hashlib.sha256((regression.content if regression else "").encode()).hexdigest()
        try:
            make_readable_for_sandbox(workspace.repo_dir)
            if key not in baseline_cache:
                baseline_dir = workspace.repo_dir
                if regression:
                    baseline_dir = self._fresh_copy(workspace, "baseline")
                    ValidationService.write_regression_test(baseline_dir, regression.path, regression.content)
                    make_readable_for_sandbox(baseline_dir)
                progress.emit("validate", "info", "Running baseline tests before the patch")
                baseline_cache[key] = await self._validator.run_baseline(baseline_dir)
            baseline = baseline_cache[key]

            patched_dir = self._fresh_copy(workspace, "patched")
            self._patches.apply_to_directory(build.diff, index, patched_dir)
            if regression:
                ValidationService.write_regression_test(patched_dir, regression.path, regression.content)
            make_readable_for_sandbox(patched_dir)
            progress.emit("validate", "info", "Running tests with the patch applied")
            patched = await self._validator.run_patched(patched_dir)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 - sandbox failure must degrade to an honest status
            logger.exception("sandbox execution failed")
            validation = Validation(
                status=ValidationStatus.INCONCLUSIVE, reason="sandbox_error",
                summary=f"Inconclusive: the sandbox failed to run the tests ({type(exc).__name__}).",
            )
            progress.emit("validate", "failed", validation.summary)
            return validation

        validation = vs.classify(baseline, patched)
        if regression:
            regression.executed = True
        progress.emit(
            "validate", "completed" if validation.status != ValidationStatus.INCONCLUSIVE else "failed",
            validation.summary, {"status": validation.status.value},
        )
        return validation

    @staticmethod
    def _fresh_copy(workspace: Workspace, name: str):
        existing = workspace.path / name
        if existing.exists():
            shutil.rmtree(existing, ignore_errors=True)
        return workspace.copy_repo(name)

    # ======================================================================================================
    # result assembly
    def _assemble(
        self, outcome: dict, diagnosis: DiagnosisResponse, hypotheses: list[Hypothesis], evidence: list[Evidence],
        confidence: str, candidates: list[RankedFile], profile: RepoProfile, research: ResearchReport,
    ) -> RepairResult:
        final = outcome["final"]
        attempts: list[Attempt] = outcome["attempts"]
        limitations = ["This patch was generated by an AI model. Review it carefully before merging."]
        relevant = self._relevant_files(candidates, evidence)

        if final is None:
            detail = attempts[-1].detail if attempts else "No patch could be produced."
            limitations.append(f"No valid patch was produced: {detail}")
            return RepairResult(
                outcome="no_valid_patch", root_cause=diagnosis.root_cause, confidence=confidence,  # type: ignore[arg-type]
                hypotheses=hypotheses, evidence=evidence, relevant_files=relevant,
                validation=Validation(summary="Validation was not run because there is no valid patch.",
                                      detected_commands=profile.test_commands),
                risks=diagnosis.risks, limitations=limitations, attempts=attempts, research=research,
                llm_model=self._s.llm_model,
            )

        build: PatchBuild = final["build"]
        validation: Validation = final["validation"]
        validation.detected_commands = self._commands_near(
            profile.test_commands, [c.path for c in build.changes] or [e.file for e in evidence]
        )
        regression = final["regression"]
        if validation.status == ValidationStatus.NOT_RUN:
            limitations.append("The patch has NOT been tested.")
        elif validation.status == ValidationStatus.INCONCLUSIVE:
            limitations.append("Test results were inconclusive, so the fix is not confirmed.")
        elif validation.status == ValidationStatus.FAILED:
            limitations.append("Tests still fail with this patch; treat it as a starting point only.")
        elif validation.bug_reproduced is not True:
            limitations.append("No test reproduced the reported bug before the patch, so passing tests do not prove it is fixed.")
        if validation.status != ValidationStatus.NOT_RUN:
            limitations.append("Tests ran offline with only pytest and the standard library available; project dependencies were not installed.")
        if final.get("reg_problem"):
            limitations.append(f"A proposed regression test was discarded: {final['reg_problem']}.")
        if regression and not regression.executed:
            limitations.append("The suggested regression test was not executed.")
        if profile.primary_language != "Python":
            limitations.append("Automated test validation is available for Python repositories only.")

        risks = list(dict.fromkeys([*diagnosis.risks, *final["risks"]]))[:8]
        return RepairResult(
            outcome="patch_proposed", root_cause=diagnosis.root_cause, confidence=confidence,  # type: ignore[arg-type]
            hypotheses=hypotheses, evidence=evidence, relevant_files=relevant, changes=build.changes, diff=build.diff,
            regression_test=regression, validation=validation, risks=risks, limitations=limitations,
            attempts=attempts, research=research, llm_model=self._s.llm_model,
        )

    def _finish_without_patch(
        self, progress: Progress, info: RepositoryInfo, outcome: str, root_cause: str,
        hypotheses: list[Hypothesis], evidence: list[Evidence], candidates: list[RankedFile],
        limitations: list[str], *, confidence: str = "low", risks: list[str] | None = None,
        research: ResearchReport | None = None,
    ) -> None:
        result = RepairResult(
            outcome=outcome,  # type: ignore[arg-type]
            root_cause=root_cause, confidence=confidence,  # type: ignore[arg-type]
            hypotheses=hypotheses, evidence=evidence, relevant_files=self._relevant_files(candidates, evidence),
            validation=Validation(summary="Validation was not run because no patch was generated.",
                                  detected_commands=info.test_commands),
            risks=risks or [], limitations=limitations, research=research, llm_model=self._s.llm_model,
        )
        progress.set_result(result)
        progress.emit("finalize", "completed", f"Investigation finished without a patch: {outcome.replace('_', ' ')}")

    # ======================================================================================================
    # small utilities
    @staticmethod
    def _project_label(profile: RepoProfile) -> str:
        """\"Python project\", or \"Multi-language project\" when the top languages are tied (a repository of several projects)."""
        counts = sorted(profile.languages.values(), reverse=True)
        if len(counts) > 1 and counts[0] == counts[1]:
            return f"Multi-language project ({', '.join(list(profile.languages)[:4])})"
        return f"{profile.primary_language} project"

    @staticmethod
    def _commands_near(commands: list[str], paths: list[str]) -> list[str]:
        """In a repository with several projects, put the test command of the project that was changed first."""
        def near(command: str) -> bool:
            match = re.match(r"cd (\S+) && ", command)
            return bool(match) and any(p.startswith(match.group(1) + "/") for p in paths)

        return sorted(commands, key=lambda c: not near(c))

    @staticmethod
    def _overview(info: RepositoryInfo, profile: RepoProfile) -> str:
        return (
            f"Repository: {info.owner}/{info.name}\nDescription: {info.description or '(none)'}\n"
            f"Primary language: {profile.primary_language}\nManifests: {', '.join(profile.manifests[:10]) or '(none)'}\n"
            f"Frameworks and platforms: {', '.join(profile.frameworks[:10]) or '(none detected)'}\n"
            f"Notable dependencies: {', '.join(profile.dependencies[:12]) or '(none detected)'}\n"
            f"Test frameworks: {', '.join(profile.test_frameworks) or '(none detected)'}\n"
            f"Structure:\n{profile.tree_summary}"
        )

    @staticmethod
    def _candidate_table(candidates: list[RankedFile]) -> str:
        return "\n".join(
            f"{c.path} | score {c.score} | {'; '.join(c.reasons)} | lines {c.match_lines[:6]}" for c in candidates[:20]
        )

    @staticmethod
    def _merge_candidates(a: list[RankedFile], b: list[RankedFile]) -> list[RankedFile]:
        merged: dict[str, RankedFile] = {c.path: c for c in a}
        for c in b:
            if c.path not in merged or c.score > merged[c.path].score:
                merged[c.path] = c
        return sorted(merged.values(), key=lambda c: c.score, reverse=True)[:20]

    @staticmethod
    def _choose_files(
        wanted: list[str], candidates: list[RankedFile], index: RepoIndex, *, limit: int,
        exclude: set[str] | None = None,
    ) -> list[str]:
        """Model-suggested paths that really exist, topped up with the best-ranked candidates."""
        known = index.by_path()
        chosen: list[str] = []
        for raw in wanted:
            try:
                path = normalize_repo_path(raw)
            except Exception:  # noqa: BLE001, S112 - unusable model-suggested path is skipped
                continue
            if path in known and path not in chosen and path not in (exclude or set()):
                chosen.append(path)
        for c in candidates:
            if len(chosen) >= limit:
                break
            if c.path not in chosen and c.path not in (exclude or set()):
                chosen.append(c.path)
        return chosen[:limit]

    @staticmethod
    def _relevant_files(candidates: list[RankedFile], evidence: list[Evidence]) -> list[RelevantFile]:
        out: dict[str, RelevantFile] = {}
        for e in evidence:
            if e.verified:
                rf = out.setdefault(e.file, RelevantFile(path=e.file, reason="Contains verified evidence for the root cause", lines=[]))
                rf.lines += list(range(e.start_line, min(e.end_line, e.start_line + 5) + 1))
        for c in candidates[:8]:
            out.setdefault(c.path, RelevantFile(path=c.path, reason="; ".join(c.reasons) or "Matched the bug report", lines=c.match_lines[:8]))
        for rf in out.values():
            rf.lines = sorted(set(rf.lines))[:12]
        return list(out.values())[:12]
