"use client";

import { ArrowLeft, ChevronDown, Clock, Radio } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CodeChangesTab, type Decision, type Decisions } from "@/components/investigation/code-changes-tab";
import { OverviewTab } from "@/components/investigation/overview-tab";
import { ProgressTimeline } from "@/components/investigation/progress-timeline";
import { RepositoryCard } from "@/components/investigation/repository-card";
import { ResearchTab } from "@/components/investigation/research-tab";
import { RootCauseTab } from "@/components/investigation/root-cause-tab";
import { FailureAlert, LoadErrorState, NotFoundState, WorkspaceSkeleton } from "@/components/investigation/states";
import { TestResultsTab } from "@/components/investigation/test-results-tab";
import { ValidationBadge } from "@/components/investigation/validation-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useInvestigation, type Connection } from "@/hooks/use-investigation";
import { cn, formatDuration, INVESTIGATION_ID } from "@/lib/utils";
import { statusLabel } from "@/lib/verdict";
import type { Investigation } from "@/types/api";

export function InvestigationView({ id }: { id: string }) {
  if (!INVESTIGATION_ID.test(id)) return <NotFoundState invalid />;
  return <Loaded id={id} />;
}

function Loaded({ id }: { id: string }) {
  const { investigation, loadState, error, connection, retry } = useInvestigation(id);

  if (loadState === "loading" || (loadState === "ready" && !investigation)) return <WorkspaceSkeleton />;
  if (loadState === "not_found") return <NotFoundState />;
  if (loadState === "error" || !investigation) return <LoadErrorState error={error} onRetry={retry} />;
  return <Workspace investigation={investigation} connection={connection} />;
}

function Workspace({ investigation, connection }: { investigation: Investigation; connection: Connection }) {
  const { repository, result, error } = investigation;
  const active = investigation.status === "queued" || investigation.status === "running";
  const title = repository ? `${repository.owner}/${repository.name}` : investigation.repository_url.replace("https://github.com/", "");

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}>
            <ArrowLeft className="h-4 w-4" aria-hidden /> New
          </Link>
          <h1 className="min-w-0 truncate text-lg font-semibold tracking-tight">{title}</h1>
          <StatusChip investigation={investigation} />
        </div>
        <div className="flex items-center gap-2">
          {active ? <ConnectionChip connection={connection} /> : null}
          <Elapsed investigation={investigation} active={active} />
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        {/* Once there is a result, put it first on small screens; the log and bug report move below it. */}
        <aside className={cn("min-w-0 space-y-4 lg:sticky lg:top-20 lg:self-start", result && "max-lg:order-last")}>
          <BugReport investigation={investigation} />
          <ProgressTimeline investigation={investigation} />
        </aside>

        <section className="min-w-0 space-y-4" aria-label="Investigation results">
          {repository ? <RepositoryCard repo={repository} /> : null}

          {investigation.status === "failed" && error ? <FailureAlert error={error} /> : null}

          {active && !result ? (
            <Alert tone="info" title={investigation.status === "queued" ? "Waiting for a free worker…" : "Investigation in progress"}>
              This usually takes 10 to 60 seconds. You can keep this page open: results appear here as each step finishes.
            </Alert>
          ) : null}

          {result ? <ResultTabs investigation={investigation} /> : null}
        </section>
      </div>
    </div>
  );
}

function ResultTabs({ investigation }: { investigation: Investigation }) {
  const result = investigation.result!;
  const [tab, setTab] = useState("overview");
  // Accept/reject choices live here so they survive switching tabs.
  const [decisions, setDecisions] = useState<Decisions>({});
  const decide = (path: string, decision: Decision | null) =>
    setDecisions((prev) => {
      const next = { ...prev };
      if (decision) next[path] = decision;
      else delete next[path];
      return next;
    });
  const decideAll = (decision: Decision) => setDecisions(Object.fromEntries(result.changes.map((c) => [c.path, decision])));
  const sources = result.research?.status === "completed" ? result.research.sources.length : 0;
  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList aria-label="Investigation results">
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="root-cause">Root Cause</TabsTrigger>
        <TabsTrigger value="research">
          Research
          {sources > 0 ? <Badge className="px-1.5 py-0">{sources}</Badge> : null}
        </TabsTrigger>
        <TabsTrigger value="changes">
          Code Changes
          {result.changes.length > 0 ? <Badge className="px-1.5 py-0">{result.changes.length}</Badge> : null}
        </TabsTrigger>
        <TabsTrigger value="tests">
          Test Results
          <ValidationBadge validation={result.validation} />
        </TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <OverviewTab result={result} onViewChanges={() => setTab("changes")} onViewResearch={() => setTab("research")} />
      </TabsContent>
      <TabsContent value="root-cause">
        <RootCauseTab result={result} />
      </TabsContent>
      <TabsContent value="research">
        <ResearchTab research={result.research} />
      </TabsContent>
      <TabsContent value="changes">
        <CodeChangesTab result={result} decisions={decisions} onDecide={decide} onDecideAll={decideAll} />
      </TabsContent>
      <TabsContent value="tests">
        <TestResultsTab validation={result.validation} />
      </TabsContent>
    </Tabs>
  );
}

function BugReport({ investigation }: { investigation: Investigation }) {
  const [open, setOpen] = useState(false);
  const long = investigation.bug_description.length > 220;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Bug report</CardTitle>
      </CardHeader>
      <CardBody className="space-y-3">
        <p className={cn("whitespace-pre-wrap text-sm leading-6 text-fg/90", long && !open && "line-clamp-4")}>{investigation.bug_description}</p>
        {long ? (
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="inline-flex cursor-pointer items-center gap-1 text-xs text-accent">
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden /> {open ? "Show less" : "Show more"}
          </button>
        ) : null}
        {investigation.stack_trace ? (
          <details className="rounded-lg border border-border">
            <summary className="cursor-pointer select-none px-3 py-2 text-xs text-muted hover:text-fg">Stack trace</summary>
            <pre className="scroll-thin max-h-48 overflow-auto border-t border-border bg-bg p-3 font-mono text-[11px] leading-5 whitespace-pre-wrap break-words">
              {investigation.stack_trace}
            </pre>
          </details>
        ) : null}
      </CardBody>
    </Card>
  );
}

function StatusChip({ investigation }: { investigation: Investigation }) {
  const tone = { queued: "neutral", running: "info", completed: "success", failed: "danger" } as const;
  return <Badge tone={tone[investigation.status]}>{statusLabel(investigation.status)}</Badge>;
}

function ConnectionChip({ connection }: { connection: Connection }) {
  if (connection === "idle") return null;
  return (
    <Badge tone={connection === "live" ? "success" : "neutral"} title={connection === "live" ? "Streaming live events" : "Checking for updates every 2 seconds"}>
      <Radio className="h-3 w-3" aria-hidden /> {connection === "live" ? "Live" : "Polling"}
    </Badge>
  );
}

function Elapsed({ investigation, active }: { investigation: Investigation; active: boolean }) {
  // Rendered only after the investigation has loaded in the browser, so reading the clock here cannot mismatch SSR.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);

  const start = new Date(investigation.created_at).getTime();
  const end = active ? now : new Date(investigation.updated_at).getTime();
  return (
    <Badge>
      <Clock className="h-3 w-3" aria-hidden /> {formatDuration(Math.max(0, (end - start) / 1000))}
    </Badge>
  );
}
