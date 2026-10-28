import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { Investigation } from "@/types/api";
import { event, ID, investigation, notRun, passed, repo, result } from "./fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const apiMock = vi.hoisted(() => ({
  health: vi.fn(),
  createRepair: vi.fn(),
  getInvestigation: vi.fn(),
  diffUrl: vi.fn(() => "http://localhost:8000/api/repair/x/diff"),
  eventsUrl: vi.fn(() => "http://localhost:8000/api/repair/x/events"),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: apiMock };
});

const hookMock = vi.hoisted(() => ({ useInvestigation: vi.fn() }));
vi.mock("@/hooks/use-investigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-investigation")>();
  return { ...actual, useInvestigation: hookMock.useInvestigation };
});

import { EvidenceTrail } from "@/components/landing/evidence-trail";
import { RepairForm, validateForm } from "@/components/landing/repair-form";
import { Faq } from "@/components/landing/sections";
import { ThemeToggle } from "@/components/theme-toggle";
import { InvestigationView } from "@/components/investigation/investigation-view";
import { stageStates } from "@/components/investigation/stages";
import { mergeEvent } from "@/hooks/use-investigation";

const healthy = {
  status: "ok", version: "1", environment: "test",
  llm: { configured: true, model: "test-model", provider_host: "llm.test" },
  sandbox: { enabled: false, available: false, detail: "Sandbox is disabled (SANDBOX_ENABLED=false)." },
  github_token_configured: false, limits: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.health.mockResolvedValue(healthy);
});

describe("validateForm", () => {
  it("accepts a valid submission", () => {
    expect(validateForm("https://github.com/o/r", "The server crashes on empty input", "")).toEqual({});
  });
  it("reports each problem separately", () => {
    const errors = validateForm("nope", "short", "x".repeat(8001));
    expect(Object.keys(errors).sort()).toEqual(["bug", "repo", "trace"]);
    expect(validateForm("", "valid description here", "").repo).toMatch(/enter/i);
  });
});

