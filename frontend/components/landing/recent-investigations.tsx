"use client";

import { History, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { clearRecent, getRecentServerSnapshot, getRecentSnapshot, parseRecent, subscribeRecent } from "@/lib/storage";

const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function RecentInvestigations() {
  // localStorage is an external system: subscribe to it instead of copying it into state from an effect.
  const raw = useSyncExternalStore(subscribeRecent, getRecentSnapshot, getRecentServerSnapshot);
  const items = useMemo(() => parseRecent(raw), [raw]);

  if (items.length === 0) return null;

  return (
    <section aria-labelledby="recent-heading" className="mt-8">
      <div className="mb-2 flex items-center justify-between">
        <h2 id="recent-heading" className="inline-flex items-center gap-2 text-sm font-medium text-muted">
          <History className="h-4 w-4" aria-hidden /> Recent investigations
        </h2>
        <Button variant="ghost" size="sm" onClick={clearRecent}>
          <Trash2 className="h-3.5 w-3.5" aria-hidden /> Clear
        </Button>
      </div>
      <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
        {items.map((item) => (
          <li key={item.id}>
            <Link href={`/investigation/${item.id}`} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-surface-2">
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{item.repository}</span>
                <span className="block truncate text-xs text-muted">{item.summary}</span>
              </span>
              <time dateTime={item.createdAt} className="shrink-0 text-xs text-faint">
                {formatter.format(new Date(item.createdAt))}
              </time>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-faint">Stored only in this browser. Results expire on the server after 24 hours.</p>
    </section>
  );
}
