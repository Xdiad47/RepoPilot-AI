import { Clock, Terminal } from "lucide-react";
import { ValidationBadge } from "@/components/investigation/validation-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/copy-button";
import { formatDuration } from "@/lib/utils";
import type { TestRun, Validation } from "@/types/api";

function alertFor(v: Validation): { tone: "success" | "warning" | "danger" | "neutral"; title: string } {
  switch (v.status) {
    case "passed":
      return {
        tone: v.bug_reproduced === true ? "success" : "warning",
        title: v.scope === "targeted" ? "Passed — targeted fix confirmed" : v.bug_reproduced === true ? "Passed — fix confirmed by tests" : "Passed — but the bug was not reproduced",
      };
    case "failed":
      return { tone: "danger", title: "Failed — tests still fail with this patch" };
    case "inconclusive":
      return { tone: "warning", title: "Inconclusive — the result cannot confirm the fix" };
    default:
      return { tone: "neutral", title: "Validation unavailable" };
  }
}

export function TestResultsTab({ validation }: { validation: Validation }) {
  const alert = alertFor(validation);
  return (
    <div className="space-y-4">
      <Alert tone={alert.tone} title={alert.title}>
        {validation.summary}
      </Alert>

      {validation.status === "not_run" ? (
        <Card>
          <CardBody className="space-y-2 text-sm leading-6 text-muted">
            <p>
              <strong className="text-fg">Nothing was executed.</strong> No test output exists for this investigation, and none is shown here
              on purpose. Validation needs the Docker sandbox to be enabled on the server, a Python repository, and a detectable test suite.
            </p>
            {validation.reason ? <p className="font-mono text-xs text-faint">reason: {validation.reason}</p> : null}
          </CardBody>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <ValidationBadge validation={validation} />
        {validation.bug_reproduced === true ? <Badge tone="success">Bug reproduced before patch</Badge> : null}
        {validation.bug_reproduced === false ? <Badge tone="warning">Bug not reproduced by existing tests</Badge> : null}
        {validation.pre_existing_failures > 0 ? <Badge tone="warning">{validation.pre_existing_failures} pre-existing failure(s) remain</Badge> : null}
      </div>

      {validation.fixed_tests.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Tests fixed by the patch</CardTitle>
          </CardHeader>
          <CardBody>
            <ul className="space-y-1 font-mono text-xs">
              {validation.fixed_tests.map((t) => (
                <li key={t} className="break-all text-success">
                  ✓ {t}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}

      {validation.runs.map((run) => (
        <RunCard key={run.label} run={run} />
      ))}
    </div>
  );
}

function RunCard({ run }: { run: TestRun }) {
  const title = run.label === "baseline" ? "Before the patch" : "After the patch";
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle>{title}</CardTitle>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge tone={run.exit_code === 0 ? "success" : "danger"}>exit {run.timed_out ? "timeout" : (run.exit_code ?? "—")}</Badge>
          <Badge>
            <Clock className="h-3 w-3" aria-hidden /> {formatDuration(run.duration_seconds)}
          </Badge>
          <Badge tone="success">{run.passed} passed</Badge>
          <Badge tone={run.failed ? "danger" : "neutral"}>{run.failed} failed</Badge>
          {run.errors ? <Badge tone="danger">{run.errors} errors</Badge> : null}
        </div>
      </CardHeader>
      <CardBody className="space-y-3">
        <p className="flex items-center gap-2 font-mono text-xs text-muted">
          <Terminal className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="break-all">{run.command.join(" ")}</span>
        </p>
        <p className="text-xs text-faint">Ran in an isolated container: no network, read-only filesystem, resource limits.</p>
        {run.failed_tests.length > 0 ? (
          <ul className="space-y-1 font-mono text-xs">
            {run.failed_tests.map((t) => (
              <li key={t} className="break-all text-danger">
                ✗ {t}
              </li>
            ))}
          </ul>
        ) : null}
        <details className="group rounded-lg border border-border">
          <summary className="flex cursor-pointer select-none items-center justify-between px-3 py-2 text-sm text-muted hover:text-fg">
            <span>Raw output{run.output_truncated ? " (truncated)" : ""}</span>
            <CopyButton text={run.output} />
          </summary>
          <pre className="scroll-thin max-h-96 overflow-auto border-t border-border bg-bg p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words">
            {run.output || "(no output)"}
          </pre>
        </details>
      </CardBody>
    </Card>
  );
}