describe("RepairForm", () => {
  it("shows what the backend can and cannot do before submitting", async () => {
    render(<RepairForm />);
    expect(await screen.findByText(/AI online · test-model/)).toBeInTheDocument();
    expect(screen.getByText(/Validation unavailable · patches are proposals only/)).toBeInTheDocument();
  });

  it("validates before calling the API and shows field errors accessibly", async () => {
    render(<RepairForm />);
    await screen.findByText(/AI online/);
    await userEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    expect(apiMock.createRepair).not.toHaveBeenCalled();
    expect(await screen.findByText(/enter a github repository url/i)).toBeInTheDocument();
    expect(screen.getByLabelText("GitHub repository")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/at least 10 characters/i)).toBeInTheDocument();
  });

  it("fills the form from an example, including the stack trace", async () => {
    render(<RepairForm />);
    await userEvent.click(screen.getByRole("button", { name: /empty email/i }));
    expect((screen.getByLabelText("GitHub repository") as HTMLInputElement).value).toMatch(/^https:\/\/github\.com\//);
    expect((screen.getByLabelText(/what's going wrong/i) as HTMLTextAreaElement).value).toContain("empty email");
    expect((screen.getByLabelText("Stack trace") as HTMLTextAreaElement).value).toContain("IndexError");
  });

  it("submits, remembers the investigation locally and navigates to it", async () => {
    apiMock.createRepair.mockResolvedValue({ repair_id: ID, status: "queued", status_url: "", events_url: "" });
    render(<RepairForm />);
    await userEvent.type(screen.getByLabelText("GitHub repository"), "https://github.com/octocat/hello");
    await userEvent.type(screen.getByLabelText(/what's going wrong/i), "Signup crashes when the email is empty");
    await userEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/investigation/${ID}`));
    expect(apiMock.createRepair).toHaveBeenCalledWith({
      repository_url: "https://github.com/octocat/hello",
      bug_description: "Signup crashes when the email is empty",
      stack_trace: null,
    });
    expect(window.localStorage.getItem("repopilot:recent:v1")).toContain(ID);
    expect(window.localStorage.getItem("repopilot:recent:v1")).not.toMatch(/api[_-]?key|token/i);
  });

  it("accepts owner/repository shorthand and sends the full URL", async () => {
    apiMock.createRepair.mockResolvedValue({ repair_id: ID, status: "queued", status_url: "", events_url: "" });
    render(<RepairForm />);
    await userEvent.type(screen.getByLabelText("GitHub repository"), "octocat/hello");
    await userEvent.type(screen.getByLabelText(/what's going wrong/i), "Signup crashes when the email is empty");
    await userEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/investigation/${ID}`));
    expect(apiMock.createRepair).toHaveBeenCalledWith(expect.objectContaining({ repository_url: "https://github.com/octocat/hello" }));
  });

  it("shows a loading state while the request is in flight", async () => {
    apiMock.createRepair.mockReturnValue(new Promise(() => {}));
    render(<RepairForm />);
    await userEvent.click(screen.getByRole("button", { name: /empty email/i }));
    await userEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    const busy = await screen.findByRole("button", { name: /starting investigation/i });
    expect(busy).toBeDisabled();
  });

  it("displays backend errors clearly and maps field errors back onto the form", async () => {
    apiMock.createRepair.mockRejectedValue(new ApiError("validation_error", "Only github.com repositories are supported.", 422, { repository_url: "Only github.com repositories are supported." }));
    render(<RepairForm />);
    await userEvent.click(screen.getByRole("button", { name: /empty email/i }));
    await userEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    expect(await screen.findAllByText(/only github\.com repositories/i)).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: /analyze repository/i })).toBeEnabled();
  });

  it("explains rate limiting", async () => {
    apiMock.createRepair.mockRejectedValue(new ApiError("rate_limited", "Rate limit reached: at most 5 investigations per hour.", 429, undefined, 600));
    render(<RepairForm />);
    await userEvent.click(screen.getByRole("button", { name: /empty email/i }));
    await userEvent.click(screen.getByRole("button", { name: /analyze repository/i }));
    expect(await screen.findByText("Slow down a little")).toBeInTheDocument();
  });

  it("blocks submission and says why when the AI provider is not configured", async () => {
    apiMock.health.mockResolvedValue({ ...healthy, llm: { configured: false, model: null, provider_host: null } });
    render(<RepairForm />);
    expect((await screen.findAllByText(/AI provider not configured/i)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /analyze repository/i })).toBeDisabled();
  });

  it("shows a missing-configuration state when no backend URL exists", async () => {
    apiMock.health.mockRejectedValue(new ApiError("missing_configuration", "The backend URL is not configured."));
    render(<RepairForm />);
    expect((await screen.findAllByText(/missing configuration|backend url not configured/i)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /analyze repository/i })).toBeDisabled();
  });

  it("warns, without blocking, when the backend is offline", async () => {
    apiMock.health.mockRejectedValue(new ApiError("network_error", "Cannot reach the RepoPilot backend."));
    render(<RepairForm />);
    expect(await screen.findByText("Backend is not responding")).toBeInTheDocument();
    expect(screen.getByText("Backend offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /analyze repository/i })).toBeEnabled();
  });

  it("lists recent investigations from local storage and can clear them", async () => {
    window.localStorage.setItem(
      "repopilot:recent:v1",
      JSON.stringify([{ id: ID, repository: "octocat/hello", summary: "Signup crashes", createdAt: "2026-10-27T10:00:00Z" }]),
    );
    render(<RepairForm />);
    const link = await screen.findByRole("link", { name: /octocat\/hello/ });
    expect(link).toHaveAttribute("href", `/investigation/${ID}`);
    await userEvent.click(screen.getByRole("button", { name: /clear/i }));
    await waitFor(() => expect(screen.queryByRole("link", { name: /octocat\/hello/ })).not.toBeInTheDocument());
  });
});

function showing(state: Partial<ReturnType<typeof hookMock.useInvestigation>>) {
  hookMock.useInvestigation.mockReturnValue({ investigation: null, loadState: "ready", error: null, connection: "closed", retry: vi.fn(), ...state });
}

