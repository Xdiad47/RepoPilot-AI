import { ArrowRight, BadgeCheck, Bug, FileCode2, GitCompareArrows, Globe } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";

/**
 * A static illustration of one real result: the "10% discount" bug in the public demo repository, including the web
 * research that run found (source count and the one comparison are copied from that run).
 * Nothing here is generated at runtime, and the caption says so.
 */
export function EvidenceTrail() {
  return (
    <section id="example" aria-labelledby="example-heading" className="mx-auto max-w-6xl scroll-mt-20 px-4 pb-4 pt-16 sm:px-6">
      <div className="mx-auto mb-10 max-w-2xl text-center">
        <p className="text-xs font-semibold uppercase tracking-widest text-accent">What you get</p>
        <h2 id="example-heading" className="mt-2 font-display text-3xl tracking-tight sm:text-4xl">
          Every claim is tied to a line of your code
        </h2>
        <p className="mt-3 text-muted">
          A real result from the demo repository: the bug report, the evidence found in the file, and the smallest patch that addresses it.
        </p>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] items-stretch gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1.15fr)_auto_minmax(0,1fr)]">
        <Step n={1} icon={<Bug className="h-4 w-4" aria-hidden />} title="You describe the bug">
          <p className="text-sm leading-6 text-fg/90">
            “A 10% discount on a 200 dollar cart takes off the entire price and the total shows 0.0 instead of 180.”
          </p>
          <p className="mt-3 font-mono text-xs text-faint">Xdiad47/repopilot-demo-bugs</p>
        </Step>

        <Connector />

        <Step n={2} icon={<FileCode2 className="h-4 w-4" aria-hidden />} title="It finds and checks the evidence">
          <p className="font-mono text-xs text-muted">
            shop/cart.py<span className="text-faint">:8</span>
          </p>
          <pre className="scroll-thin mt-2 overflow-x-auto rounded-lg border border-border bg-bg p-3 font-mono text-[12px] leading-5">
            <code>
              <span className="rounded bg-diff-del px-0.5 text-fg">return round(total - total * percent / 10, 2)</span>
            </code>
          </pre>
          <p className="mt-3 inline-flex items-start gap-1.5 text-xs text-accent-2">
            <BadgeCheck className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden /> Quote found in the file
          </p>
          <p className="mt-2 text-sm leading-6 text-fg/90">
            <code className="font-mono text-[13px]">apply_discount</code> divides the percent by 10 instead of 100.
          </p>
        </Step>

        <Connector />

        <Step n={3} icon={<GitCompareArrows className="h-4 w-4" aria-hidden />} title="It proposes a minimal patch">
          <div className="overflow-hidden rounded-lg border border-border bg-bg font-mono text-[12px] leading-5">
            <p className="bg-diff-del px-3 py-1 break-all">
              <span className="select-none pr-2 text-danger">−</span>
              <span>… percent / 10, 2)</span>
            </p>
            <p className="bg-diff-add px-3 py-1 break-all">
              <span className="select-none pr-2 text-success">+</span>
              <span>… percent / 100, 2)</span>
            </p>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge tone="success">High confidence</Badge>
            <Badge tone="success">Evidence 1/1</Badge>
            <Badge>1 file +1 −1</Badge>
          </div>
        </Step>
      </div>

      <div className="mx-auto mt-4 max-w-3xl rounded-2xl border border-border bg-surface p-5 shadow-sm">
        <h3 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-accent/15 text-accent">
            <Globe className="h-4 w-4" aria-hidden />
          </span>
          It also checks the internet
        </h3>
        <p className="mt-3 text-sm leading-6 text-muted">
          8 sources found on the internet, 4 of them official Python documentation. One was compared with the code:
        </p>
        <p className="mt-2 rounded-lg border border-accent/25 bg-accent/5 px-3 py-2 text-sm leading-6">
          <span className="font-mono text-xs text-faint">stackoverflow.com</span>
          <span className="mx-1.5 text-faint" aria-hidden>·</span>
          supports the correct formula for percentage discounts and highlights that using the wrong divisor leads to incorrect totals.
        </p>
        <p className="mt-2 text-xs leading-5 text-faint">
          Web pages explain how things should work. They never count as evidence: only the quoted line above does.
        </p>
      </div>

      <p className="mx-auto mt-5 max-w-2xl text-center text-xs leading-5 text-faint">
        On this public demo, test validation is switched off, so the patch above was a proposal and was not executed. When validation is
        available, RepoPilot runs your tests before and after the patch and reports passed, failed or inconclusive, never a guess.
      </p>
    </section>
  );
}

function Step({ n, icon, title, children }: { n: number; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-accent/15 text-accent">
          {icon}
        </span>
        <h3 className="text-sm font-semibold tracking-tight">
          <span className="mr-1.5 font-mono text-xs text-faint">0{n}</span>
          {title}
        </h3>
      </div>
      {children}
    </div>
  );
}

function Connector() {
  return (
    <div className="grid place-items-center text-faint" aria-hidden>
      <ArrowRight className="hidden h-5 w-5 lg:block" />
      <ArrowRight className="h-5 w-5 rotate-90 lg:hidden" />
    </div>
  );
}
