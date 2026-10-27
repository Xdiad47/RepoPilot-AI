#!/usr/bin/env bash
# Add a SEPARATE nginx server block for the RepoPilot API. Run as root ON THE VPS.
# Usage: install-nginx.sh <api-domain> [--force]
# Existing sites are never modified. If nginx rejects the result, the new files are removed again.
set -euo pipefail

DOMAIN="${1:-}"; FORCE="${2:-}"
PORT=8200
AVAILABLE=/etc/nginx/sites-available/repopilot-api.conf
ENABLED=/etc/nginx/sites-enabled/repopilot-api.conf
TEMPLATE="$(cd "$(dirname "$0")/.." && pwd)/nginx/repopilot-api.conf.template"

die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Run as root."
[[ -n "$DOMAIN" ]] || die "Usage: $0 <api-domain>   e.g. repopilot-api.example.com"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] || die "'$DOMAIN' is not a valid hostname."
[[ -f "$TEMPLATE" ]] || die "Template not found: $TEMPLATE"

# Never shadow a domain that another site already serves.
if grep -rqsE "server_name[^;]*[[:space:]]$DOMAIN[[:space:];]" /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null \
   && [[ ! -e "$ENABLED" ]]; then
  die "$DOMAIN is already used by another nginx site. Choose a different subdomain."
fi
if [[ -e "$AVAILABLE" && "$FORCE" != "--force" ]]; then
  die "$AVAILABLE already exists. Re-run with --force to replace RepoPilot's own file."
fi

nginx -t >/dev/null 2>&1 || die "The current nginx configuration is already invalid; fix it first (nginx -t)."

sed -e "s/__API_DOMAIN__/$DOMAIN/g" -e "s/__UPSTREAM_PORT__/$PORT/g" "$TEMPLATE" > "$AVAILABLE"
ln -sf "$AVAILABLE" "$ENABLED"

if ! nginx -t; then
  rm -f "$ENABLED" "$AVAILABLE"
  die "nginx rejected the new configuration; it has been removed again. Nothing was reloaded."
fi
systemctl reload nginx
echo "==> nginx now proxies http://$DOMAIN -> 127.0.0.1:$PORT"
echo
echo "Next steps:"
echo "  1. Make sure the DNS A record for $DOMAIN points to this server's IPv4 address."
echo "  2. Check:  getent hosts $DOMAIN"
echo "  3. HTTPS:  certbot --nginx -d $DOMAIN --redirect"
echo "  4. Verify: curl -fsS https://$DOMAIN/api/health"
