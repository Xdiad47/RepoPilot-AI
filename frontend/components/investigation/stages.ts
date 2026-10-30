import type { Investigation, InvestigationEvent, Stage } from "@/types/api";

export const PIPELINE: { stage: Stage; label: string; description: string }[] = [
  { stage: "clone", label: "Clone", description: "Fetch the repository" },
  { stage: "analyze", label: "Analyze", description: "Language & tests" },
  { stage: "retrieve", label: "Search", description: "Find relevant code" },
  { stage: "plan", label: "Plan", description: "Form hypotheses" },
  { stage: "research", label: "Research", description: "Search the web for documentation" },
  { stage: "diagnose", label: "Diagnose", description: "Verify root cause" },
  { stage: "patch", label: "Patch", description: "Propose a fix" },
  { stage: "validate", label: "Validate", description: "Run tests" },
  { stage: "finalize", label: "Report", description: "Summarise" },
];

export type StageState = "pending" | "active" | "done" | "failed" | "skipped";

/** Derives each step's state strictly from events the backend actually emitted. */
export function stageStates(investigation: Investigation): Record<Stage, StageState> {
  const terminal = investigation.status === "completed" || investigation.status === "failed";
  const result = {} as Record<Stage, StageState>;
  const lastOverall = investigation.events.at(-1);

  for (const { stage } of PIPELINE) {
    const events = investigation.events.filter((e: InvestigationEvent) => e.stage === stage);
    const significant = events.filter((e) => e.status !== "info");
    const last = significant.at(-1);
    if (events.length === 0) {
      result[stage] = terminal ? "skipped" : "pending";
    } else if (!last) {
      // Only informational events (e.g. "Validation unavailable"): the step never actually ran.
      result[stage] = terminal ? "skipped" : "active";
    } else if (last.status === "failed") {
      result[stage] = "failed";
    } else if (last.status === "completed") {
      result[stage] = "done";
    } else {
      result[stage] = terminal ? "done" : lastOverall?.stage === stage || investigation.status === "running" ? "active" : "done";
    }
  }
  result.queued = investigation.status === "queued" ? "active" : "done";
  return result;
}

export function elapsedSeconds(from: string, to: string): number {
  return Math.max(0, (new Date(to).getTime() - new Date(from).getTime()) / 1000);
}
