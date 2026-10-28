"use client";

import { AlertCircle, Check, ChevronRight, CircleDashed, Info, Loader2, MinusCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatDuration } from "@/lib/utils";
import type { Investigation } from "@/types/api";
import { elapsedSeconds, PIPELINE, stageStates, type StageState } from "./stages";

const icon: Record<StageState, React.ReactNode> = {
  done: <Check className="h-3.5 w-3.5" aria-hidden />,
  active: <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />,
  failed: <AlertCircle className="h-3.5 w-3.5" aria-hidden />,
  skipped: <MinusCircle className="h-3.5 w-3.5" aria-hidden />,
  pending: <CircleDashed className="h-3.5 w-3.5" aria-hidden />,
};

const tone: Record<StageState, string> = {
  done: "border-success/40 bg-success-bg text-success",
  active: "border-accent/50 bg-accent/10 text-accent",
  failed: "border-danger/40 bg-danger-bg text-danger",
  skipped: "border-border bg-surface-2 text-faint",
  pending: "border-border bg-surface-2 text-faint",
};

const stateLabel: Record<StageState, string> = {
  done: "done",
  active: "in progress",
  failed: "failed",
  skipped: "not run",
  pending: "pending",
};

export function ProgressTimeline({ investigation }: { investigation: Investigation }) {
  const states = stageStates(investigation);
  const first = investigation.events[0]?.timestamp;
  const logRef = useRef<HTMLOListElement>(null);
  const running = investigation.status === "running" || investigation.status === "queued";

  useEffect(() => {
    // Follow new events inside the log only (never the page); once finished, start from the first event again.
    const log = logRef.current;
    if (log) log.scrollTop = running ? log.scrollHeight : 0;
  }, [investigation.events.length, running]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Investigation progress</CardTitle>
        <span className="text-xs text-faint">{investigation.events.length} events</span>
      </CardHeader>
      <CardBody className="space-y-4">
        <ol className="grid grid-cols-4 gap-2" aria-label="Pipeline stages">
          {PIPELINE.map(({ stage, label, description }) => (
            <li
              key={stage}
              title={`${description} — ${stateLabel[states[stage]]}`}
              className={cn("flex flex-col items-center gap-1 rounded-lg border px-1 py-2 text-center", tone[states[stage]])}
            >
              {icon[states[stage]]}
              <span className="text-[11px] font-medium leading-none">{label}</span>
              <span className="sr-only">{stateLabel[states[stage]]}</span>
            </li>
          ))}
        </ol>

        <ol ref={logRef} aria-label="Event log" aria-live="polite" className="scroll-thin max-h-72 space-y-2 overflow-y-auto pr-1">
          {investigation.events.map((event, i) => (
            <li key={event.seq} className="flex gap-2.5 text-[13px]">
              <span
                className={cn(
                  "mt-0.5 shrink-0",
                  event.status === "failed" && "text-danger",
                  event.status === "completed" && "text-success",
                  event.status === "started" && "text-accent",
                  event.status === "info" && "text-faint",
                )}
              >
                {event.status === "failed" ? (
                  <AlertCircle className="h-4 w-4" aria-hidden />
                ) : event.status === "completed" ? (
                  <Check className="h-4 w-4" aria-hidden />
                ) : event.status === "info" ? (
                  <Info className="h-4 w-4" aria-hidden />
                ) : running && i === investigation.events.length - 1 ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden />
                )}
              </span>
              <span className="min-w-0 flex-1 break-words text-fg/90">{event.message}</span>
              {first ? (
                <span className="shrink-0 font-mono text-[11px] text-faint">+{formatDuration(elapsedSeconds(first, event.timestamp))}</span>
              ) : null}
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}
