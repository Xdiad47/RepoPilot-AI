/**
 * Where the RepoPilot backend lives. NEXT_PUBLIC_* values are inlined at build time, so this must reference
 * `process.env.NEXT_PUBLIC_API_BASE_URL` literally. Never put secrets in NEXT_PUBLIC_* variables.
 */
export function resolveApiBaseUrl(raw: string | undefined, nodeEnv: string | undefined): string | null {
  const value = raw?.trim().replace(/\/+$/, "");
  if (value) return value;
  // Only fall back to localhost outside production, so a misconfigured deployment fails loudly.
  if (nodeEnv !== "production") return "http://localhost:8000";
  return null;
}

export function getApiBaseUrl(): string | null {
  return resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL, process.env.NODE_ENV);
}

export const DEMO_REPO_URL =
  process.env.NEXT_PUBLIC_DEMO_REPO_URL?.trim() || "https://github.com/Xdiad47/repopilot-demo-bugs";
