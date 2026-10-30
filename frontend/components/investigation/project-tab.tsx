import { BookOpen, FlaskConical, Folder, HeartPulse, Play, Settings2, TriangleAlert, Wrench } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import type { FolderSummary, QualityIssue, RepositoryInfo } from "@/types/api";

const roleLabel: Record<FolderSummary["role"], string> = {
  source: "Source code", tests: "Tests", docs: "Documentation", ci: "Automation (CI)", tooling: "Tooling and deployment",
  config: "Configuration", assets: "Assets", other: "Other files",
};
const roleIcon: Record<FolderSummary["role"], React.ReactNode> = {
  source: <Folder className="h-4 w-4" />, tests: <FlaskConical className="h-4 w-4" />, docs: <BookOpen className="h-4 w-4" />,
  ci: <Play className="h-4 w-4" />, tooling: <Wrench className="h-4 w-4" />, config: <Settings2 className="h-4 w-4" />,
  assets: <Folder className="h-4 w-4" />, other: <Folder className="h-4 w-4" />,
};

export function ProjectTab({ repository }: { repository: RepositoryInfo | null }) {
  const structure = repository?.structure ?? [];
  const entries = repository?.entry_points ?? [];
  const quality = repository?.quality ?? [];
  const warnings = quality.filter((q) => q.severity === "warning");
  const notes = quality.filter((q) => q.severity === "info");
  const biggest = Math.max(1, ...structure.map((f) => f.files));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2">
            <Folder className="h-4 w-4 text-accent" aria-hidden /> Project structure
          </CardTitle>
          <span className="text-xs text-faint">{repository?.source_file_count ?? 0} source files</span>
        </CardHeader>
        <CardBody className="space-y-4">
          {structure.length === 0 ? (
            <p className="text-sm text-muted">No structure information is available for this investigation.</p>
          ) : (
            <ul className="space-y-2.5" aria-label="Folders">
              {structure.map((folder) => (
                <li key={folder.path} className="space-y-1.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="inline-flex min-w-0 items-center gap-2 text-sm">
                      <span className="text-faint" aria-hidden>{roleIcon[folder.role]}</span>
                      <span className="break-all font-mono text-[13px]">{folder.path === "(root)" ? "(top level)" : `${folder.path}/`}</span>
                    </p>
                    <span className="flex flex-wrap items-center gap-1.5 text-xs">
                      <Badge>{roleLabel[folder.role]}</Badge>
                      {folder.languages.map((l) => (
                        <Badge key={l} tone="accent">
                          {l}
                        </Badge>
                      ))}
                      <span className="text-faint">
                        {folder.files} file{folder.files === 1 ? "" : "s"}
                      </span>
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                    <div className="h-full rounded-full bg-accent/60" style={{ width: `${Math.max(4, (folder.files / biggest) * 100)}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {entries.length > 0 ? (
            <div className="border-t border-border pt-3">
              <p className="text-xs font-medium text-muted">Where the program most likely starts</p>
              <p className="mt-2 flex flex-wrap gap-1.5">
                {entries.map((e) => (
                  <Badge key={e} className="font-mono font-normal">
                    {e}
                  </Badge>
                ))}
              </p>
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="inline-flex items-center gap-2">
            <HeartPulse className="h-4 w-4 text-accent" aria-hidden /> Code health
          </CardTitle>
          <span className="text-xs text-faint">{warnings.length} warning{warnings.length === 1 ? "" : "s"} · {notes.length} note{notes.length === 1 ? "" : "s"}</span>
        </CardHeader>
        <CardBody className="space-y-3">
          <Alert tone="neutral" title="Quick checks, not a full audit">
            These are simple automatic checks on the repository (hard-coded secrets, risky calls, very large files, missing tests). They are
            hints worth a look, and the absence of a warning does not mean the code is safe.
          </Alert>
          {quality.length === 0 ? (
            <p className="text-sm text-muted">No issues were found by these checks.</p>
          ) : (
            <ul className="space-y-2.5" aria-label="Code health observations">
              {quality.map((issue, i) => (
                <IssueRow key={`${issue.title}-${issue.path}-${issue.line}-${i}`} issue={issue} />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function IssueRow({ issue }: { issue: QualityIssue }) {
  return (
    <li className="flex gap-3 rounded-lg border border-border p-3">
      <TriangleAlert className={issue.severity === "warning" ? "mt-0.5 h-4 w-4 shrink-0 text-warning" : "mt-0.5 h-4 w-4 shrink-0 text-faint"} aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {issue.title}
          <Badge tone={issue.severity === "warning" ? "warning" : "neutral"}>{issue.severity === "warning" ? "Warning" : "Note"}</Badge>
        </p>
        {issue.path ? (
          <p className="break-all font-mono text-xs text-muted">
            {issue.path}
            {issue.line ? <span className="text-faint">:{issue.line}</span> : null}
          </p>
        ) : null}
        <p className="text-sm leading-6 text-muted">{issue.detail}</p>
      </div>
    </li>
  );
}
