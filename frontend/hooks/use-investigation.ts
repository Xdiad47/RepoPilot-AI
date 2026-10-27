"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Investigation, InvestigationEvent } from "@/types/api";

export type LoadState = "loading" | "ready" | "not_found" | "error";
export type Connection = "idle" | "live" | "polling" | "closed";

const isTerminal = (s: Investigation["status"]) => s === "completed" || s === "failed";
const POLL_MS = 2000;

/** Append an event received over SSE (ignoring any we already have). */
export function mergeEvent(inv: Investigation, event: InvestigationEvent): Investigation {
  const last = inv.events.at(-1)?.seq ?? 0;
  if (event.seq <= last) return inv;
  return { ...inv, status: inv.status === "queued" ? "running" : inv.status, events: [...inv.events, event] };
}

/**
 * Loads an investigation and keeps it live. Server-sent events are the primary channel; if the stream cannot
 * be opened or drops (corporate proxies, mobile networks), it falls back to polling. Everything shown comes
 * from the backend; nothing is simulated.
 */
export function useInvestigation(id: string) {
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | null>(null);
  const [connection, setConnection] = useState<Connection>("idle");
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setLoadState("loading");
    setError(null);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;

    async function refresh(): Promise<Investigation | null> {
      try {
        const inv = await api.getInvestigation(id);
        if (cancelled) return null;
        setInvestigation(inv);
        setLoadState("ready");
        setError(null);
        return inv;
      } catch (e) {
        if (cancelled) return null;
        const apiError = e instanceof ApiError ? e : new ApiError("unknown", "Unexpected error.");
        if (apiError.status === 404) setLoadState("not_found");
        else setLoadState((state) => (state === "ready" ? state : "error"));
        setError(apiError);
        return null;
      }
    }

    function startPolling() {
      setConnection("polling");
      const tick = async () => {
        const inv = await refresh();
        if (cancelled) return;
        if (inv && isTerminal(inv.status)) {
          setConnection("closed");
          return;
        }
        pollTimer = setTimeout(tick, POLL_MS);
      };
      pollTimer = setTimeout(tick, POLL_MS);
    }

    function startStream() {
      let stream: EventSource;
      try {
        stream = new EventSource(api.eventsUrl(id));
      } catch {
        startPolling();
        return;
      }
      source = stream;
      stream.addEventListener("open", () => setConnection("live"));
      stream.addEventListener("progress", (message) => {
        try {
          const event = JSON.parse((message as MessageEvent<string>).data) as InvestigationEvent;
          setInvestigation((prev) => (prev ? mergeEvent(prev, event) : prev));
          // Repository info and results are not part of events; fetch them when a step finishes.
          if (event.status === "completed" || event.status === "failed") void refresh();
        } catch {
          /* ignore malformed event */
        }
      });
      stream.addEventListener("end", async () => {
        stream.close();
        await refresh();
        if (!cancelled) setConnection("closed");
      });
      stream.onerror = () => {
        stream.close();
        if (!cancelled) startPolling();
      };
    }

    (async () => {
      const inv = await refresh();
      if (cancelled || !inv) return;
      if (isTerminal(inv.status)) setConnection("closed");
      else startStream();
    })();

    return () => {
      cancelled = true;
      source?.close();
      clearTimeout(pollTimer);
    };
  }, [id, attempt]);

  return { investigation, loadState, error, connection, retry };
}
