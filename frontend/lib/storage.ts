import { INVESTIGATION_ID, truncate } from "@/lib/utils";

/** Recent investigations live in this browser only. Never store API keys or secrets here. */
export interface RecentInvestigation {
  id: string;
  repository: string;
  summary: string;
  createdAt: string;
}

const KEY = "repopilot:recent:v1";
const MAX = 8;

function isRecent(value: unknown): value is RecentInvestigation {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    INVESTIGATION_ID.test(v.id) &&
    typeof v.repository === "string" &&
    typeof v.summary === "string" &&
    typeof v.createdAt === "string"
  );
}

export function parseRecent(raw: string | null): RecentInvestigation[] {
  try {
    const parsed: unknown = JSON.parse(raw ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isRecent).slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function loadRecent(): RecentInvestigation[] {
  return parseRecent(getRecentSnapshot());
}

// --- external-store plumbing for useSyncExternalStore (keeps tabs and components in sync) ---
const CHANGE_EVENT = "repopilot:recent-changed";

/** Raw string snapshot (a primitive, so React can compare it cheaply). Empty list on the server. */
export function getRecentSnapshot(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "[]";
  } catch {
    return "[]";
  }
}

export const getRecentServerSnapshot = (): string => "[]";

export function subscribeRecent(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(CHANGE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function notify() {
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function saveRecent(entry: { id: string; repositoryUrl: string; bug: string }): void {
  try {
    const repository = entry.repositoryUrl.replace(/^https:\/\/(www\.)?github\.com\//, "").replace(/\/$/, "");
    const next: RecentInvestigation = {
      id: entry.id,
      repository,
      summary: truncate(entry.bug, 90),
      createdAt: new Date().toISOString(),
    };
    const rest = loadRecent().filter((r) => r.id !== entry.id);
    window.localStorage.setItem(KEY, JSON.stringify([next, ...rest].slice(0, MAX)));
    notify();
  } catch {
    /* storage unavailable (private mode, quota): the feature simply degrades */
  }
}

export function clearRecent(): void {
  try {
    window.localStorage.removeItem(KEY);
    notify();
  } catch {
    /* ignore */
  }
}
