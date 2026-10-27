import { describe, expect, it, vi } from "vitest";
import { ApiError, api, describeError } from "@/lib/api";
import { resolveApiBaseUrl } from "@/lib/config";
import { parseUnifiedDiff } from "@/lib/diff";
import { clearRecent, loadRecent, saveRecent } from "@/lib/storage";
import { formatDuration, formatKb, isGithubUrl, truncate } from "@/lib/utils";
import { verdictFor } from "@/lib/verdict";
import { DIFF, notRun, passed, result } from "./fixtures";

describe("isGithubUrl", () => {
  it.each(["https://github.com/octocat/hello", "https://github.com/octocat/hello/", "https://www.github.com/o/r.git", "https://github.com/o/repo.name_x"])(
    "accepts %s",
    (url) => expect(isGithubUrl(url)).toBe(true),
  );
  it.each(["", "github.com/o/r", "http://github.com/o/r", "https://gitlab.com/o/r", "https://github.com/o", "https://github.com/o/r/tree/main", "git@github.com:o/r.git", "https://github.com/o/r?x=1", "https://github.com/-o/r", "https://evil.com/github.com/o/r"])(
    "rejects %s",
    (url) => expect(isGithubUrl(url)).toBe(false),
  );
});

describe("formatting helpers", () => {
  it("formats sizes and durations", () => {
    expect(formatKb(null)).toBe("—");
    expect(formatKb(512)).toBe("512 KB");
    expect(formatKb(2048)).toBe("2.0 MB");
    expect(formatDuration(0.25)).toBe("250 ms");
    expect(formatDuration(5.55)).toBe("5.5 s");
    expect(formatDuration(125)).toBe("2m 5s");
  });
  it("truncates on whitespace-normalised text", () => {
    expect(truncate("a   b\n c", 10)).toBe("a b c");
    expect(truncate("x".repeat(20), 10)).toBe("xxxxxxxxx…");
  });
});

describe("resolveApiBaseUrl", () => {
  it("uses the configured URL and trims trailing slashes", () => {
    expect(resolveApiBaseUrl(" https://api.example.com/// ", "production")).toBe("https://api.example.com");
  });
  it("falls back to localhost only outside production", () => {
    expect(resolveApiBaseUrl(undefined, "development")).toBe("http://localhost:8000");
    expect(resolveApiBaseUrl("", "test")).toBe("http://localhost:8000");
  });
  it("is null in production when unset, so a bad deploy fails loudly", () => {
    expect(resolveApiBaseUrl(undefined, "production")).toBeNull();
    expect(resolveApiBaseUrl("   ", "production")).toBeNull();
  });
});

describe("api client", () => {
  const mockFetch = (impl: () => Promise<Response> | Response) => vi.stubGlobal("fetch", vi.fn(async () => impl()));
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

  it("returns parsed JSON on success", async () => {
    mockFetch(() => json({ status: "ok" }));
    await expect(api.health()).resolves.toEqual({ status: "ok" });
  });

  it("surfaces the backend's error code, message and field errors", async () => {
    mockFetch(() => json({ error: { code: "validation_error", message: "bad url", fields: { repository_url: "bad url" } } }, 422));
    const error = await api.createRepair({ repository_url: "x", bug_description: "y" }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "validation_error", status: 422, message: "bad url", fields: { repository_url: "bad url" } });
  });

  it("exposes Retry-After for rate limits", async () => {
    mockFetch(() => json({ error: { code: "rate_limited", message: "slow down" } }, 429, { "retry-after": "120" }));
    const error = (await api.getInvestigation("a".repeat(32)).catch((e) => e)) as ApiError;
    expect(error.code).toBe("rate_limited");
    expect(error.retryAfter).toBe(120);
  });

  it("copes with non-JSON error pages from a proxy", async () => {
    mockFetch(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    const error = (await api.health().catch((e) => e)) as ApiError;
    expect(error).toMatchObject({ code: "http_502", status: 502 });
    expect(error.message).toContain("502");
  });

  it("maps network failures to a friendly error", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    const error = (await api.health().catch((e) => e)) as ApiError;
    expect(error.code).toBe("network_error");
    expect(error.message).toMatch(/cannot reach/i);
  });

  it("sends JSON and never sends credentials or secrets", async () => {
    const fetchMock = vi.fn(async () => json({ repair_id: "a".repeat(32), status: "queued", status_url: "", events_url: "" }, 202));
    vi.stubGlobal("fetch", fetchMock);
    await api.createRepair({ repository_url: "https://github.com/o/r", bug_description: "something broke badly", stack_trace: null });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/repair");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBeUndefined();
    expect(Object.keys(init.headers as object)).toEqual(["Content-Type"]);
  });

  it("describes errors for display", () => {
    expect(describeError(new ApiError("network_error", "x")).title).toBe("Backend unreachable");
    expect(describeError(new ApiError("missing_configuration", "x")).title).toBe("Missing configuration");
    expect(describeError(new ApiError("rate_limited", "x")).title).toBe("Slow down a little");
    expect(describeError(new Error("boom")).title).toBe("Unexpected error");
  });
});

