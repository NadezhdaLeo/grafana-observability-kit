# Worker crash loop

**Fires when:** a production worker restarted more than 3 times in 15 minutes.

**Severity:** critical, pages

## First five minutes

1. Read the last lines of the worker log before each exit. Crash loops repeat the same error.
2. Check memory: an OOM-killed worker shows as a restart, not as an error.
3. Check the queue: `QueueOldestMessageTooOld` tells you how long you have.

## If that did not help

- Scale the remaining healthy worker up to keep the queue draining while you debug.
- If one specific job type crashes the worker, move it to a dead-letter queue.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
