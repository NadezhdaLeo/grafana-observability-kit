# Replication lag

**Fires when:** the replica is more than 30s (warning) or 90s (critical) behind.

**Severity:** see rule

## First five minutes

1. Is the replica under heavy read load? Lag follows read saturation.
2. Is there a long transaction on the primary? Replication waits for it.
3. Check network between the two instances.

## If that did not help

- Do not fail over while lag is high; you would lose the unreplicated writes.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
