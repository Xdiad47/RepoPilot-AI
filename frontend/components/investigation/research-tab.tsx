import { BookOpenCheck, ExternalLink, Globe, Search } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ResearchReport, ResearchSource, SourceKind } from "@/types/api";

const kindLabel: Record<SourceKind, string> = { official: "Official documentation", community: "Community", other: "Web" };
const kindTone: Record<SourceKind, "success" | "info" | "neutral"> = { official: "success", community: "info", other: "neutral" };

function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function ResearchTab({ research }: { research: ResearchReport | null }) {
  if (!research || research.status !== "completed") {
    return (
      <Alert tone="neutral" title="Web research was not used for this investigation">
        {research?.note ||
          "This investigation was run before web research existed, so it relied on the repository alone."}{" "}
        The diagnosis and patch are based only on code found in the repository.
      </Alert>
    );
  }

  const used = research.sources.filter((s) => s.used).length;
  // Sources that the diagnosis actually compared with the code come first.
  const ordered = [...research.sources].sort((a, b) => Number(b.used) - Number(a.used));

  return (
    <div className="space-y-4">
      <Alert tone="info" title={`${research.sources.length} sources found with ${research.provider}`}>
        Web research explains how a framework or API is meant to behave. It is context, never proof: only code quoted from the
        repository counts as evidence. {used > 0 ? `${used} of these ${used === 1 ? "was" : "were"} compared with the code below.` : research.note}
      </Alert>

      {research.summary ? (
        <Card>
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2">
              <BookOpenCheck className="h-4 w-4 text-accent" aria-hidden /> How the research relates to this repository
            </CardTitle>
          </CardHeader>
          <CardBody>
            <p className="text-sm leading-6 text-fg/90">{research.summary}</p>
          </CardBody>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 text-muted">
          <Search className="h-3.5 w-3.5" aria-hidden /> Searched for:
        </span>
        {research.queries.map((q) => (
          <Badge key={q} className="max-w-full whitespace-normal text-left font-normal">
            {q}
          </Badge>
        ))}
      </div>

      <ul className="space-y-3" aria-label="Research sources">
        {ordered.map((source) => (
          <SourceCard key={source.id} source={source} />
        ))}
      </ul>
    </div>
  );
}

function SourceCard({ source }: { source: ResearchSource }) {
  const href = safeHref(source.url);
  return (
    <li>
      <Card className={cn(source.used && "border-accent/30")}>
        <CardBody className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={kindTone[source.kind]}>{kindLabel[source.kind]}</Badge>
            {source.used ? <Badge tone="accent">Compared with your code</Badge> : null}
            <span className="font-mono text-[11px] text-faint">{source.id}</span>
          </div>
          <h3 className="text-[15px] font-semibold leading-snug">
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-start gap-1.5 hover:text-accent">
                <span className="break-words">{source.title}</span>
                <ExternalLink className="mt-1 h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            ) : (
              source.title
            )}
          </h3>
          <p className="inline-flex items-center gap-1.5 break-all font-mono text-xs text-faint">
            <Globe className="h-3 w-3 shrink-0" aria-hidden /> {source.domain}
          </p>
          {source.snippet ? <p className="text-sm leading-6 text-muted">{source.snippet}</p> : null}
          {source.relevance ? (
            <p className="rounded-lg border border-accent/25 bg-accent/5 px-3 py-2 text-sm leading-6">
              <span className="font-medium text-accent">How it relates to this bug: </span>
              {source.relevance}
            </p>
          ) : null}
        </CardBody>
      </Card>
    </li>
  );
}
