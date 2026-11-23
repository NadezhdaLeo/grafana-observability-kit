# Database disk

**Fires when:** the data volume is above 90%, or predicted to be full within 7 days.

**Severity:** critical (90%) pages; predictive tier is warning

## First five minutes

1. Find what grew: table sizes, WAL, old backups on the same volume.
2. Free the obvious: rotated logs, old backups, dropped tables not yet vacuumed.
3. Extend the volume if the growth is legitimate.

## If that did not help

- Set a retention policy so this does not page again next month.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
