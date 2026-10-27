import { ScanSearch } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <Link href="/" className={cn("group inline-flex items-center gap-2.5", className)} aria-label="RepoPilot AI home">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-accent to-accent-2 text-accent-fg shadow-lg shadow-accent/25 transition-transform group-hover:scale-105">
        <ScanSearch className="h-[18px] w-[18px]" aria-hidden />
      </span>
      <span className="text-[15px] font-semibold tracking-tight">
        RepoPilot<span className="ml-1 rounded bg-accent/15 px-1.5 py-0.5 text-[11px] font-bold text-accent">AI</span>
      </span>
    </Link>
  );
}
