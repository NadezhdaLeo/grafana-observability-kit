# Watchdog

**Fires when:** the always-firing heartbeat stops arriving for 5 minutes.

**Severity:** critical, pages

## First five minutes

1. Is Alertmanager running? Is Prometheus running? Check both before anything else.
2. Is the Alertmanager webhook receiver reachable from Alertmanager?
3. Check Alertmanager's own logs for delivery errors.

## If that did not help

- In production this check must run outside the monitored stack (a hosted dead-man's-switch). If it runs inside, it dies with the thing it watches.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