describe("InvestigationView states", () => {
  it("rejects malformed ids without calling the API", () => {
    render(<InvestigationView id="../../etc/passwd" />);
    expect(screen.getByText(/isn't valid/i)).toBeInTheDocument();
    expect(hookMock.useInvestigation).not.toHaveBeenCalled();
  });

  it("shows a loading skeleton", () => {
    showing({ loadState: "loading" });
    render(<InvestigationView id={ID} />);
    expect(screen.getByLabelText("Loading investigation")).toHaveAttribute("aria-busy", "true");
  });

  it("shows not-found for expired investigations", () => {
    showing({ loadState: "not_found" });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Investigation not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /start a new investigation/i })).toHaveAttribute("href", "/");
  });

  it("shows a retryable error when the backend cannot be reached", async () => {
    const retry = vi.fn();
    showing({ loadState: "error", error: new ApiError("network_error", "Cannot reach the RepoPilot backend."), retry });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Backend unreachable")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalled();
  });

  it("shows an unsupported repository honestly, with partial repository info and no tabs", () => {
    showing({
      investigation: investigation({
        status: "failed", result: null,
        repository: { ...repo, primary_language: "Go", supported: false, support_note: "Go repositories are not supported yet." },
        error: { code: "unsupported_repository", message: "Go repositories are not supported yet.", stage: "analyze" },
        events: [event(1, "queued", "info", "accepted"), event(2, "clone", "completed", "Cloned"), event(3, "analyze", "started", "Detecting language")],
      }),
    });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("This repository isn't supported yet")).toBeInTheDocument();
    expect(screen.getByText("Unsupported")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /root cause/i })).not.toBeInTheDocument();
    expect(screen.getByText(/stopped during the “analyze” step/i)).toBeInTheDocument();
  });

  it("shows an in-progress investigation using only real events", () => {
    showing({
      connection: "live",
      investigation: investigation({
        status: "running", result: null, repository: null,
        events: [event(1, "queued", "info", "Investigation accepted"), event(2, "clone", "started", "Shallow-cloning into an isolated workspace")],
      }),
    });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Investigation in progress")).toBeInTheDocument();
    expect(screen.getByText("Shallow-cloning into an isolated workspace")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("shows a queued investigation", () => {
    showing({ investigation: investigation({ status: "queued", result: null, repository: null, events: [event(1, "queued", "info", "Investigation queued (1 ahead of it)")] }) });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText(/waiting for a free worker/i)).toBeInTheDocument();
  });

  it("keeps a root-cause analysis visible when the investigation stopped early", () => {
    showing({
      investigation: investigation({
        status: "failed", error: { code: "timeout", message: "The investigation exceeded the 600s time limit.", stage: "patch" },
        result: result({ outcome: "no_valid_patch", changes: [], diff: "", regression_test: null }),
      }),
    });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("The investigation timed out")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /root cause/i })).toBeInTheDocument();
  });

  it("completed + unvalidated: Overview calls the patch a proposal, Test Results says validation is unavailable", async () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Patch proposed — not tested")).toBeInTheDocument();
    expect(screen.queryByText(/verified by tests/i)).not.toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument(); // one of two evidence items verified

    await userEvent.click(screen.getByRole("tab", { name: /test results/i }));
    expect(screen.getAllByText(/validation unavailable/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/nothing was executed/i)).toBeInTheDocument();
    expect(screen.queryByText(/raw output/i)).not.toBeInTheDocument();
  });

  it("completed + validated: shows real before/after runs", async () => {
    showing({ investigation: investigation({ result: result({ validation: passed }) }) });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Patch verified by tests")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /test results/i }));
    expect(screen.getByText("Before the patch")).toBeInTheDocument();
    expect(screen.getByText("After the patch")).toBeInTheDocument();
    expect(screen.getByText("Bug reproduced before patch")).toBeInTheDocument();
    expect(screen.getByText("✓ tests/test_a.py::test_x")).toBeInTheDocument();
  });

  it("Root Cause tab flags evidence that was not found in the repo", async () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /root cause/i }));
    expect(screen.getByText("Verified in repository")).toBeInTheDocument();
    expect(screen.getByText("Not found in repository")).toBeInTheDocument();
    expect(screen.getByText(/does not appear in this file/i)).toBeInTheDocument();
    expect(screen.getByText("Unchecked split")).toBeInTheDocument();
    expect(screen.getByText("selected")).toBeInTheDocument();
  });

  it("Code Changes tab renders the diff and lets you inspect original and patched files", async () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
    const diff = screen.getByRole("region", { name: "Diff for app/api.py" });
    expect(within(diff).getByText(/if "@" in email else ""/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download \.patch/i })).toHaveAttribute("href", expect.stringContaining("/diff"));
    expect(screen.getByText("Not executed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Original file" }));
    expect(screen.getByRole("region", { name: "Original app/api.py" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Patched file" }));
    expect(screen.getByRole("region", { name: "Patched app/api.py" })).toBeInTheDocument();
  });

  it("Code Changes tab explains when no patch exists", async () => {
    showing({ investigation: investigation({ result: result({ outcome: "insufficient_evidence", changes: [], diff: "", regression_test: null }) }) });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Not enough evidence to propose a patch")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
    expect(screen.getByText("No patch was generated")).toBeInTheDocument();
  });

  it("copies the diff to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
    fireEvent.click(screen.getByRole("button", { name: /copy full diff/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("--- a/app/api.py")));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });
});

