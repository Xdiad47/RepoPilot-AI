import type { Investigation, InvestigationEvent, RepairResult, RepositoryInfo, ResearchReport, Validation } from "@/types/api";

export const ID = "a".repeat(32);

export const repo: RepositoryInfo = {
  url: "https://github.com/octocat/hello",
  owner: "octocat",
  name: "hello",
  description: "A demo repo",
  default_branch: "main",
  commit_sha: "0123456789abcdef0123456789abcdef01234567",
  stars: 42,
  size_kb: 120,
  primary_language: "Python",
  languages: { Python: 5 },
  source_file_count: 5,
  manifests: ["requirements.txt"],
  test_frameworks: ["pytest"],
  frameworks: ["FastAPI"],
  dependencies: ["fastapi", "pydantic"],
  test_commands: ["pytest"],
  validation_supported: true,
  structure: [
    { path: "(root)", files: 2, languages: [], role: "other" },
    { path: "app", files: 3, languages: ["Python"], role: "source" },
    { path: "tests", files: 2, languages: ["Python"], role: "tests" },
  ],
  entry_points: ["app/main.py"],
  quality: [
    { severity: "warning", title: "Bare except", detail: "`except:` hides real errors.", path: "app/api.py", line: 9 },
    { severity: "info", title: "No README", detail: "The repository root has no README.", path: null, line: null },
  ],
  tree_summary: "",
  supported: true,
  support_note: "Python is fully supported.",
};

export const DIFF = `--- a/app/api.py
+++ b/app/api.py
@@ -3,5 +3,5 @@
 
 def register(payload):
     email = payload["email"]
-    domain = email.split("@")[1]
+    domain = email.split("@")[1] if "@" in email else ""
     return {"domain": domain}
`;

export const notRun: Validation = {
  status: "not_run",
  summary: "Validation unavailable. Sandbox is disabled. The patch is a proposal only: it has not been tested.",
  reason: "validation_unavailable",
  bug_reproduced: null,
  scope: null,
  fixed_tests: [],
  pre_existing_failures: 0,
  detected_commands: ["pytest"],
  runs: [],
};

export const passed: Validation = {
  status: "passed",
  summary: "Passed. The tests failed before the patch (1 failing) and all 2 pass after it.",
  reason: null,
  bug_reproduced: true,
  scope: "full_suite",
  fixed_tests: ["tests/test_a.py::test_x"],
  pre_existing_failures: 0,
  detected_commands: ["pytest"],
  runs: [
    { label: "baseline", command: ["python", "-m", "pytest"], exit_code: 1, timed_out: false, duration_seconds: 0.7, output: "1 failed, 1 passed in 0.1s", output_truncated: false, passed: 1, failed: 1, errors: 0, failed_tests: ["tests/test_a.py::test_x"] },
    { label: "patched", command: ["python", "-m", "pytest"], exit_code: 0, timed_out: false, duration_seconds: 0.5, output: "2 passed in 0.1s", output_truncated: false, passed: 2, failed: 0, errors: 0, failed_tests: [] },
  ],
};

export function result(overrides: Partial<RepairResult> = {}): RepairResult {
  return {
    outcome: "patch_proposed",
    root_cause: "register() indexes email.split('@')[1] without checking for '@'.",
    confidence: "high",
    hypotheses: [
      { title: "Unchecked split", explanation: "IndexError on empty input", likelihood: "high", selected: true, evidence_for: ["split()[1] on empty string"], evidence_against: [] },
      { title: "Bad normalization", explanation: "normalize is fine", likelihood: "low", selected: false, evidence_for: [], evidence_against: ["only strips"] },
    ],
    evidence: [
      { file: "app/api.py", start_line: 6, end_line: 6, snippet: '    domain = email.split("@")[1]', explanation: "crashes here", verified: true },
      { file: "app/ghost.py", start_line: 1, end_line: 1, snippet: "", explanation: "invented", verified: false },
    ],
    relevant_files: [{ path: "app/api.py", reason: "stack trace", lines: [5, 6] }],
    changes: [
      {
        path: "app/api.py",
        explanation: "Guard the split.",
        additions: 1,
        deletions: 1,
        original_content: 'def register(payload):\n    email = payload["email"]\n    domain = email.split("@")[1]\n',
        patched_content: 'def register(payload):\n    email = payload["email"]\n    domain = email.split("@")[1] if "@" in email else ""\n',
      },
    ],
    diff: DIFF,
    regression_test: { path: "tests/test_repopilot_regression.py", description: "empty email", content: "def test_x():\n    assert True\n", executed: false },
    validation: notRun,
    risks: ["Behavior change for malformed emails"],
    limitations: ["The patch has NOT been tested."],
    attempts: [{ iteration: 1, outcome: "patch_proposed", detail: "Not validated." }],
    research: null,
    llm_model: "test-model",
    ...overrides,
  };
}

