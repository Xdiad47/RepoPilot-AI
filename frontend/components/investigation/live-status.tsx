import { Check, Circle, Loader2 } from "lucide-react";
import { Card, CardBody } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Investigation, Stage } from "@/types/api";
import { PIPELINE, stageStates, type StageState } from "./stages";

/** Plain-language wording for each real backend step, so a visitor always knows what is happening and why. */
export const FRIENDLY: Record<Stage, { title: string; text: string; short: string }> = {
  queued: { title: "Getting ready", text: "Your investigation is waiting for a free worker. It will start in a moment.", short: "Getting ready" },
  clone: { title: "Connecting to your repository", text: "Downloading a safe, read-only copy of the code. Your repository is never changed.", short: "Connect to the repository" },
  analyze: { title: "Analysing the repository", text: "Detecting the languages, frameworks and how this project is tested.", short: "Analyse the project" },
  retrieve: { title: "Looking for the code behind the bug", text: "Searching the files for anything related to your description.", short: "Find the relevant code" },
  plan: { title: "Planning the investigation", text: "Forming theories about what could be wrong and where to look.", short: "Plan the investigation" },
  research: { title: "Searching the internet", text: "Looking for official documentation and known issues about this kind of error.", short: "Search the internet" },
  diagnose: { title: "Debugging: finding the root cause", text: "Reading the code and checking every claim against the real file.", short: "Find the root cause" },
  patch: { title: "Writing a fix", text: "Drafting the smallest change that solves the problem, and checking that it applies cleanly.", short: "Write a fix" },
  validate: { title: "Checking the fix", text: "Running the project's tests when that is possible, otherwise saying clearly that it was not tested.", short: "Check the fix" },
  finalize: { title: "Preparing your report", text: "Putting the evidence, the fix and the next steps together.", short: "Prepare your report" },
};

function currentStage(investigation: Investigation, states: Record<Stage, StageState>): Stage {
  if (investigation.status === "queued") return "queued";
  const active = PIPELINE.find((p) => states[p.stage] === "active");
  if (active) return active.stage;
  // Between two steps: show the next one that has not run yet.
  return PIPELINE.find((p) => states[p.stage] === "pending")?.stage ?? "finalize";
}

/** What the backend has actually reported so far (never invented): the latest finished steps. */
function foundSoFar(investigation: Investigation): string[] {
  return investigation.events
    .filter((e) => e.status === "completed" && e.stage !== "queued")
    .slice(-3)
    .map((e) => e.message);
}

export function LiveStatus({ investigation }: { investigation: Investigation }) {
  const states = stageStates(investigation);
  const stage = currentStage(investigation, states);
  const info = FRIENDLY[stage];
  const found = foundSoFar(investigation);

  return (
    <Card className="border-accent/40">
      <CardBody className="space-y-5">
        <div role="status" aria-live="polite" className="flex items-start gap-3.5">
          <span className="relative mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent/15 text-accent">
            <span className="absolute inset-0 animate-ping rounded-full bg-accent/20 motion-reduce:hidden" aria-hidden />
            <Loader2 className="relative h-5 w-5 animate-spin" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-widest text-accent">Investigation in progress</p>
            <h2 className="mt-1 text-lg font-semibold leading-snug">{info.title}…</h2>
            <p className="mt-1 text-sm leading-6 text-muted">{info.text}</p>
          </div>
        </div>

        <ol className="space-y-2" aria-label="Steps">
          {PIPELINE.filter((p) => p.stage !== "validate" || states.validate !== "skipped").map(({ stage: s }) => (
            <li key={s} className={cn("flex items-center gap-2.5 text-sm", states[s] === "pending" && s !== stage && "text-faint")}>
              <StepIcon state={s === stage ? "active" : states[s]} />
              <span className={cn(s === stage && "font-medium text-fg")}>{FRIENDLY[s].short}</span>
              <span className="sr-only">{s === stage ? "(in progress)" : states[s] === "done" ? "(done)" : states[s] === "failed" ? "(could not finish)" : ""}</span>
            </li>
          ))}
        </ol>

        {found.length > 0 ? (
          <div className="rounded-lg border border-border bg-bg p-3">
            <p className="text-xs font-medium text-muted">Found so far</p>
            <ul className="mt-2 space-y-1.5">
              {found.map((message, i) => (
                <li key={`${i}-${message}`} className="flex gap-2 text-[13px] leading-5 text-fg/90">
                  <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
                  <span className="min-w-0 break-words">{message}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <p className="text-xs leading-5 text-faint">
          This usually takes 10 to 60 seconds. You can keep this page open: results appear here as each step finishes. Every line above
          comes from the server as it happens.
        </p>
      </CardBody>
    </Card>
  );
}

function StepIcon({ state }: { state: StageState }) {
  if (state === "done") return <Check className="h-4 w-4 text-success" aria-hidden />;
  if (state === "active") return <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden />;
  if (state === "failed") return <Circle className="h-4 w-4 text-danger" aria-hidden />;
  return <Circle className="h-4 w-4 text-border-strong" aria-hidden />;
}
