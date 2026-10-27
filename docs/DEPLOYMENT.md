# Deployment guide

Frontend → **Vercel**. Backend → your existing **VPS** behind nginx. Nothing here changes existing sites.

> Status legend: ✅ prepared in this repo · 🧑 needs your action/approval. Nothing has been deployed yet.

## 0. What the VPS already runs (inspected read-only)

| Item | Finding |
| --- | --- |
| OS / size | Ubuntu 24.04, **1 vCPU, ~1.9 GB RAM**, swap already in use |
| Existing services | Scanly RAG (uvicorn :8000), another uvicorn (:8001), Ayurveda API in Docker (:8100) |
| Web server | nginx, one file per site in `/etc/nginx/sites-enabled/`, certbot-managed Let's Encrypt certs |
| Free port used by RepoPilot | **8200** (loopback only) |

Consequences: RepoPilot runs as its own non-root user with a memory cap (512 MB) and CPU quota (70 %), one worker, one
concurrent investigation, and **sandboxed test validation stays off on this VPS** (see [SECURITY.md](SECURITY.md#enabling-the-sandbox-on-the-vps)).

## 1. Choose the API subdomain 🧑

Pick one hostname for the backend, e.g. `repopilot-api.<your-domain>`. Do **not** reuse an existing site's hostname.
Use a subdomain only; root-domain DNS is never touched.

## 2. DNS record 🧑

At your DNS provider (GoDaddy for `.in` domains bought there), for the domain you chose, add:

| Field | Value |
| --- | --- |
| Type | `A` |
| Name / Host | the subdomain label only, e.g. `repopilot-api` (GoDaddy appends the domain) |
| Value | `50.6.45.147` (the VPS public IPv4) |
| TTL | 600 seconds (or the default) |

Verify before continuing (can take a few minutes):

```bash
dig +short repopilot-api.<your-domain>     # or: nslookup / getent hosts
# expected: 50.6.45.147
```

If the domain uses a different DNS host (Cloudflare etc.), create the same `A` record there. With Cloudflare, start with
the proxy **off** (grey cloud) so certbot's HTTP challenge reaches the VPS.

## 3. Install the backend on the VPS 🧑 (run on the VPS as root)

```bash
ssh scanly-vps
git clone https://github.com/Xdiad47/RepoPilot-AI.git /tmp/repopilot-bootstrap
bash /tmp/repopilot-bootstrap/deploy/scripts/install-backend.sh
```

The first run creates the `repopilot` user, directories, virtualenv and `/etc/repopilot/backend.env` from the template,
then **stops** and asks you to edit that file. Put the real values **on the server only**:

```bash
nano /etc/repopilot/backend.env     # LLM_API_KEY, FRONTEND_ORIGIN=https://<your>.vercel.app
bash /opt/repopilot/deploy/scripts/install-backend.sh    # second run starts the service
bash /opt/repopilot/deploy/scripts/healthcheck.sh        # http://127.0.0.1:8200/api/health
```

The script refuses to run if port 8200 is taken, never overwrites an existing env file, and only writes RepoPilot's own
files (`/opt/repopilot`, `/etc/repopilot`, `/var/lib/repopilot`, `/etc/systemd/system/repopilot-api.service`).

## 4. nginx server block 🧑

```bash
bash /opt/repopilot/deploy/scripts/install-nginx.sh repopilot-api.<your-domain>
```

* Creates a **separate** file `sites-available/repopilot-api.conf` (+ symlink). Existing site files are untouched.
* Refuses a hostname already used by another site; runs `nginx -t` before and after; removes its own files if nginx
  rejects the result; reloads only on success.
* SSE-safe: `proxy_buffering off`, long read timeout. Per-IP request throttle for this site only.

## 5. HTTPS 🧑 (after DNS resolves)

```bash
certbot --nginx -d repopilot-api.<your-domain> --redirect
curl -fsS https://repopilot-api.<your-domain>/api/health
```

Certbot's existing renewal timer covers the new certificate.

## 6. Frontend on Vercel 🧑

1. Vercel → **Add New → Project** → import `Xdiad47/RepoPilot-AI`.
2. **Root Directory:** `frontend` (framework preset: Next.js is detected automatically).
3. **Environment Variables** (Production + Preview): `NEXT_PUBLIC_API_BASE_URL = https://repopilot-api.<your-domain>`.
   *Only public values belong here, never an API key.*
4. Deploy. Note the production URL (e.g. `https://repopilot-ai.vercel.app`).
5. Back on the VPS set `FRONTEND_ORIGIN=<that exact URL>` in `/etc/repopilot/backend.env` (comma-separate extra origins,
   e.g. a custom domain) and `systemctl restart repopilot-api`.

The frontend deploys independently of the backend: pushing to `main` redeploys Vercel, while the VPS is updated with
`install-backend.sh`.

## 7. Production smoke-test checklist

- [ ] `https://<api>/api/health` → `status: ok`, `llm.configured: true`; no secrets in the response.
- [ ] `http://<api>/api/health` redirects to HTTPS.
- [ ] Landing page shows **AI online** (and "Validation unavailable" while the sandbox is off).
- [ ] Browser console shows no CORS errors (if it does: `FRONTEND_ORIGIN` must equal the exact page origin, scheme included).
- [ ] An example investigation runs; the timeline updates live (the "Live" chip, not "Polling").
- [ ] Root Cause tab shows verified evidence; Code Changes shows a diff; Download .patch works.
- [ ] Test Results says **Validation unavailable** (sandbox off), not a fabricated pass.
- [ ] A bad URL (`https://gitlab.com/x/y`) shows a clear validation error; 6 quick submissions trigger the rate-limit message.
- [ ] Existing sites (`scanlyy.in`, `api.scanlyy.in`, …) still respond; `nginx -t` is clean.
- [ ] `systemctl status repopilot-api` is active; `journalctl -u repopilot-api -n 50` has no errors or secrets.

## 8. Operations

| Task | Command |
| --- | --- |
| Logs | `journalctl -u repopilot-api -f` |
| Status / restart | `systemctl status repopilot-api` · `systemctl restart repopilot-api` |
| Update backend | `bash /opt/repopilot/deploy/scripts/install-backend.sh` |
| Roll back backend | `bash /opt/repopilot/deploy/scripts/rollback.sh` |
| Roll back frontend | Vercel dashboard → Deployments → promote a previous one |
| Remove everything | `systemctl disable --now repopilot-api`, delete `/etc/systemd/system/repopilot-api.service`, `/etc/nginx/sites-{available,enabled}/repopilot-api.conf` (then `nginx -t && systemctl reload nginx`), `/opt/repopilot`, `/etc/repopilot`, `/var/lib/repopilot`, `userdel repopilot` |

## 9. Secrets

* The Groq key lives only in `/etc/repopilot/backend.env` (mode 640, root:repopilot) and your local `backend/.env`
  (gitignored). It is never in the repository, the frontend, or logs (a redaction filter masks it).
* **It expires on 2027-01-21** (created under the itzeazy Groq account). Regenerate it before then and update the file.
* A key that has been pasted into a chat or terminal transcript should be regarded as exposed: rotate it after the hackathon.
