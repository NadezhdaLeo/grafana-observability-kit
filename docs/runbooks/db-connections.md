# Database connections

**Fires when:** the primary uses more than 90% of its connection limit.

**Severity:** critical, pages (75% tier is warning)

## First five minutes

1. List connections by client. One client holding most of them is a leaking pool.
2. Restart that client; connections drop immediately.
3. Only then consider raising the limit. Raising it first hides the leak.

## If that did not help

- Check for long-running transactions holding connections open.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
