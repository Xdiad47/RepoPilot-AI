"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "repopilot-theme"; // keep in sync with THEME_BOOT in app/layout.tsx
const EVENT = "repopilot-theme-change";

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  const media = window.matchMedia?.("(prefers-color-scheme: light)");
  media?.addEventListener("change", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    media?.removeEventListener("change", onChange);
  };
}

/** The theme actually in effect: an explicit choice wins, otherwise the OS setting. */
function getTheme(): Theme {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getTheme, () => "dark" as Theme);
  const next: Theme = theme === "dark" ? "light" : "dark";

  function toggle() {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage can be blocked (private mode); the choice then simply lasts for this page view.
    }
    window.dispatchEvent(new Event(EVENT));
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className="grid h-9 w-9 cursor-pointer place-items-center rounded-lg border border-border text-muted transition-colors hover:border-border-strong hover:text-fg"
    >
      {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
    </button>
  );
}
