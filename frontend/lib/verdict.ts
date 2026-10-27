import type { InvestigationStatus, RepairResult } from "@/types/api";

export type Tone = "success" | "warning" | "danger" | "neutral" | "info";

export interface Verdict {
  tone: Tone;
  headline: string;
  detail: string;
}

/**
 * The single place that decides what the UI is allowed to claim. A "verified" claim requires a real passing
 * validation run; everything else is described as a proposal.
 */
export function verdictFor(result: RepairResult): Verdict {
  const v = result.validation;
  if (result.outcome === "insufficient_evidence") {
    return {
      tone: "warning",
      headline: "Not enough evidence to propose a patch",
      detail: "The AI's claims about the code could not be verified in the repository, so no patch was generated.",
    };
  }
  if (result.outcome === "no_valid_patch") {
    return {
      tone: "danger",
      headline: "No valid patch could be produced",
      detail: "The root cause analysis is shown below, but every patch attempt was rejected or could not be generated.",
    };
  }
  switch (v.status) {
    case "passed":
      if (v.scope === "targeted") {
        return {
          tone: "success",
          headline: "Targeted fix verified by tests",
          detail: `Previously failing tests now pass and nothing regressed. ${v.pre_existing_failures} unrelated failure(s) that already existed remain.`,
        };
      }
      if (v.bug_reproduced === true) {
        return { tone: "success", headline: "Patch verified by tests", detail: "Tests failed before the patch and pass after it." };
      }
      return {
        tone: "warning",
        headline: "Patch proposed; tests pass but did not reproduce the bug",
        detail: "The suite passes, but it also passed before the patch, so this does not prove the bug is fixed.",
      };
    case "failed":
      return { tone: "danger", headline: "Patch proposed, but tests fail", detail: "Treat this patch as a starting point only." };
    case "inconclusive":
      return { tone: "warning", headline: "Patch proposed; test results inconclusive", detail: "The fix could not be confirmed." };
    default:
      return {
        tone: "neutral",
        headline: "Patch proposed — not tested",
        detail: "Validation unavailable for this run. The patch is a proposal that has not been executed.",
      };
  }
}

export function statusLabel(status: InvestigationStatus): string {
  return { queued: "Queued", running: "Running", completed: "Completed", failed: "Failed" }[status];
}
