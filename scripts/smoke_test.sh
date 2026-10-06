#!/usr/bin/env bash
# After a deploy: is the site up, is HTTPS working, and is the API healthy?
#   scripts/smoke_test.sh https://app.example.com
# Run it on the server to include the API's own health check (the API has no
# public port; it is checked inside its container).
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-}}"
if [[ -z "$BASE_URL" ]]; then
  echo "usage: smoke_test.sh <https://your-domain>" >&2
  exit 2
fi
[[ "$BASE_URL" =~ ^https?:// ]] || BASE_URL="https://$BASE_URL"
fail() { echo "✗ $1" >&2; exit 1; }

echo "→ home page"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/")
[[ "$code" == "200" ]] || fail "home page returned $code"
echo "  ok"

echo "→ app files (manifest, offline page)"
curl -fsS "$BASE_URL/manifest.webmanifest" | grep -q '"name"' || fail "no manifest"
curl -fsS -o /dev/null "$BASE_URL/offline.html" || fail "no offline page"
echo "  ok"

echo "→ security headers"
headers=$(curl -sSI "$BASE_URL/")
grep -qi "strict-transport-security" <<<"$headers" || fail "no HSTS header"
grep -qi "content-security-policy" <<<"$headers" || fail "no CSP header"
echo "  ok"

echo "→ webhooks reach the API (an unsigned call must be refused, not 404/502)"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/billing/webhook" -d '{}')
[[ "$code" == "401" ]] || fail "billing webhook returned $code (expected 401)"
echo "  ok"

if command -v docker >/dev/null && docker compose -f docker-compose.prod.yml ps api >/dev/null 2>&1; then
  echo "→ API health (inside its container)"
  docker compose -f docker-compose.prod.yml exec -T api curl -fsS http://localhost:8000/healthz >/dev/null \
    || fail "API /healthz failed"
  echo "  ok"
fi

echo "✓ smoke test passed"
