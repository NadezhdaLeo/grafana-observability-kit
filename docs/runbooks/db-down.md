# Primary database down

**Fires when:** the primary instance fails its health check for 1 minute.

**Severity:** critical, pages

## First five minutes

1. Is the process running? Restart it if it is not, before anything else.
2. Check disk: a full data volume stops the database. See `DbDiskNearlyFull`.
3. Check `DbReplicationLagHigh` on the replica before considering a failover; a lagging replica loses writes.

## If that did not help

- Fail over to the replica only if the primary cannot be brought back within the SLO window.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
