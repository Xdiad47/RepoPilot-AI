"use client";

import { ArrowRight, ChevronDown, Loader2, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { BackendStatus } from "@/components/landing/backend-status";
import { RecentInvestigations } from "@/components/landing/recent-investigations";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { useHealth } from "@/hooks/use-health";
import { api, ApiError, describeError } from "@/lib/api";
import { EXAMPLES, type ExampleBug } from "@/lib/examples";
import { saveRecent } from "@/lib/storage";
import { cn, isGithubUrl, normalizeRepoInput } from "@/lib/utils";

const LIMITS = { bug: 4000, trace: 8000 };

interface FieldErrors {
  repo?: string;
  bug?: string;
  trace?: string;
}

export function validateForm(repo: string, bug: string, trace: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!repo.trim()) errors.repo = "Enter a GitHub repository URL.";
  else if (!isGithubUrl(repo)) errors.repo = "Use a public repository URL like https://github.com/owner/repository";
  if (bug.trim().length < 10) errors.bug = "Describe the problem in at least 10 characters.";
  else if (bug.length > LIMITS.bug) errors.bug = `Keep the description under ${LIMITS.bug} characters.`;
  if (trace.length > LIMITS.trace) errors.trace = `Keep the stack trace under ${LIMITS.trace} characters.`;
  return errors;
}

export function RepairForm() {
  const router = useRouter();
  const ids = useId();
  const health = useHealth();
  const [repo, setRepo] = useState("");
  const [bug, setBug] = useState("");
  const [trace, setTrace] = useState("");
  const [showTrace, setShowTrace] = useState(false);
  const [activeExample, setActiveExample] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  const configBlocked =
    (health.kind === "error" && health.error.code === "missing_configuration") ||
    (health.kind === "ok" && !health.health.llm.configured);

  function applyExample(example: ExampleBug) {
    setRepo(example.repository_url);
    setBug(example.bug_description);
    setTrace(example.stack_trace ?? "");
    setShowTrace(Boolean(example.stack_trace));
    setActiveExample(example.id);
    setErrors({});
    setSubmitError(null);
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const repoUrl = normalizeRepoInput(repo);
    if (repoUrl !== repo) setRepo(repoUrl);
    const found = validateForm(repoUrl, bug, trace);
    setErrors(found);
    setSubmitError(null);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      const accepted = await api.createRepair({
        repository_url: repoUrl,
        bug_description: bug.trim(),
        stack_trace: trace.trim() || null,
      });
      saveRecent({ id: accepted.repair_id, repositoryUrl: repoUrl, bug });
      router.push(`/investigation/${accepted.repair_id}`);
    } catch (e) {
      // Map server-side field errors back onto the form.
      if (e instanceof ApiError && e.fields) {
        setErrors({ repo: e.fields.repository_url, bug: e.fields.bug_description, trace: e.fields.stack_trace });
      }
      setSubmitError(e);
      setSubmitting(false);
    }
  }

  const failure = submitError ? describeError(submitError) : null;

  return (
    <div className="mx-auto w-full max-w-3xl text-left">
      <div className="mb-4 flex justify-center">
        <BackendStatus state={health} />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Example bug reports">
        <span className="mr-1 inline-flex items-center gap-1.5 text-xs font-medium text-muted">
          <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden /> Not sure where to start? Try an example
        </span>
        {EXAMPLES.map((example) => (
          <button
            key={example.id}
            type="button"
            onClick={() => applyExample(example)}
            aria-pressed={activeExample === example.id}
            className={cn(
              "cursor-pointer rounded-full border px-3 py-1.5 text-xs transition-colors",
              activeExample === example.id
                ? "border-accent bg-accent/10 text-fg"
                : "border-border bg-surface text-muted hover:border-border-strong hover:text-fg",
            )}
          >
            {example.title}
            <span className="ml-1.5 text-faint">· {example.hint}</span>
          </button>
        ))}
      </div>

      <form
        onSubmit={onSubmit}
        noValidate
        className="space-y-5 rounded-2xl border border-border bg-surface p-5 shadow-xl shadow-black/10 sm:p-6"
      >
        {configBlocked ? (
          <Alert tone="danger" title={health.kind === "ok" ? "AI provider not configured" : "Missing configuration"}>
            {health.kind === "ok"
              ? "The server has no LLM API key configured, so investigations are disabled."
              : "This deployment has no backend URL. Set NEXT_PUBLIC_API_BASE_URL and redeploy."}
          </Alert>
        ) : null}
        {health.kind === "error" && health.error.code !== "missing_configuration" ? (
          <Alert tone="warning" title="Backend is not responding">
            {health.error.message} You can still try to submit; it will fail clearly if the backend stays down.
          </Alert>
        ) : null}

        <Field label="GitHub repository" htmlFor={`${ids}-repo`} error={errors.repo} hint="Public repositories only. Paste the full link, or just owner/repository.">
          <Input
            id={`${ids}-repo`}
            name="repository_url"
            type="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="https://github.com/owner/repository or owner/repository"
            value={repo}
            invalid={Boolean(errors.repo)}
            aria-describedby={errors.repo ? `${ids}-repo-error` : undefined}
            onChange={(e) => setRepo(e.target.value)}
          />
        </Field>

        <Field
          label="What's going wrong?"
          htmlFor={`${ids}-bug`}
          error={errors.bug}
          counter={`${bug.length}/${LIMITS.bug}`}
          hint="Describe the symptom, expected behavior and where it happens. Specific reports get better results."
        >
          <Textarea
            id={`${ids}-bug`}
            name="bug_description"
            rows={4}
            placeholder="My Python API returns a 500 error when the user submits an empty email address. Find the cause and propose a fix."
            value={bug}
            invalid={Boolean(errors.bug)}
            aria-describedby={errors.bug ? `${ids}-bug-error` : undefined}
            onChange={(e) => setBug(e.target.value)}
          />
        </Field>

        <div>
          <button
            type="button"
            onClick={() => setShowTrace((v) => !v)}
            aria-expanded={showTrace}
            className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-muted hover:text-fg"
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", showTrace && "rotate-180")} aria-hidden />
            Stack trace <span className="text-faint">(optional)</span>
          </button>
          {showTrace ? (
            <div className="mt-3">
              <Field label="Stack trace" htmlFor={`${ids}-trace`} error={errors.trace} counter={`${trace.length}/${LIMITS.trace}`}>
                <Textarea
                  id={`${ids}-trace`}
                  name="stack_trace"
                  rows={6}
                  className="font-mono text-xs"
                  placeholder={'Traceback (most recent call last):\n  File "app/api.py", line 42, in register\n…'}
                  value={trace}
                  invalid={Boolean(errors.trace)}
                  onChange={(e) => setTrace(e.target.value)}
                />
              </Field>
            </div>
          ) : null}
        </div>

        {failure ? (
          <Alert tone="danger" title={failure.title}>
            {failure.message}
          </Alert>
        ) : null}

        <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-faint">Your repository is cloned into a disposable workspace and never modified.</p>
          <Button type="submit" variant="primary" size="lg" disabled={submitting || configBlocked}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {submitting ? "Starting investigation…" : "Analyze Repository"}
            {!submitting ? <ArrowRight className="h-4 w-4" aria-hidden /> : null}
          </Button>
        </div>
      </form>

      <RecentInvestigations />
    </div>
  );
}
