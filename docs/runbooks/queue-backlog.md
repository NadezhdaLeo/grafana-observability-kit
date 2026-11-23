# Queue backlog

**Fires when:** the oldest message has waited more than 5 minutes.

**Severity:** critical, pages

## First five minutes

1. Compare consume rate to publish rate on the Service Overview dashboard.
2. Check `WorkerCrashLooping` and `QueueConsumersLow`: a backlog with fewer consumers is a worker problem.
3. If consumers are healthy but slow, check the database.

## If that did not help

- Scale workers up temporarily to drain; fix the cause afterwards.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
