# Scrape target down

**Fires when:** a scrape target reports up == 0 for 3 minutes, or a rule group fails to evaluate.

**Severity:** warning, chat

## First five minutes

1. Can Prometheus reach the target? Check network and the target's /metrics endpoint.
2. For rule evaluation failures: open the rule in the Prometheus UI; the error message names the expression.

## If that did not help

- Every alert that depends on the missing target is blind until this is fixed.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
