import type { Investigation, InvestigationEvent, RepairResult, RepositoryInfo, Validation } from "@/types/api";

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
