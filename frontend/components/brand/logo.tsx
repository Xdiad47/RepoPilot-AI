import Link from "next/link";
import { cn } from "@/lib/utils";

/** The RepoPilot mark: a heading chevron (the "pilot") above a scan line (the code it inspects). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("h-8 w-8", className)} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-accent" />
      <path d="M16 6.5 24 21l-8-3.4L8 21 16 6.5Z" className="fill-accent-fg" />
      <rect x="9" y="24" width="14" height="2.2" rx="1.1" className="fill-accent-fg" opacity="0.55" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <Link href="/" className={cn("group inline-flex items-center gap-2.5", className)} aria-label="RepoPilot AI home">
      <LogoMark className="transition-transform group-hover:-rotate-6" />
      <span className="text-[15px] font-semibold tracking-tight">
        RepoPilot<span className="ml-1 rounded bg-accent/15 px-1.5 py-0.5 text-[11px] font-bold text-accent">AI</span>
      </span>
    </Link>
  );
}
