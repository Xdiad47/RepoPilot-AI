import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { Investigation } from "@/types/api";
import { buildReport } from "@/lib/report";
import { event, ID, investigation, multiHunkResult, notRun, passed, repo, research, result, twoFileResult } from "./fixtures";

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
import { RefreshOnBack, resetRefreshOnBack } from "@/components/refresh-on-back";
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
    expect(screen.getByText("Connecting to your repository…")).toBeInTheDocument();
    expect(screen.getByText("Shallow-cloning into an isolated workspace")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("shows a queued investigation", () => {
    showing({ investigation: investigation({ status: "queued", result: null, repository: null, events: [event(1, "queued", "info", "Investigation queued (1 ahead of it)")] }) });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Getting ready…")).toBeInTheDocument();
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

  it("copies only the accepted changes to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
    expect(screen.getByRole("button", { name: /copy accepted diff/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /accept all/i }));
    fireEvent.click(screen.getByRole("button", { name: /copy accepted diff/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("--- a/app/api.py")));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });
});

describe("Accept and reject changes", () => {
  async function openChanges() {
    showing({ investigation: investigation({ result: twoFileResult() }) });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
  }
  const summary = () => screen.getByText(/to review/i).textContent;

  it("starts with every file undecided and nothing to download", async () => {
    await openChanges();
    expect(summary()).toBe("0 accepted · 0 rejected · 2 to review");
    expect(screen.getByRole("button", { name: /download accepted/i })).toBeDisabled();
    expect(screen.getByText(/accept at least one file/i)).toBeInTheDocument();
  });

  it("accepts and rejects individual files and lets you change your mind", async () => {
    await openChanges();
    const api = within(screen.getByRole("group", { name: "Decision for app/api.py" }));
    const util = within(screen.getByRole("group", { name: "Decision for app/util.py" }));
    await userEvent.click(api.getByRole("button", { name: "Accept" }));
    await userEvent.click(util.getByRole("button", { name: "Reject" }));
    expect(summary()).toBe("1 accepted · 1 rejected · 0 to review");
    expect(screen.getByRole("button", { name: /download accepted/i })).toBeEnabled();
    await userEvent.click(api.getByRole("button", { name: "Accepted" }));
    expect(summary()).toBe("0 accepted · 1 rejected · 1 to review");
  });

  it("the copied patch contains only the accepted files", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await openChanges();
    await userEvent.click(within(screen.getByRole("group", { name: "Decision for app/util.py" })).getByRole("button", { name: "Accept" }));
    fireEvent.click(screen.getByRole("button", { name: /copy accepted diff/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = writeText.mock.calls.at(-1)![0] as string;
    expect(copied).toContain("--- a/app/util.py");
    expect(copied).not.toContain("app/api.py");
    expect(copied.endsWith("\n")).toBe(true);
  });

  it("downloads the accepted patch as repopilot.patch", async () => {
    const created = vi.fn(() => "blob:test");
    Object.defineProperty(URL, "createObjectURL", { value: created, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await openChanges();
    await userEvent.click(screen.getByRole("button", { name: /accept all/i }));
    await userEvent.click(screen.getByRole("button", { name: /download accepted/i }));
    expect(created).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });

  it("accept all and reject all apply to every file, and decisions survive switching tabs", async () => {
    await openChanges();
    await userEvent.click(screen.getByRole("button", { name: /accept all/i }));
    expect(summary()).toBe("2 accepted · 0 rejected · 0 to review");
    await userEvent.click(screen.getByRole("button", { name: /reject all/i }));
    expect(summary()).toBe("0 accepted · 2 rejected · 0 to review");
    await userEvent.click(screen.getByRole("tab", { name: /overview/i }));
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
    expect(summary()).toBe("0 accepted · 2 rejected · 0 to review");
  });

  it("says plainly that RepoPilot never changes the repository", async () => {
    await openChanges();
    expect(screen.getByText(/never changes your repository/i)).toBeInTheDocument();
  });
});

describe("Research tab", () => {
  const withResearch = (r: Investigation["result"]) => showing({ investigation: investigation({ result: r }) });

  it("lists sources with their kind, puts the ones compared with the code first, and shows how they relate", async () => {
    withResearch(result({ research }));
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /research/i }));
    expect(screen.getByText("3 sources found on the internet")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "Research sources" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Built-in exceptions");
    expect(items[0]).toHaveTextContent("Official documentation");
    expect(items[0]).toHaveTextContent("Compared with your code");
    expect(items[0]).toHaveTextContent("How it relates to this bug");
    expect(items[1]).toHaveTextContent("Community");
    expect(screen.getByText(/context, never proof/i)).toBeInTheDocument();
    expect(screen.getByText(research.summary)).toBeInTheDocument();
    expect(screen.getByText("python str.split documentation")).toBeInTheDocument();
  });

  it("opens sources safely and never renders a non-web link", async () => {
    withResearch(result({ research }));
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /research/i }));
    const link = screen.getByRole("link", { name: /built-in exceptions/i });
    expect(link).toHaveAttribute("href", "https://docs.python.org/3/library/exceptions.html");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.queryByRole("link", { name: /sneaky link/i })).not.toBeInTheDocument();
    expect(screen.getByText("Sneaky link")).toBeInTheDocument();
  });

  it("is honest when research was skipped, failed or predates the feature", async () => {
    withResearch(result({ research: { ...research, status: "unavailable", sources: [], note: "Web research found nothing usable: the Tavily usage limit was reached." } }));
    const { unmount } = render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /research/i }));
    expect(screen.getByText("Web research was not used for this investigation")).toBeInTheDocument();
    expect(screen.getByText(/usage limit was reached/i)).toBeInTheDocument();
    unmount();

    withResearch(result({ research: null }));
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /research/i }));
    expect(screen.getByText(/before web research existed/i)).toBeInTheDocument();
  });

  it("the overview summarises the research and links to it", async () => {
    withResearch(result({ research }));
    render(<InvestigationView id={ID} />);
    expect(screen.getByText(/3 sources found on the internet; 1 compared with the code/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /view sources/i }));
    expect(screen.getByRole("tab", { name: /research/i })).toHaveAttribute("aria-selected", "true");
  });

  it("shows a Research step in the progress panel", () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    expect(within(screen.getByRole("list", { name: "Pipeline stages" })).getByText("Research")).toBeInTheDocument();
  });
});

