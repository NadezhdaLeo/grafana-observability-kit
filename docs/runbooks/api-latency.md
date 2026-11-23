# API latency

**Fires when:** p95 latency stays above 1 second for 10 minutes.

**Severity:** warning, chat

## First five minutes

1. Golden Signals dashboard: which route is slow? `/search` is usually the first to degrade.
2. Check `DbSlowQueries`: most API latency is database latency with extra steps.
3. Check CPU on the API instances; saturation shows as latency before it shows as errors.

## If that did not help

- Look at the latency heatmap for a bimodal pattern: a slow dependency produces a second band, not a shift.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
