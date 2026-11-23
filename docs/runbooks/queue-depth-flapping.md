# Queue depth (worked example of a flapping rule)

**Fires when:** queue depth exceeds 500 for 1 minute.

**Severity:** warning, chat

## First five minutes

This rule is the kit's deliberate bad example. Depth oscillates around 500 during normal
operation, and `for: 1m` turns every oscillation into a notification. The Alert Noise
dashboard shows it at the top of the Flapping table.

The fix is one of:

1. Lengthen the window: `for: 10m`. Cheapest, removes most of the noise.
2. Alert on the trend instead of the level: `predict_linear(queue_depth[15m], 600) > 2000`.
3. Delete it. `QueueOldestMessageTooOld` already covers the customer-visible symptom;
   depth is a diagnostic metric, not an alert condition.

## If that did not help

- Apply one of the fixes above and watch the Flapping panel for a day.

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