describe("Cross-language repository overview", () => {
  it("shows stack, dependencies and a detected test command that RepoPilot will not run", () => {
    showing({
      investigation: investigation({
        repository: { ...repo, primary_language: "Dart", languages: { Dart: 40, Kotlin: 6 }, frameworks: ["Flutter", "Provider"], dependencies: ["provider", "dio"], test_commands: ["flutter test"], test_frameworks: ["flutter_test"], validation_supported: false },
      }),
    });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Flutter")).toBeInTheDocument();
    expect(screen.getByText("flutter test")).toBeInTheDocument();
    expect(screen.getByText(/detected, not run by repopilot/i)).toBeInTheDocument();
    expect(screen.getByText(/dependencies \(2\)/i)).toBeInTheDocument();
  });

  it("lists detected test commands on the Test Results tab and says they were not run", async () => {
    showing({ investigation: investigation({ result: result({ validation: { ...notRun, detected_commands: ["go test ./..."] } }) }) });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /test results/i }));
    expect(screen.getByText("go test ./...")).toBeInTheDocument();
    expect(screen.getByText(/these were not run by repopilot/i)).toBeInTheDocument();
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
    expect(screen.getByText(/8 sources found on the internet/i)).toBeInTheDocument();
    expect(screen.getByText(/never count as evidence/i)).toBeInTheDocument();
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


describe("Live status while an investigation runs", () => {
  const running = (events: ReturnType<typeof event>[]) =>
    showing({ connection: "live", investigation: investigation({ status: "running", result: null, repository: null, events }) });

  it("tells the visitor in plain words that the internet is being searched", () => {
    running([
      event(1, "queued", "info", "Investigation accepted"),
      event(2, "clone", "completed", "Cloned commit 01234567; indexed 14 text files (0 skipped)"),
      event(3, "analyze", "completed", "Go project (Go modules); test framework: go test"),
      event(4, "plan", "completed", "4 initial hypotheses; will inspect 6 files"),
      event(5, "research", "started", "Searching the web with Tavily (2 queries)"),
    ]);
    render(<InvestigationView id={ID} />);
    const status = screen.getByRole("status");
    expect(within(status).getByText("Searching the internet…")).toBeInTheDocument();
    expect(within(status).getByText(/official documentation and known issues/i)).toBeInTheDocument();
    expect(within(status).getByText("Investigation in progress")).toBeInTheDocument();
  });

  it("moves on to debugging once the research is done, and shows what was really found", () => {
    running([
      event(1, "queued", "info", "Investigation accepted"),
      event(2, "retrieve", "completed", "Found 5 candidate files (0 stack-trace frames matched the repo)"),
      event(3, "research", "completed", "Found 8 sources (6 official documentation)"),
      event(4, "diagnose", "started", "Reading the relevant files and comparing hypotheses"),
    ]);
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Debugging: finding the root cause…")).toBeInTheDocument();
    const found = screen.getByText("Found so far").parentElement!;
    expect(within(found).getByText("Found 5 candidate files (0 stack-trace frames matched the repo)")).toBeInTheDocument();
    expect(within(found).getByText("Found 8 sources (6 official documentation)")).toBeInTheDocument();
  });

  it("marks finished steps as done and the current one as in progress, for screen readers too", () => {
    running([
      event(1, "queued", "info", "Investigation accepted"),
      event(2, "clone", "completed", "Cloned"),
      event(3, "analyze", "started", "Detecting language, dependencies and test framework"),
    ]);
    render(<InvestigationView id={ID} />);
    const steps = within(screen.getByRole("list", { name: "Steps" }));
    expect(steps.getByText("Connect to the repository").closest("li")).toHaveTextContent("(done)");
    expect(steps.getByText("Analyse the project").closest("li")).toHaveTextContent("(in progress)");
    expect(steps.getByText("Search the internet").closest("li")).not.toHaveTextContent("(done)");
  });

  it("between two steps it shows the next one that has not run yet", () => {
    running([event(1, "queued", "info", "accepted"), event(2, "clone", "completed", "Cloned")]);
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Analysing the repository…")).toBeInTheDocument();
  });

  it("is replaced by the results once they exist", () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    expect(screen.queryByText("Investigation in progress")).not.toBeInTheDocument();
    expect(screen.getByRole("tablist")).toBeInTheDocument();
  });

  it("the loading screen says what it is doing", () => {
    hookMock.useInvestigation.mockReturnValue({ investigation: null, loadState: "loading", error: null, connection: "idle", retry: vi.fn() });
    render(<InvestigationView id={ID} />);
    expect(screen.getByText("Opening your investigation…")).toBeInTheDocument();
  });
});


