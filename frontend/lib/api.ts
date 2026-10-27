import { getApiBaseUrl } from "@/lib/config";
import type { Health, Investigation, RepairAccepted, RepairRequest } from "@/types/api";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number = 0,
    public readonly fields?: Record<string, string>,
    public readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const REQUEST_TIMEOUT_MS = 30_000;

function base(): string {
  const url = getApiBaseUrl();
  if (!url) {
    throw new ApiError(
      "missing_configuration",
      "The backend URL is not configured. Set NEXT_PUBLIC_API_BASE_URL for this deployment.",
    );
  }
  return url;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${base()}${path}`, { ...init, signal: controller.signal, cache: "no-store" });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      aborted ? "timeout" : "network_error",
      aborted
        ? "The backend took too long to respond."
        : "Cannot reach the RepoPilot backend. Check your connection or try again in a moment.",
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    let body: { error?: { code?: string; message?: string; fields?: Record<string, string> } } = {};
    try {
      body = await response.json();
    } catch {
      /* non-JSON error page from a proxy */
    }
    const retry = Number(response.headers.get("retry-after"));
    throw new ApiError(
      body.error?.code ?? `http_${response.status}`,
      body.error?.message ?? `The backend returned an error (HTTP ${response.status}).`,
      response.status,
      body.error?.fields,
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  createRepair: (body: RepairRequest) =>
    request<RepairAccepted>("/api/repair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getInvestigation: (id: string) => request<Investigation>(`/api/repair/${id}`),
  diffUrl: (id: string) => `${base()}/api/repair/${id}/diff`,
  eventsUrl: (id: string) => `${base()}/api/repair/${id}/events`,
};

export function describeError(error: unknown): { title: string; message: string } {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "missing_configuration":
        return { title: "Missing configuration", message: error.message };
      case "network_error":
      case "timeout":
        return { title: "Backend unreachable", message: error.message };
      case "rate_limited":
        return { title: "Slow down a little", message: error.message };
      case "llm_not_configured":
        return { title: "AI provider not configured", message: error.message };
      default:
        return { title: "Request failed", message: error.message };
    }
  }
  return { title: "Unexpected error", message: "Something went wrong. Please try again." };
}
