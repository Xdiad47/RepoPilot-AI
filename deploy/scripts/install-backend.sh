#!/usr/bin/env bash
# Install or update the RepoPilot AI backend on the VPS. Run as root ON THE VPS. Idempotent.
#
# It only creates/changes RepoPilot's own files:
#   /opt/repopilot, /etc/repopilot, /var/lib/repopilot, /etc/systemd/system/repopilot-api.service, user "repopilot".
# It never touches nginx, other systemd units, other users' directories, or existing sites.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Xdiad47/RepoPilot-AI.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/repopilot
ENV_DIR=/etc/repopilot
ENV_FILE="$ENV_DIR/backend.env"
STATE_DIR=/var/lib/repopilot
PORT=8200
UNIT=repopilot-api

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root."
command -v git >/dev/null || die "git is required."
command -v python3 >/dev/null || die "python3 is required."

# 1. Refuse to run if something else already owns the port.
if ss -ltn "sport = :$PORT" | grep -q LISTEN && ! systemctl is-active --quiet "$UNIT"; then
  die "Port $PORT is already in use by another process. Pick a free port (edit PORT here and in the systemd unit / nginx)."
fi

# 2. Service account and directories.
id repopilot >/dev/null 2>&1 || { say "Creating system user 'repopilot'"; useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin repopilot; }
install -d -m 755 "$APP_DIR"
install -d -m 750 -o root -g repopilot "$ENV_DIR"
install -d -m 750 -o repopilot -g repopilot "$STATE_DIR" "$STATE_DIR/data" "$STATE_DIR/workspaces"

# 3. Code. Remember the previous revision so rollback.sh can restore it.
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" rev-parse HEAD > "$STATE_DIR/previous_rev" 2>/dev/null || true
  say "Updating code"
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
else
  [[ -z "$(ls -A "$APP_DIR" 2>/dev/null)" ]] || die "$APP_DIR exists and is not empty or not a git checkout."
  say "Cloning $REPO_URL"
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
git -C "$APP_DIR" rev-parse HEAD > "$STATE_DIR/current_rev"

# 4. Python environment (isolated virtualenv inside the app directory).
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' 2>/dev/null; then
  say "Installing python3-venv (needed to create the virtualenv)"
  apt-get install -y python3-venv >/dev/null
fi
say "Installing Python dependencies"
python3 -m venv "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# 5. Environment file: created once from the template, never overwritten.
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 640 -o root -g repopilot "$APP_DIR/deploy/env/backend.env.production.example" "$ENV_FILE"
  say "Created $ENV_FILE from the template."
  die "Edit $ENV_FILE now (LLM_API_KEY, FRONTEND_ORIGIN), then run this script again. Nothing has been started."
fi
if grep -q '__PASTE_ON_THE_SERVER_ONLY__\|__YOUR_PROJECT__' "$ENV_FILE"; then
  die "$ENV_FILE still contains placeholder values. Edit it, then run this script again."
fi
chmod 640 "$ENV_FILE"; chown root:repopilot "$ENV_FILE"

# 6. systemd unit (our own file, so it is safe to refresh) and start.
install -m 644 "$APP_DIR/deploy/systemd/$UNIT.service" "/etc/systemd/system/$UNIT.service"
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null
systemctl restart "$UNIT"

# 7. Health check; on failure show logs and leave the previous revision restorable with rollback.sh.
say "Waiting for the service to become healthy"
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    say "Healthy: $(curl -fsS "http://127.0.0.1:$PORT/api/health" | head -c 200)"
    say "Done. Revision $(cut -c1-8 "$STATE_DIR/current_rev"). Next: deploy/scripts/install-nginx.sh <api-domain>"
    exit 0
  fi
  sleep 1
done
journalctl -u "$UNIT" -n 40 --no-pager || true
die "Service did not become healthy. To restore the previous revision run: deploy/scripts/rollback.sh"