export function event(seq: number, stage: InvestigationEvent["stage"], status: InvestigationEvent["status"], message: string): InvestigationEvent {
  return { seq, timestamp: new Date(Date.UTC(2026, 9, 27, 10, 0, seq)).toISOString(), stage, status, message, detail: null };
}

export function investigation(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: ID,
    status: "completed",
    created_at: "2026-10-27T10:00:00Z",
    updated_at: "2026-10-27T10:00:09Z",
    repository_url: repo.url,
    bug_description: "register() returns a 500 error when the user submits an empty email address.",
    stack_trace: null,
    repository: repo,
    result: result(),
    error: null,
    events: [
      event(1, "queued", "info", "Investigation accepted"),
      event(2, "clone", "completed", "Cloned commit 01234567"),
      event(3, "analyze", "completed", "Python project"),
      event(4, "diagnose", "completed", "Root cause identified"),
      event(5, "patch", "completed", "Patch validated"),
      event(6, "validate", "info", "Validation unavailable: sandbox disabled"),
      event(7, "finalize", "completed", "Investigation complete"),
    ],
    ...overrides,
  };
}

export const TWO_FILE_DIFF = `--- a/app/api.py
+++ b/app/api.py
@@ -3,5 +3,5 @@
 
 def register(payload):
     email = payload["email"]
-    domain = email.split("@")[1]
+    domain = email.split("@")[1] if "@" in email else ""
     return {"domain": domain}
--- a/app/util.py
+++ b/app/util.py
@@ -1,3 +1,3 @@
 def clean(value):
-    return value.strip()
+    return (value or "").strip()
`;

export function twoFileResult(overrides: Partial<RepairResult> = {}): RepairResult {
  const base = result();
  return result({
    diff: TWO_FILE_DIFF,
    changes: [
      base.changes[0],
      { path: "app/util.py", explanation: "Handle None.", additions: 1, deletions: 1, original_content: null, patched_content: null },
    ],
    ...overrides,
  });
}

export const research: ResearchReport = {
  status: "completed",
  provider: "Tavily",
  queries: ["python IndexError split on empty string", "python str.split documentation"],
  summary: "The Python docs confirm that indexing past the end of a list raises IndexError, which matches the unguarded split.",
  note: "",
  sources: [
    { id: "R1", title: "Stack Overflow: split index error", url: "https://stackoverflow.com/q/1", domain: "stackoverflow.com", snippet: "You split on @ with no @.", kind: "community", query: "q", score: 0.9, used: false, relevance: "" },
    { id: "R2", title: "Built-in exceptions", url: "https://docs.python.org/3/library/exceptions.html", domain: "docs.python.org", snippet: "IndexError is raised when a sequence subscript is out of range.", kind: "official", query: "q", score: 0.6, used: true, relevance: "Confirms split()[1] raises IndexError when no '@' is present." },
    { id: "R3", title: "Sneaky link", url: "javascript:alert(1)", domain: "evil.test", snippet: "", kind: "other", query: "q", score: null, used: false, relevance: "" },
  ],
};

export const MULTI_HUNK_DIFF = `--- a/app/api.py
+++ b/app/api.py
@@ -2,3 +2,3 @@ def register(payload):
     email = payload["email"]
-    domain = email.split("@")[1]
+    domain = email.split("@")[1] if "@" in email else ""
     return {"domain": domain}
@@ -20,3 +20,3 @@ def other():
     x = 1
-    return x
+    return x + 1
     y = 2
`;

export function multiHunkResult(): RepairResult {
  const base = result();
  return result({ diff: MULTI_HUNK_DIFF, changes: [{ ...base.changes[0], additions: 2, deletions: 2 }] });
}
