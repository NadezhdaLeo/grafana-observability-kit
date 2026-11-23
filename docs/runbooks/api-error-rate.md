# API error rate

**Fires when:** the share of 5xx responses exceeds the threshold for the rule's window.

**Severity:** critical (5% or budget burn) pages; warning (1%) does not

## First five minutes

1. Open the Golden Signals dashboard for `api`. Is the error rate on one route or all of them?
2. One route: a code path or a dependency. All routes: the database, or the instance itself.
3. Compare with `DbSlowQueries` and `DbConnectionsNearLimit`.

## If that did not help

- Check recent deploys and feature flags.
- Sample the error responses; the body usually names the failing dependency.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
