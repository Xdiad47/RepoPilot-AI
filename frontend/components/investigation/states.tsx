import { ArrowLeft, RefreshCw, SearchX } from "lucide-react";
import Link from "next/link";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ErrorInfo } from "@/types/api";

export function WorkspaceSkeleton() {
  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-8 sm:px-6" aria-busy="true" aria-label="Loading investigation">
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="space-y-4">
          <Skeleton className="h-40" />
          <Skeleton className="h-80" />
        </div>
        <div className="space-y-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-12" />
          <Skeleton className="h-96" />
        </div>
      </div>
    </div>
  );
}

export function NotFoundState({ invalid }: { invalid?: boolean }) {
  return (
    <div className="mx-auto max-w-lg px-4 py-24 text-center">
      <SearchX className="mx-auto h-10 w-10 text-faint" aria-hidden />
      <h1 className="mt-4 text-xl font-semibold">{invalid ? "That investigation link isn't valid" : "Investigation not found"}</h1>
      <p className="mt-2 text-sm text-muted">
        {invalid
          ? "The address doesn't look like a RepoPilot investigation."
          : "It may have expired (results are kept for 24 hours) or the server may have restarted."}
      </p>
      <Link href="/" className={cn(buttonVariants({ variant: "primary" }), "mt-6")}>
        <ArrowLeft className="h-4 w-4" aria-hidden /> Start a new investigation
      </Link>
    </div>
  );
}

export function LoadErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { title, message } = describeError(error);
  return (
    <div className="mx-auto max-w-xl px-4 py-24">
      <Alert
        tone="danger"
        title={title}
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Try again
          </Button>
        }
      >
        {message}
      </Alert>
    </div>
  );
}

const failureTitles: Record<string, string> = {
  unsupported_repository: "This repository isn't supported yet",
  repository_not_found: "Repository not found",
  repository_too_large: "Repository is too large",
  clone_failed: "Couldn't clone the repository",
  github_unavailable: "GitHub is unavailable",
  llm_unavailable: "The AI provider is unavailable",
  llm_output_invalid: "The AI returned an unusable answer",
  timeout: "The investigation timed out",
  cancelled: "The investigation was cancelled",
};

export function FailureAlert({ error }: { error: ErrorInfo }) {
  return (
    <Alert tone="danger" title={failureTitles[error.code] ?? "The investigation could not be completed"}>
      <p>{error.message}</p>
      {error.stage ? <p className="mt-1 text-xs text-faint">Stopped during the “{error.stage}” step.</p> : null}
    </Alert>
  );
}
