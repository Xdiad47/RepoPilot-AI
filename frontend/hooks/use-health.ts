"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Health } from "@/types/api";

export type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; error: ApiError };

/** Checks the backend once on mount so the UI can say up-front what is and is not available. */
export function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((health) => !cancelled && setState({ kind: "ok", health }))
      .catch((e) => !cancelled && setState({ kind: "error", error: e instanceof ApiError ? e : new ApiError("unknown", "Unexpected error.") }));
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
