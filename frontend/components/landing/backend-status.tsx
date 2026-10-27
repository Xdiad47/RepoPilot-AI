"use client";

import { CircleAlert, Loader2, ShieldAlert, ShieldCheck, Wifi } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { HealthState } from "@/hooks/use-health";

/** Tells the visitor, before they submit anything, what the backend can and cannot do right now. */
export function BackendStatus({ state }: { state: HealthState }) {
  if (state.kind === "loading") {
    return (
      <Badge>
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Checking backend…
      </Badge>
    );
  }
  if (state.kind === "error") {
    const missing = state.error.code === "missing_configuration";
    return (
      <Badge tone="danger">
        <CircleAlert className="h-3 w-3" aria-hidden /> {missing ? "Backend URL not configured" : "Backend offline"}
      </Badge>
    );
  }
  const { llm, sandbox } = state.health;
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      <Badge tone={llm.configured ? "success" : "danger"}>
        <Wifi className="h-3 w-3" aria-hidden /> {llm.configured ? `AI online · ${llm.model}` : "AI provider not configured"}
      </Badge>
      {sandbox.available ? (
        <Badge tone="success">
          <ShieldCheck className="h-3 w-3" aria-hidden /> Sandboxed test validation on
        </Badge>
      ) : (
        <Badge tone="warning" title={sandbox.detail}>
          <ShieldAlert className="h-3 w-3" aria-hidden /> Validation unavailable · patches are proposals only
        </Badge>
      )}
    </div>
  );
}
