import { RepairForm } from "@/components/landing/repair-form";
import { HowItWorks, SiteFooter, TrustSection } from "@/components/landing/sections";
import { SiteHeader } from "@/components/site-header";

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <section className="hero-glow relative overflow-hidden">
          <div className="grid-fade pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative mx-auto max-w-5xl px-4 pb-16 pt-16 text-center sm:px-6 sm:pt-24">
            <p className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1 text-xs text-muted backdrop-blur">
              <span className="h-1.5 w-1.5 rounded-full bg-accent-2" aria-hidden />
              Multi-agent code repair · evidence-based · honest about what was tested
            </p>
            <h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
              Find the bug.{" "}
              <span className="bg-gradient-to-r from-accent to-accent-2 bg-clip-text text-transparent">Understand the cause.</span>{" "}
              Fix it with evidence.
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-pretty text-base leading-7 text-muted sm:text-lg">
              Point RepoPilot AI at a public GitHub repository and describe what&apos;s broken. It finds the faulty code, proves its
              diagnosis with quotes from your repo, proposes a minimal patch and, where your tests can run safely, checks it against them. When they can&apos;t,
              it tells you plainly that the patch is untested.
            </p>
            <div className="mt-10">
              <RepairForm />
            </div>
          </div>
        </section>
        <HowItWorks />
        <TrustSection />
      </main>
      <SiteFooter />
    </>
  );
}
