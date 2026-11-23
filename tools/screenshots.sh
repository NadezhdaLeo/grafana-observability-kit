#!/usr/bin/env bash
# Renders every provisioned dashboard to docs/screenshots/<uid>.png using the
# grafana-image-renderer container (docker compose profile "screenshots").
#
#   make screenshots
#   GRAFANA_URL=http://localhost:3000 GRAFANA_AUTH=admin:admin ./tools/screenshots.sh
#
# Let the stack run for at least an hour first (or use `make demo`), otherwise
# the alert-noise and on-call dashboards have nothing to show.

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_AUTH="${GRAFANA_AUTH:-admin:admin}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/docs/screenshots"
WIDTH="${WIDTH:-1600}"
HEIGHT="${HEIGHT:-1100}"
# Set FROM_OVERRIDE (e.g. now-45m) to render a shorter range than the per-dashboard default,
# useful when the stack has been running for less than a few hours.
FROM_OVERRIDE="${FROM_OVERRIDE:-}"

# uid:slug:from
DASHBOARDS=(
  "svc-overview:service-overview:now-6h"
  "golden-signals:golden-signals:now-6h"
  "alert-noise:alert-noise-overview:now-24h"
  "on-call-view:on-call-view:now-24h"
)

mkdir -p "$OUT"

echo "waiting for Grafana at $GRAFANA_URL ..."
for _ in $(seq 1 60); do
  if curl -fsS "$GRAFANA_URL/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "waiting for the renderer ..."
for _ in $(seq 1 60); do
  if curl -fsS -u "$GRAFANA_AUTH" "$GRAFANA_URL/render/d-solo/svc-overview/x?panelId=1&width=10&height=10" -o /dev/null 2>/dev/null; then break; fi
  sleep 2
done

for entry in "${DASHBOARDS[@]}"; do
  IFS=: read -r uid slug from <<<"$entry"
  [ -n "$FROM_OVERRIDE" ] && from="$FROM_OVERRIDE"
  url="$GRAFANA_URL/render/d/$uid/$slug?orgId=1&from=$from&to=now&width=$WIDTH&height=$HEIGHT&kiosk&tz=UTC&theme=dark"
  echo "rendering $uid -> docs/screenshots/$uid.png"
  curl -fsS -u "$GRAFANA_AUTH" "$url" -o "$OUT/$uid.png"
done

echo "done: $(ls "$OUT"/*.png | wc -l) screenshots in $OUT"
