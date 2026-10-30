import { ExternalLink, FileCode2, FlaskConical, GitCommit, HardDrive, Layers, Package, Star, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { formatKb } from "@/lib/utils";
import type { RepositoryInfo } from "@/types/api";

export function RepositoryCard({ repo }: { repo: RepositoryInfo }) {
  const languages = Object.entries(repo.languages ?? {}).slice(0, 6);
  // When the top two languages have the same number of files, naming one of them as "the" language would mislead.
  const tied = languages.length > 1 && languages[0][1] === languages[1][1];
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
            {repo.primary_language ? <Badge tone="accent">{tied ? "Multi-language" : repo.primary_language}</Badge> : null}
            {!repo.supported ? <Badge tone="danger">Unsupported</Badge> : null}
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-muted sm:grid-cols-4">
          <Stat icon={<FileCode2 className="h-3.5 w-3.5" />} label="Source files" value={String(repo.source_file_count)} />
          <Stat icon={<HardDrive className="h-3.5 w-3.5" />} label="Size" value={formatKb(repo.size_kb)} />
          <Stat icon={<GitCommit className="h-3.5 w-3.5" />} label="Commit" value={repo.commit_sha?.slice(0, 8) ?? "—"} mono />
          <Stat icon={<Star className="h-3.5 w-3.5" />} label="Stars" value={repo.stars == null ? "—" : String(repo.stars)} />
        </dl>

        {languages.length > 1 ? (
          <Row icon={<FileCode2 className="h-3.5 w-3.5" aria-hidden />} label="Languages">
            {languages.map(([name, count]) => (
              <Badge key={name}>
                {name} <span className="text-faint">{count}</span>
              </Badge>
            ))}
          </Row>
        ) : null}
        {repo.frameworks?.length ? (
          <Row icon={<Layers className="h-3.5 w-3.5" aria-hidden />} label="Stack">
            {repo.frameworks.map((f) => (
              <Badge key={f} tone="accent">
                {f}
              </Badge>
            ))}
          </Row>
        ) : null}
        <Row icon={<FlaskConical className="h-3.5 w-3.5" aria-hidden />} label="Tests">
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
        </Row>
        {repo.test_commands?.length ? (
          <Row icon={<Terminal className="h-3.5 w-3.5" aria-hidden />} label="Test command">
            {repo.test_commands.slice(0, 2).map((c) => (
              <code key={c} className="break-all rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px]">
                {c}
              </code>
            ))}
            <span className="text-faint">{repo.validation_supported ? "runs in the sandbox when it is enabled" : "detected, not run by RepoPilot"}</span>
          </Row>
        ) : null}
        {repo.dependencies?.length ? (
          <details className="group text-xs">
            <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 text-muted hover:text-fg">
              <Package className="h-3.5 w-3.5" aria-hidden /> Dependencies ({repo.dependencies.length})
            </summary>
            <p className="mt-2 flex flex-wrap gap-1.5">
              {repo.dependencies.map((d) => (
                <Badge key={d} className="font-mono font-normal">
                  {d}
                </Badge>
              ))}
            </p>
          </details>
        ) : null}
        {repo.support_note ? <p className="text-xs text-faint">{repo.support_note}</p> : null}
      </CardBody>
    </Card>
  );
}

function Row({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="inline-flex min-w-24 items-center gap-1.5 text-muted">
        {icon} {label}:
      </span>
      {children}
    </div>
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
