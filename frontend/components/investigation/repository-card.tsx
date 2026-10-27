import { ExternalLink, FileCode2, FlaskConical, GitCommit, HardDrive, Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { formatKb } from "@/lib/utils";
import type { RepositoryInfo } from "@/types/api";

export function RepositoryCard({ repo }: { repo: RepositoryInfo }) {
  return (
    <Card>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <a
              href={repo.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-base font-semibold hover:text-accent"
            >
              {repo.owner}/{repo.name} <ExternalLink className="h-3.5 w-3.5 text-faint" aria-hidden />
            </a>
            {repo.description ? <p className="mt-1 text-sm text-muted">{repo.description}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {repo.primary_language ? <Badge tone="accent">{repo.primary_language}</Badge> : null}
            {!repo.supported ? <Badge tone="danger">Unsupported</Badge> : null}
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-muted sm:grid-cols-4">
          <Stat icon={<FileCode2 className="h-3.5 w-3.5" />} label="Source files" value={String(repo.source_file_count)} />
          <Stat icon={<HardDrive className="h-3.5 w-3.5" />} label="Size" value={formatKb(repo.size_kb)} />
          <Stat icon={<GitCommit className="h-3.5 w-3.5" />} label="Commit" value={repo.commit_sha?.slice(0, 8) ?? "—"} mono />
          <Stat icon={<Star className="h-3.5 w-3.5" />} label="Stars" value={repo.stars == null ? "—" : String(repo.stars)} />
        </dl>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1.5 text-muted">
            <FlaskConical className="h-3.5 w-3.5" aria-hidden /> Tests:
          </span>
          {repo.test_frameworks.length ? (
            repo.test_frameworks.map((f) => <Badge key={f}>{f}</Badge>)
          ) : (
            <span className="text-faint">none detected</span>
          )}
          {repo.manifests.slice(0, 4).map((m) => (
            <Badge key={m} className="font-mono">
              {m}
            </Badge>
          ))}
        </div>
        {repo.support_note ? <p className="text-xs text-faint">{repo.support_note}</p> : null}
      </CardBody>
    </Card>
  );
}

function Stat({ icon, label, value, mono }: { icon: React.ReactNode; label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-faint">
        {icon}
        {label}
      </dt>
      <dd className={mono ? "mt-0.5 font-mono text-fg" : "mt-0.5 text-fg"}>{value}</dd>
    </div>
  );
}
