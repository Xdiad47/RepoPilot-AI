/** Mirrors backend/app/schemas/models.py. Keep in sync when the API changes. */

export type ValidationStatus = "passed" | "failed" | "not_run" | "inconclusive";
export type InvestigationStatus = "queued" | "running" | "completed" | "failed";
export type Stage =
  | "queued"
  | "clone"
  | "analyze"
  | "retrieve"
  | "plan"
  | "diagnose"
  | "patch"
  | "validate"
  | "finalize";
export type EventStatus = "started" | "completed" | "failed" | "info";
export type Level = "high" | "medium" | "low";

export interface RepairRequest {
  repository_url: string;
  bug_description: string;
  stack_trace?: string | null;
}

export interface RepairAccepted {
  repair_id: string;
  status: InvestigationStatus;
  status_url: string;
  events_url: string;
}

export interface RepositoryInfo {
  url: string;
  owner: string;
  name: string;
  description: string | null;
  default_branch: string | null;
  commit_sha: string | null;
  stars: number | null;
  size_kb: number | null;
  primary_language: string | null;
  languages: Record<string, number>;
  source_file_count: number;
  manifests: string[];
  test_frameworks: string[];
  tree_summary: string;
  supported: boolean;
  support_note: string;
}

export interface Evidence {
  file: string;
  start_line: number;
  end_line: number;
  snippet: string;
  explanation: string;
  verified: boolean;
}

export interface Hypothesis {
  title: string;
  explanation: string;
  likelihood: Level;
  selected: boolean;
  evidence_for: string[];
  evidence_against: string[];
}

export interface RelevantFile {
  path: string;
  reason: string;
  lines: number[];
}

export interface FileChange {
  path: string;
  explanation: string;
  additions: number;
  deletions: number;
  original_content: string | null;
  patched_content: string | null;
}

export interface RegressionTest {
  path: string;
  description: string;
  content: string;
  executed: boolean;
}

export interface TestRun {
  label: "baseline" | "patched";
  command: string[];
  exit_code: number | null;
  timed_out: boolean;
  duration_seconds: number;
  output: string;
  output_truncated: boolean;
  passed: number;
  failed: number;
  errors: number;
  failed_tests: string[];
}

export interface Validation {
  status: ValidationStatus;
  summary: string;
  reason: string | null;
  bug_reproduced: boolean | null;
  scope: "full_suite" | "targeted" | null;
  fixed_tests: string[];
  pre_existing_failures: number;
  runs: TestRun[];
}

export interface Attempt {
  iteration: number;
  outcome: string;
  detail: string;
}

export type Outcome = "patch_proposed" | "insufficient_evidence" | "no_valid_patch";

export interface RepairResult {
  outcome: Outcome;
  root_cause: string;
  confidence: Level;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  relevant_files: RelevantFile[];
  changes: FileChange[];
  diff: string;
  regression_test: RegressionTest | null;
  validation: Validation;
  risks: string[];
  limitations: string[];
  attempts: Attempt[];
  llm_model: string;
}

export interface InvestigationEvent {
  seq: number;
  timestamp: string;
  stage: Stage;
  status: EventStatus;
  message: string;
  detail: Record<string, string | number | boolean | null> | null;
}

export interface ErrorInfo {
  code: string;
  message: string;
  stage: Stage | null;
}

export interface Investigation {
  id: string;
  status: InvestigationStatus;
  created_at: string;
  updated_at: string;
  repository_url: string;
  bug_description: string;
  stack_trace: string | null;
  repository: RepositoryInfo | null;
  result: RepairResult | null;
  error: ErrorInfo | null;
  events: InvestigationEvent[];
}

export interface Health {
  status: string;
  version: string;
  environment: string;
  llm: { configured: boolean; model: string | null; provider_host: string | null };
  sandbox: { enabled: boolean; available: boolean; detail: string };
  github_token_configured: boolean;
  limits: Record<string, number>;
}
