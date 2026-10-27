import { Bug, FileSearch, FlaskConical, GitCompareArrows, Lock, ScanEye, ShieldCheck, Target } from "lucide-react";
import type { ReactNode } from "react";

const steps = [
  { icon: FileSearch, title: "Inspect", text: "Shallow-clones the public repo into a private workspace, detects language, dependencies and test framework, and searches for code related to your report." },
  { icon: Target, title: "Diagnose", text: "Compares root-cause hypotheses and must back each claim with code quoted from your repository. Quotes that can't be found are flagged, never trusted." },
  { icon: GitCompareArrows, title: "Patch", text: "Proposes a minimal fix as exact edits, then builds and re-validates the unified diff against the real files before showing it." },
  { icon: FlaskConical, title: "Verify", text: "Runs the tests before and after in a locked-down sandbox. If it can't run them, it says so instead of guessing." },
];

const trust = [
  { icon: ScanEye, title: "Evidence, not vibes", text: "Every cited line is checked against the actual file. Unverified evidence lowers confidence or stops the patch." },
  { icon: ShieldCheck, title: "Honest validation", text: "Four statuses only: passed, failed, inconclusive, not run. “Passed” requires a real test run that exited 0." },
  { icon: Lock, title: "Untrusted code stays contained", text: "Tests run offline in a throwaway container: no network, read-only filesystem, no capabilities, strict CPU, memory and time limits." },
  { icon: Bug, title: "Prompt-injection aware", text: "Repository files are treated as data. The model has no tools, and it never chooses what gets executed." },
];

function SectionHeading({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto mb-10 max-w-2xl text-center">
      <p className="text-xs font-semibold uppercase tracking-widest text-accent">{eyebrow}</p>
      <h2 id={id} className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h2>
      {children ? <p className="mt-3 text-muted">{children}</p> : null}
    </div>
  );
}

export function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="how-heading" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
      <SectionHeading id="how-heading" eyebrow="Workflow" title="From bug report to evidence-backed patch">
        Four stages, each one visible in real time while it runs.
      </SectionHeading>
      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, i) => (
          <li key={step.title} className="relative rounded-xl border border-border bg-surface p-5">
            <span className="absolute right-4 top-4 text-xs font-mono text-faint">0{i + 1}</span>
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent/10 text-accent">
              <step.icon className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <h3 className="mt-4 font-semibold">{step.title}</h3>
            <p className="mt-1.5 text-sm leading-6 text-muted">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function TrustSection() {
  return (
    <section id="trust" aria-labelledby="trust-heading" className="mx-auto max-w-6xl scroll-mt-20 px-4 pb-24 sm:px-6">
      <SectionHeading id="trust-heading" eyebrow="Trust model" title="Built to never overclaim">
        A repair tool is only useful if you can believe what it tells you.
      </SectionHeading>
      <div className="grid gap-4 sm:grid-cols-2">
        {trust.map((item) => (
          <div key={item.title} className="flex gap-4 rounded-xl border border-border bg-surface p-5">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-2/10 text-accent-2">
              <item.icon className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <div>
              <h3 className="font-semibold">{item.title}</h3>
              <p className="mt-1 text-sm leading-6 text-muted">{item.text}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 px-4 py-6 text-xs text-faint sm:flex-row sm:px-6">
        <p>RepoPilot AI — evidence-based, AI-assisted code repair for public GitHub repositories.</p>
        <p>AI-generated patches can be wrong. Always review before merging.</p>
      </div>
    </footer>
  );
}
