import { BookOpenCheck, Bug, ChevronDown, FileSearch, FlaskConical, GitCompareArrows, Globe, Hand, Lock, ScanEye, ShieldCheck, Target } from "lucide-react";
import type { ReactNode } from "react";
import { LogoMark } from "@/components/brand/logo";

const REPO_URL = "https://github.com/Xdiad47/RepoPilot-AI";

const steps = [
  { icon: FileSearch, title: "Inspect", text: "Shallow-clones the public repo into a private workspace and identifies its languages, frameworks, dependencies and test setup from the files themselves. No language list to choose from." },
  { icon: Globe, title: "Research", text: "Searches the web with Tavily for official documentation, known issues and error messages, then ranks official sources first. Only a short query leaves the server, never your code." },
  { icon: Target, title: "Diagnose", text: "Compares root-cause hypotheses and must back each claim with code quoted from your repository. Web findings are context; only verified quotes count as evidence." },
  { icon: GitCompareArrows, title: "Patch", text: "Proposes a minimal fix as exact edits, then builds and re-validates the unified diff against the real files before showing it." },
  { icon: Hand, title: "Review", text: "Accept or reject each changed file, then download only what you accepted. RepoPilot never pushes code or opens pull requests." },
  { icon: FlaskConical, title: "Verify", text: "Where it can (Python today), runs the tests before and after in a locked-down sandbox. Everywhere else it shows the test command it found and says it was not run." },
];

const trust = [
  { icon: ScanEye, title: "Evidence, not vibes", text: "Every cited line is checked against the actual file. Unverified evidence lowers confidence or stops the patch." },
  { icon: BookOpenCheck, title: "Research is context, not proof", text: "Every source links to its origin and is compared with your code. A web page can explain how an API should behave; it can never count as evidence about your repository." },
  { icon: ShieldCheck, title: "Honest validation", text: "Four statuses only: passed, failed, inconclusive, not run. “Passed” requires a real test run that exited 0." },
  { icon: Lock, title: "Untrusted code stays contained", text: "When enabled, tests run offline in a throwaway container: no network, read-only filesystem, no capabilities, strict CPU, memory and time limits." },
  { icon: Bug, title: "Prompt-injection aware", text: "Repository files and web pages are treated as data. The model has no tools, and it never chooses what gets executed." },
  { icon: Hand, title: "You stay in control", text: "Nothing is applied for you. You review each file, accept or reject it, and apply the patch yourself." },
];

const faqs: { q: string; a: ReactNode }[] = [
  {
    q: "Do I need an account?",
    a: "No. Paste a public GitHub repository link and describe the bug. Your recent investigations are remembered only in your own browser.",
  },
  {
    q: "How long does it take?",
    a: "Usually 10 to 60 seconds. The free AI tier has a speed limit, so a run can occasionally pause for a few seconds while it waits. You can watch every step as it happens.",
  },
  {
    q: "Will it change my repository?",
    a: "No. RepoPilot never pushes code or opens pull requests. You get a diff that you can read, copy or download, and apply yourself with git apply once you are happy with it.",
  },
  {
    q: "Is my code safe?",
    a: "The repository is shallow-cloned into a disposable workspace, never modified, and cleaned up automatically. The AI has no tools and cannot run commands: it only returns text that is checked before you see it. Web research sends only a short search query, with anything that looks like a key masked, and never your source code. Results are kept for 24 hours.",
  },
  {
    q: "Which repositories and languages work?",
    a: "Public GitHub repositories up to about 30 MB, in almost any language: Python, JavaScript, TypeScript, Java, Kotlin, Swift, Dart and Flutter, Go, Rust, C, C++, C#, PHP, Ruby and more. Frameworks and test commands are detected from the repository itself. Every language gets analysis, evidence and a patch proposal; only Python tests can be run for you today.",
  },
  {
    q: "What does the web research do?",
    a: "RepoPilot searches the web with Tavily for official documentation, known bugs and discussions about your error, shows every source with its link, and explains how each one relates to your code. It is background knowledge for the diagnosis, never a substitute for evidence from your repository. If the search is unavailable, the investigation continues without it and says so.",
  },
  {
    q: "Why does a patch say “not tested”?",
    a: "Running unknown code is risky, so on this public demo server test validation is switched off and every patch is shown as a proposal. Even with a sandbox, only Python tests are run today; for other languages RepoPilot shows the test command it detected so you can run it yourself. When tests do run, the result is reported honestly as passed, failed or inconclusive.",
  },
  {
    q: "Is there a usage limit?",
    a: "Yes, a few investigations per hour for each visitor, plus a daily cap, to keep the free service available for everyone.",
  },
];

function SectionHeading({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto mb-10 max-w-2xl text-center">
      <p className="text-xs font-semibold uppercase tracking-widest text-accent">{eyebrow}</p>
      <h2 id={id} className="mt-2 font-display text-3xl tracking-tight sm:text-4xl">{title}</h2>
      {children ? <p className="mt-3 text-muted">{children}</p> : null}
    </div>
  );
}

export function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="how-heading" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
      <SectionHeading id="how-heading" eyebrow="Workflow" title="From bug report to evidence-backed patch">
        Six stages, each one visible in real time while it runs.
      </SectionHeading>
      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((step, i) => (
          <li key={step.title} className="relative rounded-2xl border border-border bg-surface p-5">
            <span className="absolute right-4 top-3 font-display text-4xl leading-none text-border-strong" aria-hidden>
              {i + 1}
            </span>
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/10 text-accent">
              <step.icon className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <h3 className="mt-4 font-semibold">
              <span className="sr-only">Step {i + 1}: </span>
              {step.title}
            </h3>
            <p className="mt-1.5 text-sm leading-6 text-muted">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function TrustSection() {
  return (
    <section id="trust" aria-labelledby="trust-heading" className="mx-auto max-w-6xl scroll-mt-20 px-4 pb-20 sm:px-6">
      <SectionHeading id="trust-heading" eyebrow="Trust model" title="Built to never overclaim">
        A repair tool is only useful if you can believe what it tells you.
      </SectionHeading>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {trust.map((item) => (
          <div key={item.title} className="flex gap-4 rounded-2xl border border-border bg-surface p-5">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent-2/10 text-accent-2">
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

export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-heading" className="mx-auto max-w-3xl scroll-mt-20 px-4 pb-24 sm:px-6">
      <SectionHeading id="faq-heading" eyebrow="FAQ" title="Questions you might have" />
      <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface">
        {faqs.map((item) => (
          <details key={item.q} className="group">
            <summary className="flex cursor-pointer items-center justify-between gap-4 px-5 py-4 text-left text-[15px] font-medium hover:bg-surface-2">
              {item.q}
              <ChevronDown className="h-4 w-4 shrink-0 text-faint transition-transform group-open:rotate-180" aria-hidden />
            </summary>
            <p className="px-5 pb-5 text-sm leading-6 text-muted">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-8 sm:px-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-sm">
          <p className="inline-flex items-center gap-2 text-sm font-semibold">
            <LogoMark className="h-6 w-6" /> RepoPilot AI
          </p>
          <p className="mt-2 text-xs leading-5 text-faint">
            Evidence-based, AI-assisted code repair for public GitHub repositories. AI-generated patches can be wrong, so always review them
            before merging.
          </p>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted">
          <a href="#how-it-works" className="hover:text-fg">How it works</a>
          <a href="#trust" className="hover:text-fg">Safety</a>
          <a href="#faq" className="hover:text-fg">FAQ</a>
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="hover:text-fg">Source code</a>
        </nav>
      </div>
    </footer>
  );
}
