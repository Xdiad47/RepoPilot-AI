# Security model

RepoPilot AI clones and reasons about **untrusted** public repositories and, optionally, runs their tests. This document
states what is protected, how, and what is *not* protected.

## Threats and controls

| Threat | Control |
| --- | --- |
| Malicious repository URL (SSRF, `file://`, credentials, shell metacharacters) | Only `https://github.com/<owner>/<repo>` is accepted; the clone URL is rebuilt from validated parts and passed after `--` with no shell. |
| Hostile git content (hooks, submodules, symlinks, LFS filters) | `core.hooksPath=/dev/null`, no submodules, `core.symlinks=false`, `GIT_CONFIG_*=/dev/null`, `GIT_ALLOW_PROTOCOL=https`; `.git` is deleted after cloning; symlinks are never followed or copied. |
| Huge repositories / zip-bombs | GitHub-reported size check before cloning, total-size and file-count limits after, per-file size cap, clone timeout. |
| Path traversal | One `normalize_repo_path` / `resolve_inside` pair is used for every path from the model or a diff (rejects `..`, absolute, backslash, NUL, `.git`, symlinked components). |
| Prompt injection (comments, README, test output) | The model has **no tools**; all untrusted text is fenced and its look-alike tags are neutralised; output is schema-validated; the model never chooses commands, paths to execute or what to run. |
| Fabricated evidence | Each quoted snippet is searched for in the real file; unverifiable evidence lowers confidence and a patch is only attempted with at least one verified quote. |
| Malicious / sloppy patches | Edits → backend-built diff → zero-fuzz dry-run; rejects traversal, unknown files, oversize patches, syntax errors, and **protected files** (secrets, CI, Dockerfiles, lockfiles, test-runner config, and existing tests so a "fix" can't weaken validation). Applied only to a disposable copy. |
| Running untrusted tests | Docker sandbox only (below). Never in the API process or on the host. If unavailable → `not_run`, not a guess. |
| Cross-investigation leakage | Unguessable 128-bit ids, one 0700 workspace per id, workspace-name validation before any delete, stale workspaces purged on start, cleanup in `finally`. |
| Abuse / LLM cost | Per-IP hourly limit, global daily cap, body-size limit, input length limits, one concurrent investigation, investigation timeout, token caps per LLM step. |
| Secret leakage | Key only in server env; never in the frontend bundle (only `NEXT_PUBLIC_API_BASE_URL` is public); log redaction; `/api/health` exposes no secrets; internal errors are sanitised. |

## The sandbox

Every test run is a throwaway container started with a fixed argv (see `SandboxRunner.docker_args`):

```
--network none            --read-only               --cap-drop ALL          --security-opt no-new-privileges
--user 65534:65534        --pids-limit 128          --memory 512m (no swap) --cpus 1.0
--ulimit nofile/core      --tmpfs /work (size-limited, copied-in source)    --mount ...,readonly (source)
```

The only command ever executed is the allowlisted `python -m pytest -q -rfE --tb=short ...`. Output is capped
(head + tail kept so pytest's summary survives), the wall-clock timeout removes the container, and runaway output stops it.

**Verified** against real Docker with a hostile test suite: network and DNS blocked; writes to `/`, `/usr` and the source
mount fail; effective capabilities are 0; `NoNewPrivs=1`; uid/gid 65534; no Docker socket; a fork bomb is stopped by the
pids limit; a 3 GB allocation is OOM-killed (exit 137); an infinite loop hits the timeout and the container is removed;
2 M lines of output are truncated and the container is killed; filling the disk stops at the tmpfs limit; no containers
remain afterwards. (The python image's public `GPG_KEY` variable is the only environment variable present.)

### Limitations

* **Offline = no dependencies.** The image has only pytest and the standard library. Repos whose tests import third-party
  packages report `inconclusive`. (Installing dependencies would require network egress, a different trust decision.)
* **Docker group ≈ root.** Any account that can talk to the Docker daemon can become root on that machine. The sandbox is
  strong against the *repository*, but a compromise of the API process could escalate through the daemon.
* **Kernel-level escapes** are out of scope of any plain container; gVisor/Kata would add defence in depth.
* Prompt-injection can still make the model *wrong* (a bad diagnosis or patch). It cannot make the system execute
  anything, but a human must review patches.
* State is in memory (+ JSON files for finished results); the service runs a single worker by design.

### Enabling the sandbox on the VPS

The VPS is shared with production sites and has 1 vCPU / 2 GB, so the recommended production setting is
`SANDBOX_ENABLED=false` (the UI then says "Validation unavailable"). To enable it safely you would:

1. Use **rootless Docker** (or Podman) under the dedicated `repopilot` user, so a container escape yields an
   unprivileged user, not root, and the daemon socket is not root-equivalent.
2. Build the image: `docker build -t repopilot-sandbox:latest deploy/sandbox`.
3. Confirm there is enough RAM (each run is capped at 512 MB) and set `MAX_CONCURRENT_INVESTIGATIONS=1`.
4. Set `SANDBOX_ENABLED=true`; confirm `/api/health` shows `sandbox.available: true`.

For a demo, running the backend locally (or on a separate small VM) with the sandbox on is the safer alternative.

## Web research (Tavily)

* The search key is read from the server environment only, is never sent to the browser, and is redacted from logs.
* Only a short plain-text query leaves the server. It is derived from the bug report, single-line, length-limited, has URLs removed and key-like strings masked. Repository source code is never sent.
* Search results are untrusted. They are length-limited, de-duplicated, restricted to http(s) links without embedded credentials, and shown to the model inside a fenced tag that it is told never to obey. A forged closing tag inside a result is neutralised.
* Web sources can explain how an API should behave but are never accepted as evidence: only code quoted from the repository and verified against the real file counts.
* If the search fails or the key is missing, the investigation continues and the result states that research was not used.
