#!/usr/bin/env bash
# Restore the previous RepoPilot AI backend revision (saved by install-backend.sh). Run as root ON THE VPS.
set -euo pipefail
APP_DIR=/opt/repopilot; STATE_DIR=/var/lib/repopilot; UNIT=repopilot-api; PORT=8200
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ -s "$STATE_DIR/previous_rev" ]] || { echo "No previous revision recorded." >&2; exit 1; }
PREV="$(cat "$STATE_DIR/previous_rev")"
echo "==> Rolling back to $PREV"
git -C "$APP_DIR" reset --hard --quiet "$PREV"
"$APP_DIR/backend/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"
echo "$PREV" > "$STATE_DIR/current_rev"
systemctl restart "$UNIT"
for _ in $(seq 1 20); do
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && { echo "==> Healthy on $PREV"; exit 0; }
  sleep 1
done
journalctl -u "$UNIT" -n 40 --no-pager || true
echo "Rollback did not become healthy." >&2; exit 1
