#!/usr/bin/env bash
# Leak check: nothing from _private/ (company exports used as reference) may
# appear in the public tree.
#
# Builds a token list from everything under _private/ -- hostnames, URLs, UIDs,
# dashboard/panel titles, alert names, label values, chat channel names,
# CamelCase identifiers -- then greps the rest of the repository for them.
#
#   ./tools/check_leaks.sh              # exit 1 on any hit
#   ./tools/check_leaks.sh --tokens     # print the token list and exit
#   EXTRA_TOKENS=/path/to/list ./tools/check_leaks.sh   # add tokens not derivable from files
#
# The script never prints the private tokens except with --tokens, and never
# writes them anywhere inside the repository.

set -euo pipefail
cd "$(dirname "$0")/.."

PRIV="_private"
if [ ! -d "$PRIV" ] || [ -z "$(ls -A "$PRIV" 2>/dev/null)" ]; then
  echo "check_leaks: $PRIV/ is empty or missing, nothing to compare against"
  exit 0
fi

TOKENS="$(mktemp)"
trap 'rm -f "$TOKENS"' EXIT

# Generic words that legitimately occur in both trees. Keep this list short and
# boring: every entry here is a word the check will NOT flag.
STOP='^(on-call|oncall|Alert|Team|Series|Rule|Owner|Service|Firings|Value|alertname|alertstate|firing|pending|severity|critical|warning|notice|info|team|component|namespace|service|instance|environment|production|staging|development|prometheus|grafana|alertmanager|kubernetes|cluster|dashboard|dashboards|datasource|timeseries|table|stat|bargauge|gauge|text|row|markdown|percentunit|short|time|value|values|options|defaults|overrides|matcher|properties|custom|color|mode|fixed|thresholds|absolute|steps|green|yellow|red|orange|blue|purple|text|auto|none|list|bottom|single|multi|desc|asc|range|instant|table|heatmap|code|builder|query|queries|legend|format|type|kind|spec|panel|panels|layout|items|element|width|height|title|description|links|tags|version|refresh|hidden|editable|annotations|templating|templates|browser|default|current|query|all|__all|__auto|__range|__interval|__range_s|sph|owner|page|true|false|null|runbook|summary|repo|labels|annotations|groups|rules|alert|expr|for|changes|count|count_over_time|min_over_time|max_over_time|sum|topk|bottomk|vector|changes|rate|increase|histogram_quantile|label_values|ALERTS|ALERTS_FOR_STATE|localhost|example|monitoring|metrics|alerts|silences|routing|readiness|paging|noise|control|overview|signals|golden|health|volume|trend|hygiene|flapping|cardinality|always|detail|dump|full|currently|samples|hour|hours|day|days|week|per|by|total|mean|max|min|last|first|none|ok|no|not|and|or|the|of|to|in|is|it|a|an|at|as|be|this|that|with|from|for|on|and|are|was|were|has|have|had|will|would|should|can|could|than|then|when|where|which|who|what|why|how|all|any|each|every|some|such|only|same|other|more|most|less|least|very|also|just|still|even|both|either|neither|between|over|under|above|below|after|before|during|while|until|since|about|against|without|within|across|through|into|onto|upon|out|off|up|down|back|again|once|twice|new|old|high|low|long|short|big|small|good|bad|best|worst|better|worse|same|different|left|right|top|middle|center|front|end|start|stop|open|close|closed|read|write|run|running|stopped|failed|failing|success|error|errors|warning|warnings|api|apis|worker|workers|db|queue|queues|pod|pods|container|containers|deployment|deployments|job|jobs|host|hosts|node|nodes|app)$'

# 1. Hostnames and domains (anything with a dot and a TLD-looking suffix)
grep -rhoE '\b[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+\.[A-Za-z]{2,}\b' "$PRIV" 2>/dev/null \
  | grep -vE '^[0-9.]+$' >> "$TOKENS" || true

# 2. Quoted identifier values in JSON/YAML: uids, names, label values, variable definitions.
#    Free-text titles are deliberately NOT tokens: "Total firings" is a phrase, not a secret.
grep -rhoE '"(uid|name|alertname|team|component|namespace|service|owner|definition|allValue)"[[:space:]]*:[[:space:]]*"[^"]{4,}"' "$PRIV" 2>/dev/null \
  | sed -E 's/^"[^"]+"[[:space:]]*:[[:space:]]*"//; s/"$//' >> "$TOKENS" || true

