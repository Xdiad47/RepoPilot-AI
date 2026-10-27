import { FileCode2, ListChecks, TriangleAlert } from "lucide-react";
import { ValidationBadge } from "@/components/investigation/validation-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { verdictFor } from "@/lib/verdict";
import type { Level, RepairResult } from "@/types/api";

const levelTone: Record<Level, "success" | "warning" | "danger"> = { high: "success", medium: "warning", low: "danger" };

export function OverviewTab({ result }: { result: RepairResult }) {
  const verdict = verdictFor(result);
  const additions = result.changes.reduce((n, c) => n + c.additions, 0);
  const deletions = result.changes.reduce((n, c) => n + c.deletions, 0);
  const verified = result.evidence.filter((e) => e.verified).length;

  return (
    <div className="space-y-4">
      <Alert tone={verdict.tone} title={verdict.headline}>
        {verdict.detail}
      </Alert>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Confidence">
          <Badge tone={levelTone[result.confidence]} className="capitalize">
            {result.confidence}
          </Badge>
        </Metric>
        <Metric label="Validation">
          <ValidationBadge validation={result.validation} />
        </Metric>
        <Metric label="Evidence verified">
          <span className="text-sm font-medium">
            {verified}/{result.evidence.length}
          </span>
        </Metric>
        <Metric label="Patch size">
          <span className="font-mono text-sm">
            {result.changes.length} file{result.changes.length === 1 ? "" : "s"} <span className="text-success">+{additions}</span>{" "}
            <span className="text-danger">−{deletions}</span>
          </span>
        </Metric>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2">
            <FileCode2 className="h-4 w-4 text-accent" aria-hidden /> Relevant files
          </CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          {result.relevant_files.length === 0 ? (
            <p className="p-4 text-sm text-muted">No relevant files were identified.</p>
          ) : (
            <ul className="divide-y divide-border">
              {result.relevant_files.map((file) => (
                <li key={file.path} className="px-4 py-3">
                  <p className="break-all font-mono text-[13px]">
                    {file.path}
                    {file.lines.length ? <span className="text-faint">:{formatLines(file.lines)}</span> : null}
                  </p>
                  <p className="mt-0.5 text-xs text-muted">{file.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {result.attempts.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-accent" aria-hidden /> Repair attempts
            </CardTitle>
            <span className="text-xs text-faint">model: {result.llm_model}</span>
          </CardHeader>
          <CardBody>
            <ol className="space-y-2">
              {result.attempts.map((a) => (
                <li key={a.iteration} className="flex gap-3 text-sm">
                  <Badge className="shrink-0 self-start">#{a.iteration}</Badge>
                  <span className="min-w-0">
                    <span className="font-medium">{a.outcome.replace(/_/g, " ")}</span>
                    {a.detail ? <span className="block break-words text-xs text-muted">{a.detail}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <ListCard title="Remaining risks" items={result.risks} empty="No specific risks were reported." />
        <ListCard title="Limitations" items={result.limitations} empty="None reported." warn />
      </div>
    </div>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-3">
      <p className="text-xs text-faint">{label}</p>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function ListCard({ title, items, empty, warn }: { title: string; items: string[]; empty: string; warn?: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="inline-flex items-center gap-2">
          <TriangleAlert className={warn ? "h-4 w-4 text-warning" : "h-4 w-4 text-muted"} aria-hidden /> {title}
        </CardTitle>
      </CardHeader>
      <CardBody>
        {items.length === 0 ? (
          <p className="text-sm text-muted">{empty}</p>
        ) : (
          <ul className="list-disc space-y-2 pl-4 text-sm leading-6 text-fg/90 marker:text-faint">
            {items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function formatLines(lines: number[]): string {
  const sorted = [...new Set(lines)].sort((a, b) => a - b);
  const ranges: string[] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (const n of sorted.slice(1)) {
    if (n === prev + 1) {
      prev = n;
      continue;
    }
    ranges.push(start === prev ? `${start}` : `${start}-${prev}`);
    start = prev = n;
  }
  ranges.push(start === prev ? `${start}` : `${start}-${prev}`);
  return ranges.slice(0, 4).join(", ");
}