describe("Coming back to a page refreshes it", () => {
  const reload = vi.fn();
  beforeEach(() => {
    reload.mockClear();
    resetRefreshOnBack();
    Object.defineProperty(window, "location", { value: { ...window.location, reload }, configurable: true, writable: true });
  });
  afterEach(() => vi.useRealTimers());

  it("does not reload on the first visit", () => {
    render(<RefreshOnBack refreshOnReturn />);
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads when the page is shown again after the visitor was somewhere else", () => {
    vi.useFakeTimers();
    const first = render(<RefreshOnBack refreshOnReturn />);
    first.unmount(); // visitor navigates to the results page
    vi.advanceTimersByTime(5000);
    render(<RefreshOnBack refreshOnReturn />); // visitor presses Back
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload for the instant unmount/remount that React does in development", () => {
    const first = render(<RefreshOnBack refreshOnReturn />);
    first.unmount();
    render(<RefreshOnBack refreshOnReturn />);
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads only once per return, not in a loop", () => {
    vi.useFakeTimers();
    render(<RefreshOnBack refreshOnReturn />).unmount();
    vi.advanceTimersByTime(5000);
    render(<RefreshOnBack refreshOnReturn />);
    expect(reload).toHaveBeenCalledTimes(1);
    render(<RefreshOnBack refreshOnReturn />);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("a page restored from the browser's back/forward cache is reloaded, a normal load is not", () => {
    render(<RefreshOnBack />);
    window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: false }));
    expect(reload).not.toHaveBeenCalled();
    window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("stops listening once the page is left", () => {
    render(<RefreshOnBack />).unmount();
    window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }));
    expect(reload).not.toHaveBeenCalled();
  });
});


