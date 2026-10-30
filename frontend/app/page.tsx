import { EvidenceTrail } from "@/components/landing/evidence-trail";
import { RepairForm } from "@/components/landing/repair-form";
import { Faq, HowItWorks, SiteFooter, TrustSection } from "@/components/landing/sections";
import { RefreshOnBack } from "@/components/refresh-on-back";
import { SiteHeader } from "@/components/site-header";

const quickSteps = ["Paste a repository link", "Describe the bug", "Review the evidence and patch"];

export default function HomePage() {
  return (
    <>
      <RefreshOnBack refreshOnReturn />
      <SiteHeader />
      <main id="main" className="flex-1">
        <section className="hero-glow relative overflow-hidden">
          <div className="grid-fade pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative mx-auto max-w-5xl px-4 pb-16 pt-14 text-center sm:px-6 sm:pt-20">
            <p className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1 text-xs text-muted backdrop-blur">
              <span className="h-1.5 w-1.5 rounded-full bg-accent-2" aria-hidden />
              Evidence-based code repair<span className="hidden sm:inline"> · honest about what was tested</span>
            </p>
            <h1 className="text-balance font-display text-5xl leading-[1.05] tracking-tight sm:text-7xl">
              Find the bug.{" "}
              <em className="text-accent">Understand the cause.</em>{" "}
              Fix it with evidence.
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-pretty text-base leading-7 text-muted sm:text-lg">
              Paste a public GitHub repository, in almost any language, and describe what&apos;s broken. RepoPilot finds the faulty code,
              checks the official documentation on the web, proves its diagnosis with quotes from your repo, and proposes a minimal patch you
              can accept or reject. It tells you plainly whether that patch was tested.
            </p>

            <ol className="mx-auto mt-7 flex max-w-2xl flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm text-muted" aria-label="How to use RepoPilot">
              {quickSteps.map((step, i) => (
                <li key={step} className="inline-flex items-center gap-2">
                  <span className="grid h-5 w-5 place-items-center rounded-full border border-border-strong font-mono text-[11px] text-fg" aria-hidden>
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
            <p className="mt-3 text-xs text-faint">No sign-up · usually 10 to 60 seconds</p>

            <div className="mt-9">
              <RepairForm />
            </div>
          </div>
        </section>
        <EvidenceTrail />
        <HowItWorks />
        <TrustSection />
        <Faq />
      </main>
      <SiteFooter />
    </>
  );
}
