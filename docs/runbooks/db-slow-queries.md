# Slow database queries

**Fires when:** p95 SELECT latency exceeds 50ms for 10 minutes.

**Severity:** warning, chat

## First five minutes

1. Check for a long-running transaction or a lock.
2. Check whether a new query shape appeared with the last deploy; a missing index shows up here first.
3. Check disk I/O on the host.

## If that did not help

- Run the slow query log for the window and look at the top three by total time.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