describe("parseUnifiedDiff", () => {
  it("parses rows with correct line numbers", () => {
    const [file] = parseUnifiedDiff(DIFF);
    expect(file.path).toBe("app/api.py");
    expect([file.additions, file.deletions]).toEqual([1, 1]);
    expect([...file.removedOldLines]).toEqual([6]);
    expect([...file.addedNewLines]).toEqual([6]);
    const rows = file.hunks[0].rows;
    expect(rows[0]).toMatchObject({ type: "context", oldNo: 3, newNo: 3 });
    expect(rows.find((r) => r.type === "del")).toMatchObject({ oldNo: 6, newNo: null });
    expect(rows.find((r) => r.type === "add")).toMatchObject({ oldNo: null, newNo: 6 });
  });

  it("does not mistake a removed '-- comment' line for a file header", () => {
    const diff = "--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n--- comment\n+-- changed\n SELECT 1;\n";
    const files = parseUnifiedDiff(diff);
    expect(files).toHaveLength(1);
    expect(files[0].hunks[0].rows.map((r) => r.type)).toEqual(["del", "add", "context"]);
    expect(files[0].hunks[0].rows[0].text).toBe("-- comment");
  });

  it("handles multiple files, no-newline markers and empty input", () => {
    const diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n";
    const files = parseUnifiedDiff(diff);
    expect(files.map((f) => f.path)).toEqual(["a.py", "b.py"]);
    expect(files[0].hunks[0].rows.map((r) => r.type)).toEqual(["del", "marker", "add"]);
    expect(parseUnifiedDiff("")).toEqual([]);
    expect(parseUnifiedDiff("garbage\nnot a diff")).toEqual([]);
  });

  it("handles pure insertions (hunk start of 0)", () => {
    const [file] = parseUnifiedDiff("--- a/e.py\n+++ b/e.py\n@@ -0,0 +1,2 @@\n+one\n+two\n");
    expect([...file.addedNewLines]).toEqual([1, 2]);
  });
});

describe("verdictFor never overclaims", () => {
  it("only reports verification when tests really passed after reproducing the bug", () => {
    expect(verdictFor(result({ validation: passed })).headline).toBe("Patch verified by tests");
  });
  it("treats an unexecuted patch as a proposal", () => {
    const v = verdictFor(result({ validation: notRun }));
    expect(v.tone).toBe("neutral");
    expect(v.headline).toMatch(/not tested/i);
    expect(v.detail).toMatch(/validation unavailable/i);
  });
  it("warns when passing tests never reproduced the bug", () => {
    const v = verdictFor(result({ validation: { ...passed, bug_reproduced: false } }));
    expect(v.tone).toBe("warning");
    expect(v.headline).not.toMatch(/verified/i);
  });
  it("labels targeted passes honestly", () => {
    const v = verdictFor(result({ validation: { ...passed, scope: "targeted", pre_existing_failures: 4 } }));
    expect(v.headline).toMatch(/targeted/i);
    expect(v.detail).toContain("4");
  });
  it.each([
    ["failed", "danger"],
    ["inconclusive", "warning"],
  ] as const)("reports %s validation as %s", (status, tone) => {
    expect(verdictFor(result({ validation: { ...notRun, status } })).tone).toBe(tone);
  });
  it("never says verified without a patch", () => {
    expect(verdictFor(result({ outcome: "insufficient_evidence", validation: passed })).headline).toMatch(/not enough evidence/i);
    expect(verdictFor(result({ outcome: "no_valid_patch" })).tone).toBe("danger");
  });
});

describe("recent investigations storage", () => {
  const id = (n: number) => String(n).padStart(32, "0");
  it("saves, orders and clears", () => {
    saveRecent({ id: id(1), repositoryUrl: "https://github.com/o/r", bug: "first bug report text" });
    saveRecent({ id: id(2), repositoryUrl: "https://github.com/o/r2/", bug: "second" });
    expect(loadRecent().map((r) => r.id)).toEqual([id(2), id(1)]);
    expect(loadRecent()[0].repository).toBe("o/r2");
    clearRecent();
    expect(loadRecent()).toEqual([]);
  });
  it("dedupes and caps the list", () => {
    for (let i = 0; i < 12; i++) saveRecent({ id: id(i), repositoryUrl: "https://github.com/o/r", bug: "b" });
    saveRecent({ id: id(11), repositoryUrl: "https://github.com/o/r", bug: "again" });
    const list = loadRecent();
    expect(list).toHaveLength(8);
    expect(list.filter((r) => r.id === id(11))).toHaveLength(1);
  });
  it("ignores corrupt or malicious stored data", () => {
    window.localStorage.setItem("repopilot:recent:v1", "{not json");
    expect(loadRecent()).toEqual([]);
    window.localStorage.setItem("repopilot:recent:v1", JSON.stringify([{ id: "../../etc", repository: "x", summary: "y", createdAt: "z" }, 5, null]));
    expect(loadRecent()).toEqual([]);
  });
  it("never throws when storage is unavailable and never stores secrets", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveRecent({ id: id(1), repositoryUrl: "https://github.com/o/r", bug: "b" })).not.toThrow();
    spy.mockRestore();
    saveRecent({ id: id(3), repositoryUrl: "https://github.com/o/r", bug: "b" });
    const stored = window.localStorage.getItem("repopilot:recent:v1") ?? "";
    expect(stored).not.toMatch(/key|token|secret/i);
  });
});
