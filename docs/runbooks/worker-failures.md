# Worker job failures

**Fires when:** more than 10% of jobs fail, or p95 job duration exceeds 20 seconds.

**Severity:** warning, chat

## First five minutes

1. Which job type fails? Group the failures by type before anything else.
2. Check the database and any upstream API the jobs call.
3. Retries are not failures: a high retry rate with a low failure rate is a dependency hiccup.

## If that did not help

- Replay a failed job by hand with debug logging.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
