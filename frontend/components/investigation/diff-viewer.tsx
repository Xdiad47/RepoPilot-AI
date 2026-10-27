import type { DiffFile } from "@/lib/diff";
import { cn } from "@/lib/utils";

/** Renders a parsed unified diff with old/new line numbers. */
export function DiffViewer({ file }: { file: DiffFile }) {
  return (
    <div
      role="region"
      aria-label={`Diff for ${file.path}`}
      tabIndex={0}
      className="scroll-thin max-h-[32rem] overflow-auto rounded-lg border border-border bg-bg font-mono text-[12.5px] leading-6"
    >
      <table className="w-full border-collapse">
        <tbody>
          {file.hunks.map((hunk, h) => (
            <HunkRows key={h} header={hunk.header} rows={hunk.rows} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HunkRows({ header, rows }: { header: string; rows: DiffFile["hunks"][number]["rows"] }) {
  return (
    <>
      <tr className="bg-surface-2 text-faint">
        <td colSpan={4} className="select-none px-3 py-0.5 text-[11px]">
          {header}
        </td>
      </tr>
      {rows.map((row, i) => {
        if (row.type === "marker") {
          return (
            <tr key={i} className="text-faint">
              <td colSpan={4} className="px-3 italic">
                {row.text}
              </td>
            </tr>
          );
        }
        const add = row.type === "add";
        const del = row.type === "del";
        return (
          <tr key={i} className={cn(add && "bg-[var(--diff-add)]", del && "bg-[var(--diff-del)]")}>
            <td className="w-10 select-none px-2 text-right align-top text-faint">{row.oldNo ?? ""}</td>
            <td className="w-10 select-none border-r border-border px-2 text-right align-top text-faint">{row.newNo ?? ""}</td>
            <td className={cn("w-5 select-none text-center align-top", add && "text-success", del && "text-danger")} aria-label={add ? "added" : del ? "removed" : undefined}>
              {add ? "+" : del ? "−" : ""}
            </td>
            <td className="whitespace-pre pr-3 align-top">{row.text || " "}</td>
          </tr>
        );
      })}
    </>
  );
}
