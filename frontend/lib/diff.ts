export type RowType = "context" | "add" | "del" | "marker";

export interface DiffRow {
  type: RowType;
  oldNo: number | null;
  newNo: number | null;
  text: string;
}

export interface DiffHunk {
  header: string;
  rows: DiffRow[];
}

export interface DiffFile {
  path: string;
  hunks: DiffHunk[];
  additions: number;
  deletions: number;
  /** 1-based line numbers in the ORIGINAL file that the patch removes or replaces. */
  removedOldLines: Set<number>;
  /** 1-based line numbers in the PATCHED file that the patch adds. */
  addedNewLines: Set<number>;
  /** This file's section of the diff, exactly as the backend produced it (ready for `git apply`). */
  raw: string;
}

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;

/**
 * Parse the unified diff produced by the backend into renderable rows.
 *
 * File headers ("--- a/x" / "+++ b/x") are only recognised between hunks: each hunk header declares how many
 * old/new lines follow, so a removed line such as "-- comment" (which prints as "--- comment") can never be
 * mistaken for a header. Unexpected input never throws; it just yields fewer rows.
 */
export function parseUnifiedDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldNo = 0;
  let newNo = 0;
  let oldLeft = 0;
  let newLeft = 0;

  const lines = diff.replace(/\n$/, "").split("\n");
  const starts: number[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const hunkOpen = hunk !== null && (oldLeft > 0 || newLeft > 0);

    if (!hunkOpen && line.startsWith("--- ") && lines[i + 1]?.startsWith("+++ ")) {
      const path = lines[i + 1].slice(4).replace(/^b\//, "").trim();
      file = { path, hunks: [], additions: 0, deletions: 0, removedOldLines: new Set(), addedNewLines: new Set(), raw: "" };
      files.push(file);
      starts.push(i);
      hunk = null;
      i += 1;
      continue;
    }

    const match = !hunkOpen ? HUNK.exec(line) : null;
    if (match && file) {
      oldNo = Number(match[1]);
      newNo = Number(match[3]);
      oldLeft = match[2] === undefined ? 1 : Number(match[2]);
      newLeft = match[4] === undefined ? 1 : Number(match[4]);
      if (oldLeft === 0) oldNo += 1; // "-N,0" means "insert after line N"
      if (newLeft === 0) newNo += 1;
      hunk = { header: line, rows: [] };
      file.hunks.push(hunk);
      continue;
    }
    if (!file || !hunk) continue;

    if (line.startsWith("\\")) {
      hunk.rows.push({ type: "marker", oldNo: null, newNo: null, text: line.slice(2) });
    } else if (line.startsWith("+")) {
      hunk.rows.push({ type: "add", oldNo: null, newNo, text: line.slice(1) });
      file.addedNewLines.add(newNo++);
      file.additions++;
      newLeft--;
    } else if (line.startsWith("-")) {
      hunk.rows.push({ type: "del", oldNo, newNo: null, text: line.slice(1) });
      file.removedOldLines.add(oldNo++);
      file.deletions++;
      oldLeft--;
    } else if (line.startsWith(" ")) {
      hunk.rows.push({ type: "context", oldNo: oldNo++, newNo: newNo++, text: line.slice(1) });
      oldLeft--;
      newLeft--;
    }
  }
  files.forEach((f, n) => {
    f.raw = lines.slice(starts[n], starts[n + 1] ?? lines.length).join("\n") + "\n";
  });
  return files;
}

/** The diff restricted to the given file paths, in original order. Empty string when none match. */
export function diffForPaths(files: DiffFile[], paths: ReadonlySet<string>): string {
  return files.filter((f) => paths.has(f.path)).map((f) => f.raw).join("");
}