# 3. Label values inside PromQL selectors:  key="v1|v2"  key=~"v1|v2"
grep -rhoE '[a-zA-Z_]+[!]?=~?\\?"[^"\\]{3,}\\?"' "$PRIV" 2>/dev/null \
  | sed -E 's/^[a-zA-Z_]+[!]?=~?\\?"//; s/\\?"$//' | tr '|' '\n' >> "$TOKENS" || true

# 4. Chat channel names and @handles
grep -rhoE '#[a-z0-9][a-z0-9_-]{3,}' "$PRIV" 2>/dev/null | sed 's/^#//' >> "$TOKENS" || true

# 5. CamelCase identifiers (alert names like FooBarBaz) and ALLCAPS-with-brackets prefixes
grep -rhoE '\b[A-Z][a-z]+([A-Z][A-Za-z0-9]+){1,}\b' "$PRIV" 2>/dev/null >> "$TOKENS" || true
grep -rhoE '\[[A-Z][A-Z -]{3,}\][A-Za-z0-9 .-]{3,40}' "$PRIV" 2>/dev/null | sed -E 's/[[:space:]]+$//' >> "$TOKENS" || true

# 6. Hyphenated identifiers (service names like foo-bar-api, pod names)
grep -rhoE '\b[a-z0-9]+(-[a-z0-9]+){1,}\b' "$PRIV" 2>/dev/null >> "$TOKENS" || true

# 7. Opaque IDs: 8+ chars of mixed letters/digits that look like UIDs
grep -rhoE '\b[a-zA-Z0-9]{8,}\b' "$PRIV" 2>/dev/null | grep -E '[0-9]' | grep -E '[a-zA-Z]' >> "$TOKENS" || true

# Normalise: trim, drop short/generic/numeric tokens, dedupe
sed -E 's/^[[:space:]]+|[[:space:]]+$//g' "$TOKENS" \
  | awk 'length($0) >= 4' \
  | grep -vE '^[0-9. ]+$' \
  | grep -vE "$STOP" \
  | grep -vE '^(now-[0-9]+[hdm]|[0-9]+[smhd]|__[a-z_]+|[a-z_]+\.[a-z_]+)$' \
  | grep -vE '^(semi-dark|super-light|dark|light)-(red|green|blue|orange|purple|yellow)$' \
  | grep -vE '^(time_series|color-background|color-text|byName|byRegexp|lastNotNull|palette-classic|continuous-[A-Za-z]+|rgba)$' \
  | grep -vE '^(panel-[0-9]+|[A-Z][A-Za-z]+(Query|Variable|Layout|LayoutItem|Config|Reference|Group|Rule)|Annotations & Alerts|-- Grafana --|dashboard\.grafana\.app|PromQL|Prometheus|BlPu|[0-9]+-hour|\$\{?[A-Za-z_]+\}?)$' \
  | grep -vE '^(as-is|to-be|in-hours|non-stop|catch-all|crash-loop|alert-hours|noise-reduction|on-call-notifications)$' \
  | sort -u > "$TOKENS.clean"
mv "$TOKENS.clean" "$TOKENS"

if [ -n "${EXTRA_TOKENS:-}" ] && [ -f "$EXTRA_TOKENS" ]; then
  grep -vE '^\s*(#|$)' "$EXTRA_TOKENS" >> "$TOKENS"
  sort -u -o "$TOKENS" "$TOKENS"
fi

if [ "${1:-}" = "--tokens" ]; then
  cat "$TOKENS"
  echo "---- $(wc -l < "$TOKENS") tokens"
  exit 0
fi

HITS="$(grep -rIFn --color=never -f "$TOKENS" \
  --exclude-dir="$PRIV" --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=docs/screenshots \
  --exclude=check_leaks.sh . || true)"

if [ -n "$HITS" ]; then
  echo "check_leaks: FOUND private tokens in the public tree:"
  echo "$HITS" | while IFS= read -r line; do
    file="${line%%:*}"; rest="${line#*:}"; lineno="${rest%%:*}"; content="${rest#*:}"
    hit="$(printf '%s\n' "$content" | grep -oF -f "$TOKENS" | head -1)"
    printf '  %s:%s  token=%q\n' "$file" "$lineno" "$hit"
  done
  exit 1
fi

echo "check_leaks: clean ($(wc -l < "$TOKENS") private tokens checked against the public tree)"