describe("Leaving individual parts of a file out of the patch", () => {
  const reviewSummary = () => screen.getByText(/to review/i).textContent ?? "";
  async function open() {
    showing({ investigation: investigation({ result: multiHunkResult() }) });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /code changes/i }));
  }

  it("offers per-part control only after the file is accepted, and only for files with several parts", async () => {
    await open();
    expect(screen.queryByRole("button", { name: /leave out part 1 of 2/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(screen.getByText(/has 2 separate parts/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /leave out part 2 of 2/i })).toBeInTheDocument();
  });

  it("copies only the parts that were kept, with a valid header", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: /leave out part 2 of 2/i }));
    expect(reviewSummary()).toContain("1 part left out");
    expect(screen.getByText("left out of the patch")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /copy accepted diff/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = writeText.mock.calls.at(-1)![0] as string;
    expect(copied).toContain("@@ -2,3 +2,3 @@ def register(payload):");
    expect(copied).not.toContain("def other()");
    expect(copied).not.toContain("return x + 1");
  });

  it("including the part again restores it, and leaving out every part disables the download", async () => {
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: /leave out part 1 of 2/i }));
    await userEvent.click(screen.getByRole("button", { name: /leave out part 2 of 2/i }));
    expect(screen.getByRole("button", { name: /download accepted/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /include part 1 of 2/i }));
    expect(screen.getByRole("button", { name: /download accepted/i })).toBeEnabled();
    expect(reviewSummary()).toContain("1 part left out");
  });

  it("forgets skipped parts of a file that is rejected", async () => {
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: /leave out part 2 of 2/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(reviewSummary()).not.toContain("left out");
  });
});

describe("Project tab", () => {
  it("shows the structure map, entry points and code health, and explains it is not an audit", async () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /^project/i }));
    const folders = within(screen.getByRole("list", { name: "Folders" }));
    expect(folders.getByText("(top level)")).toBeInTheDocument();
    expect(folders.getByText("app/")).toBeInTheDocument();
    expect(folders.getByText("Tests")).toBeInTheDocument();
    expect(screen.getByText("app/main.py")).toBeInTheDocument();
    expect(screen.getByText("Quick checks, not a full audit")).toBeInTheDocument();
    const issues = within(screen.getByRole("list", { name: "Code health observations" }));
    expect(issues.getByText("Bare except")).toBeInTheDocument();
    expect(issues.getByText("Warning")).toBeInTheDocument();
    expect(issues.getByText("Note")).toBeInTheDocument();
    expect(issues.getByText("app/api.py")).toBeInTheDocument();
  });

  it("badges the tab with the number of warnings", () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    expect(screen.getByRole("tab", { name: /^project/i })).toHaveTextContent("1");
  });

  it("says so when an older investigation has no structure data", async () => {
    showing({ investigation: investigation({ repository: { ...repo, structure: [], entry_points: [], quality: [] } }) });
    render(<InvestigationView id={ID} />);
    await userEvent.click(screen.getByRole("tab", { name: /^project/i }));
    expect(screen.getByText(/no structure information/i)).toBeInTheDocument();
    expect(screen.getByText(/no issues were found/i)).toBeInTheDocument();
  });
});

describe("Report download", () => {
  it("the overview offers a Markdown report", () => {
    showing({ investigation: investigation() });
    render(<InvestigationView id={ID} />);
    expect(screen.getByRole("button", { name: /download report/i })).toBeEnabled();
  });

  it("the report states what was verified and what was not, like the screen does", () => {
    const text = buildReport(investigation({ result: result({ research }) }));
    expect(text).toContain("# RepoPilot AI report: octocat/hello");
    expect(text).toContain("Patch proposed — not tested");
    expect(text).toContain("1 of 2 quotes verified");
    expect(text).toContain("(NOT verified: this code was not found in the file)");
    expect(text).toContain("3 sources found on the internet");
    expect(text).toContain("[Built-in exceptions](https://docs.python.org/3/library/exceptions.html) (official documentation, docs.python.org) — compared with the code:");
    expect(text).toContain("git apply repopilot.patch");
    expect(text).toContain("**not run**");
    expect(text).toContain("generated by an AI system");
    expect(text).toContain("Bare except");
  });

  it("never lets code inside the report close its own fence, and handles missing research", () => {
    const evil = result({ research: null, diff: "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+```\n" });
    const text = buildReport(investigation({ result: evil }));
    expect(text).toContain("````diff");
    expect(text).toContain("Not used for this investigation");
  });

  it("is empty when there is no result yet", () => {
    expect(buildReport(investigation({ result: null }))).toBe("");
  });
});