describe("progress derivation", () => {
  const states = (overrides: Partial<Investigation>) => stageStates(investigation(overrides));

  it("marks a validation step that only emitted 'unavailable' as not run", () => {
    expect(states({}).validate).toBe("skipped");
    expect(states({}).patch).toBe("done");
    expect(states({}).retrieve).toBe("skipped");
  });
  it("marks the step that is currently executing as active", () => {
    const s = states({ status: "running", result: null, events: [event(1, "clone", "completed", "x"), event(2, "analyze", "started", "y")] });
    expect([s.clone, s.analyze, s.plan]).toEqual(["done", "active", "pending"]);
  });
  it("marks a failed step as failed", () => {
    const s = states({ status: "failed", events: [event(1, "clone", "completed", "x"), event(2, "patch", "failed", "boom")] });
    expect(s.patch).toBe("failed");
  });
  it("recovers when a retry after a failed step succeeds", () => {
    const s = states({ events: [event(1, "patch", "failed", "invalid"), event(2, "patch", "started", "retry"), event(3, "patch", "completed", "ok")] });
    expect(s.patch).toBe("done");
  });
});

describe("mergeEvent", () => {
  it("appends new events once and flips queued to running", () => {
    const base = investigation({ status: "queued", events: [event(1, "queued", "info", "a")] });
    const next = mergeEvent(base, event(2, "clone", "started", "b"));
    expect(next.events).toHaveLength(2);
    expect(next.status).toBe("running");
    expect(mergeEvent(next, event(2, "clone", "started", "dup"))).toBe(next);
    expect(mergeEvent(next, event(1, "queued", "info", "old"))).toBe(next);
  });
});

describe("honesty of the not-run result", () => {
  it("never renders a test-output panel without a run", async () => {
    showing({ investigation: investigation({ result: result({ validation: notRun }) }) });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /test results/i }));
    expect(screen.queryByText("Before the patch")).not.toBeInTheDocument();
    expect(screen.queryByText("After the patch")).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+ passed/)).not.toBeInTheDocument();
  });
});

describe("What to do next", () => {
  it("guides the visitor and opens the code changes", async () => {
    showing({ investigation: investigation({ result: result({ validation: notRun }) }) });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("What to do next")).toBeInTheDocument();
    expect(screen.getByText(/was not tested here/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /view the code changes/i }));
    expect(screen.getByRole("tab", { name: /code changes/i })).toHaveAttribute("aria-selected", "true");
  });

  it("does not claim a patch was tested when it was not, and only suggests a final check when it passed", () => {
    showing({ investigation: investigation({ result: result({ validation: passed }) }) });
    render(<InvestigationView id={ID} />);
    expect(screen.queryByText(/was not tested here/i)).not.toBeInTheDocument();
    expect(screen.getByText(/final check before merging/i)).toBeInTheDocument();
  });

  it("is hidden when there is no patch to act on", () => {
    showing({ investigation: investigation({ result: result({ outcome: "insufficient_evidence", changes: [], diff: "", regression_test: null }) }) });
    render(<InvestigationView id={ID} />);
    expect(screen.queryByText("What to do next")).not.toBeInTheDocument();
  });
});

describe("landing page content", () => {
  it("explains in the FAQ why a patch can be untested, without overclaiming", () => {
    render(<Faq />);
    const question = screen.getByText(/why does a patch say/i);
    expect(question).toBeInTheDocument();
    expect(screen.getByText(/shown as a proposal/i)).toBeInTheDocument();
    expect(screen.getByText(/never pushes code or opens pull requests/i)).toBeInTheDocument();
  });

  it("labels the sample result as an unexecuted proposal", () => {
    render(<EvidenceTrail />);
    expect(screen.getByText(/quote found in the file/i)).toBeInTheDocument();
    expect(screen.getByText(/test validation is switched off/i)).toBeInTheDocument();
  });
});

describe("ThemeToggle", () => {
  it("switches the theme, remembers it, and labels the next action", async () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: /switch to light theme/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("repopilot-theme")).toBe("light");
    expect(screen.getByRole("button", { name: /switch to dark theme/i })).toBeInTheDocument();
    delete document.documentElement.dataset.theme;
    window.localStorage.removeItem("repopilot-theme");
  });
});
