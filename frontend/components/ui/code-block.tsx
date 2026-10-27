import { cn } from "@/lib/utils";

interface CodeBlockProps {
  code: string;
  /** First line number to display (default 1). */
  startLine?: number;
  /** 1-based line numbers (in the displayed numbering) to highlight. */
  highlight?: Set<number>;
  tone?: "add" | "del";
  maxHeight?: string;
  className?: string;
  label?: string;
}

/** Monospace block with line numbers and optional highlighted lines. No syntax colouring by design. */
export function CodeBlock({ code, startLine = 1, highlight, tone = "add", maxHeight = "28rem", className, label }: CodeBlockProps) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <div
      role="region"
      aria-label={label ?? "Code"}
      tabIndex={0}
      className={cn("scroll-thin overflow-auto rounded-lg border border-border bg-bg font-mono text-[12.5px] leading-6", className)}
      style={{ maxHeight }}
    >
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            const no = startLine + i;
            const marked = highlight?.has(no);
            return (
              <tr key={no} className={marked ? (tone === "add" ? "bg-[var(--diff-add)]" : "bg-[var(--diff-del)]") : undefined}>
                <td className="w-12 select-none border-r border-border px-3 text-right align-top text-faint">{no}</td>
                <td className="whitespace-pre px-3 align-top">{line || " "}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
