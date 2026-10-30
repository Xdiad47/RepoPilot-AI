"use client";

import { useEffect } from "react";

/** When this page was last left (module-level so it survives the page being hidden and shown again). */
let leftAt = 0;
/** React runs effect cleanups and re-runs in quick succession in development; a real visit away takes longer. */
const REAL_VISIT_MS = 400;

/**
 * Makes coming back to a page (browser Back or Forward, or a link back to it) show a fresh page instead of a stale
 * copy with leftover form text, a stuck "Starting…" button or an out-of-date recent list.
 *
 * - `refreshOnReturn`: when this page is shown again after the visitor has been elsewhere, reload it from scratch.
 * - Always: a page restored from the browser's back/forward cache is reloaded, because that copy may be out of date.
 */
export function RefreshOnBack({ refreshOnReturn = false }: { refreshOnReturn?: boolean }) {
  useEffect(() => {
    if (refreshOnReturn && leftAt > 0 && Date.now() - leftAt > REAL_VISIT_MS) {
      leftAt = 0;
      window.location.reload();
      return;
    }
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) window.location.reload();
    };
    window.addEventListener("pageshow", restored);
    return () => {
      window.removeEventListener("pageshow", restored);
      if (refreshOnReturn) leftAt = Date.now();
    };
  }, [refreshOnReturn]);
  return null;
}

/** Test helper: forget that the page was ever left. */
export function resetRefreshOnBack() {
  leftAt = 0;
}
