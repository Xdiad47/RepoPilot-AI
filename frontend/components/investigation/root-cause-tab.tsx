import { BadgeCheck, CircleHelp, Lightbulb, TriangleAlert } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { CopyButton } from "@/components/ui/copy-button";
import type { Evidence, Level, RepairResult } from "@/types/api";

const levelTone: Record<Level, "success" | "warning" | "danger"> = { high: "success", medium: "warning", low: "danger" };

export function RootCauseTab({ result }: { result: RepairResult }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-accent" aria-hidden /> Root cause
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge tone={levelTone[result.confidence]} className="capitalize">
              {result.confidence} confidence
            </Badge>
            <CopyButton text={result.root_cause} />
          </div>
        </CardHeader>
        <CardBody>
          <p className="text-[15px] leading-7">{result.root_cause}</p>
        </CardBody>
      </Card>

      {result.outcome === "insufficient_evidence" ? (
        <Alert tone="warning" title="The cited evidence could not be verified">
          None of the code quotes the AI cited exist in the repository, so RepoPilot AI treats this explanation as unproven and did
          not generate a patch.
        </Alert>
      ) : null}

      <section aria-labelledby="evidence-heading" className="space-y-3">
        <h2 id="evidence-heading" className="text-sm font-semibold">
          Evidence from the repository
        </h2>
        {result.evidence.length === 0 ? (
          <p className="text-sm text-muted">No evidence was cited.</p>
        ) : (
          result.evidence.map((item, i) => <EvidenceCard key={i} item={item} />)
        )}
      </section>

      {result.hypotheses.length > 0 ? (
        <section aria-labelledby="hyp-heading" className="space-y-3">
          <h2 id="hyp-heading" className="text-sm font-semibold">
            Hypotheses compared
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {result.hypotheses.map((h, i) => (
              <Card key={i} className={h.selected ? "border-accent/50" : undefined}>
                <CardBody className="space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium">{h.title}</p>
                    <div className="flex shrink-0 gap-1.5">
                      {h.selected ? <Badge tone="accent">selected</Badge> : null}
                      <Badge tone={levelTone[h.likelihood]} className="capitalize">
                        {h.likelihood}
                      </Badge>
                    </div>
                  </div>
                  <p className="text-sm leading-6 text-muted">{h.explanation}</p>
                  <Points label="Supports" items={h.evidence_for} tone="text-success" />
                  <Points label="Against" items={h.evidence_against} tone="text-danger" />
                </CardBody>
              </Card>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Points({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className={`text-xs font-medium ${tone}`}>{label}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs leading-5 text-muted">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceCard({ item }: { item: Evidence }) {
  const lines = item.start_line === item.end_line ? `${item.start_line}` : `${item.start_line}-${item.end_line}`;
  return (
    <Card className={item.verified ? undefined : "border-warning/40"}>
      <CardHeader>
        <p className="min-w-0 break-all font-mono text-[13px]">
          {item.file}
          <span className="text-faint">:{lines}</span>
        </p>
        {item.verified ? (
          <Badge tone="success">
            <BadgeCheck className="h-3 w-3" aria-hidden /> Verified in repository
          </Badge>
        ) : (
          <Badge tone="warning">
            <TriangleAlert className="h-3 w-3" aria-hidden /> Not found in repository
          </Badge>
        )}
      </CardHeader>
      <CardBody className="space-y-3">
        {item.explanation ? (
          <p className="flex gap-2 text-sm text-muted">
            <CircleHelp className="mt-1 h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
            {item.explanation}
          </p>
        ) : null}
        {item.verified && item.snippet ? (
          <CodeBlock code={item.snippet} startLine={item.start_line} maxHeight="14rem" label={`Code from ${item.file}`} />
        ) : (
          <p className="text-xs text-warning">The code the AI quoted does not appear in this file, so it is not treated as evidence.</p>
        )}
      </CardBody>
    </Card>
  );
}
