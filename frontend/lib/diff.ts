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
  oldStart: number;
  oldCount: number;
  newStart: number;
  newCount: number;
  /** Text after the closing "@@" (usually the enclosing function name). */
  suffix: string;
  /** The hunk's body lines exactly as in the diff (prefix character included). */
  lines: string[];
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
  /** The two header lines ("--- a/x" and "+++ b/x"), each ending in a newline. */
  headerRaw: string;
}

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/;

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
    const hunkOpen: boolean = hunk !== null && (oldLeft > 0 || newLeft > 0);

    if (!hunkOpen && line.startsWith("--- ") && lines[i + 1]?.startsWith("+++ ")) {
      const path = lines[i + 1].slice(4).replace(/^b\//, "").trim();
      file = { path, hunks: [], additions: 0, deletions: 0, removedOldLines: new Set(), addedNewLines: new Set(), raw: "", headerRaw: `${line}\n${lines[i + 1]}\n` };
      files.push(file);
      starts.push(i);
      hunk = null;
      i += 1;
      continue;
    }

    const match: RegExpExecArray | null = !hunkOpen ? HUNK.exec(line) : null;
    if (match && file) {
      oldNo = Number(match[1]);
      newNo = Number(match[3]);
      oldLeft = match[2] === undefined ? 1 : Number(match[2]);
      newLeft = match[4] === undefined ? 1 : Number(match[4]);
      if (oldLeft === 0) oldNo += 1; // "-N,0" means "insert after line N"
      if (newLeft === 0) newNo += 1;
      hunk = {
        header: line,
        rows: [],
        oldStart: Number(match[1]),
        oldCount: oldLeft,
        newStart: Number(match[3]),
        newCount: newLeft,
        suffix: match[5] ?? "",
        lines: [],
      };
      file.hunks.push(hunk);
      continue;
    }
    if (!file || !hunk) continue;

    if (line.startsWith("\\") || line.startsWith("+") || line.startsWith("-") || line.startsWith(" ")) hunk.lines.push(line);
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

/**
 * The patch for one file with some of its blocks (hunks) left out. A kept block's "new" start line is recomputed,
 * because skipping an earlier block changes how many lines precede it; the result still applies with `git apply`.
 * Returns "" when every block is skipped, and the original text untouched when none are.
 */
export function fileWithoutHunks(file: DiffFile, skipped: ReadonlySet<number>): string {
  if (skipped.size === 0) return file.raw;
  let originalShift = 0; // lines added minus removed by ALL earlier blocks, as in the original diff
  let keptShift = 0; // same, counting only the blocks we keep
  const parts: string[] = [];
  file.hunks.forEach((hunk, i) => {
    const convention = hunk.newStart - (hunk.oldStart + originalShift); // 0 normally, +1/-1 for pure insertions/deletions
    originalShift += hunk.newCount - hunk.oldCount;
    if (skipped.has(i)) return;
    const newStart = hunk.oldStart + keptShift + convention;
    keptShift += hunk.newCount - hunk.oldCount;
    parts.push(`@@ -${hunk.oldStart},${hunk.oldCount} +${newStart},${hunk.newCount} @@${hunk.suffix}\n`, ...hunk.lines.map((l) => `${l}\n`));
  });
  return parts.length === 0 ? "" : file.headerRaw + parts.join("");
}

/** Files that still contribute something once the skipped blocks are removed. */
export function effectiveFiles(files: DiffFile[], accepted: ReadonlySet<string>, skipped: Readonly<Record<string, readonly number[]>>): DiffFile[] {
  return files.filter((f) => accepted.has(f.path) && fileWithoutHunks(f, new Set(skipped[f.path] ?? [])) !== "");
}

/** The final patch: accepted files only, minus any blocks the visitor chose to skip. */
export function patchForSelection(files: DiffFile[], accepted: ReadonlySet<string>, skipped: Readonly<Record<string, readonly number[]>>): string {
  return files.filter((f) => accepted.has(f.path)).map((f) => fileWithoutHunks(f, new Set(skipped[f.path] ?? []))).join("");
}
