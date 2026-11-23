# Alert hygiene

**Fires when:** a rule fires without an owner, is critical without paging, pages on non-prod, flaps, or the daily paging budget is exceeded.

**Severity:** info or warning, never pages

## First five minutes

These are not incidents. They are rule defects surfaced as alerts so they get fixed.

1. `AlertWithoutOwner`: add the `owner` label.
2. `CriticalAlertNotPaging`: decide whether it should page; set `page` or lower the severity.
3. `PagingAlertOnNonProd`: scope the rule to production or set `page: "false"`.
4. `AlertFlapping`: lengthen `for:` (see queue-depth-flapping).
5. `PagingBudgetExceeded`: review the top paging rules on the On-call dashboard this week.

## If that did not help

- Review these once a week in the on-call handover; they should trend to zero.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
