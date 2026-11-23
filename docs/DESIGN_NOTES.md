# Design notes

Why the dashboards and rules look the way they do. Every point here came out of
running a real alerting stack and being surprised by it; the kit reproduces each
surprise so it can be seen, not just read about.

## 1. Severity is a reaction, not an importance

Three values, each attached to exactly one kind of attention:

| severity   | reaction                              | delivery                          |
|------------|---------------------------------------|-----------------------------------|
| `critical` | a human acts now, day or night        | pager                             |
| `warning`  | the owning team looks next working hour | team chat                       |
| `info`     | nobody is interrupted; it is a fact   | weekly report, never a channel    |

The temptation is to add tiers (`urgent`, `high`, `medium`, `notice`). Every extra
tier creates a boundary dispute and, in practice, a value that routes nowhere. The
kit's `Severity values in use` panel exists because real stacks accumulate typo
severities that nobody notices until a rule silently stops reaching anyone.

## 2. `page` is separate from `severity`, on purpose

`page: "true"` is the decision to interrupt a person. It almost always coincides
with `critical`, and the meta rule `CriticalAlertNotPaging` lists the cases where it
does not, as a backlog to work through.

Two reasons to keep them apart:

- Non-production can have `critical` conditions that must never page. The pager
  route in `alertmanager.yml` requires `environment="production"` in addition to
  `page="true"`. That is defence in depth: a rule mislabelled on staging does not
  wake anyone, and `PagingAlertOnNonProd` reports the mislabelling.
- Migrations. When a stack moves from one routing convention to another, `page`
  is the transitional key while `severity` is cleaned up. The On-call View shows
  both numbers side by side ("Pages delivered per day" vs. "Severity model:
  critical per day"); the gap is the work remaining before routing can move to
  severity alone.

The kit itself caught a bug this way during development: `WatchdogNotReceived`
was `critical` + `page="true"` but carried no `environment` label, so the pager
route would have dropped it. `PagingAlertOnNonProd` flagged it within a minute.

## 3. Count episodes, not samples

`count_over_time(ALERTS[30d])` is the first thing everyone writes to measure alert
volume. It counts *stored samples*: an alert that fires once and stays active for a
day contributes 5 760 at a 15-second evaluation interval. Two rules that never
resolve will sit at the top of that list forever and tell you nothing.

The kit uses two units and labels them explicitly:

- **Firings (episodes)**: how many times a rule entered the firing state.
  `changes(ALERTS_FOR_STATE[range])` plus one for every series that first appeared
  inside the range. The second term matters: without it, rules with per-instance
  labels (a new pod, a new host) are undercounted by about half, because the first
  activation of a new series is not a "change".
- **Alert-hours**: time spent firing, summed across all series of a rule. Sample
  count divided by samples-per-hour (`$sph`, a hidden dashboard variable tied to
  the evaluation interval).

The two lists rarely overlap. "Fires often" and "stays on" are different diseases
with different cures.

## 4. Four kinds of noise, four panels

| Panel                    | What it finds                                     | Fix                                      |
|--------------------------|---------------------------------------------------|------------------------------------------|
| Top rules by firings     | starts too often                                  | longer `for:`, wider threshold, rate-based condition |
| Top rules by alert-hours | stays on too long                                 | repair the cause, or stop calling it an alert |
| Flapping                 | minutes per episode under 5                       | longer `for:`                            |
| Always firing            | share of range near 100%                          | delete, or make it `info`                |
| Cardinality              | many series, few episodes                         | Alertmanager `group_by`, not the rule    |

`QueueDepthHigh` is left with `for: 1m` on a metric that oscillates around its
threshold. It is the planted example: it should appear at the top of the Flapping
panel within an hour of starting the stack. The runbook describes three fixes.

`DeprecatedRuntimeInUse` is the planted example for the other end: a condition that
is true for weeks. As `info` it goes into a report; as `warning` it would be a
permanent chat message nobody reads.

## 5. Alert on symptoms, count events for crash loops

`QueueOldestMessageTooOld` pages; `QueueDepthHigh` does not. Customers feel the
age of the oldest message, not the depth.

`WorkerCrashLooping` counts restarts (`increase(worker_restarts_total[15m]) > 3`)
instead of watching `app_up`. A crash loop is up again 20 seconds after it dies;
an `app_up == 0 for 5m` rule never fires on it. The generator's `worker_crashloop`
scenario demonstrates this: `WorkerInstanceDown` stays pending while
`WorkerCrashLooping` fires.

## 6. Group by what a human would fix

`group_by: [alertname, service, environment]`. Grouping on `alertname` alone
means that while one service's crash loop is open, a second service's identical
symptom merges into the same notification and nobody is told.

## 7. Verify delivery, not just evaluation

Prometheus knows what fired. It does not know what Alertmanager sent, or where.
The kit's webhook sink counts deliveries per receiver, and the On-call View shows
"Pages delivered per day" next to "Page-worthy episodes per day". The gap is
grouping and inhibition doing their job. `critical` is delivered to both the pager
and the team's chat on purpose (`continue: true` on the pager route); a
`page="true"` alert that never reaches the pager receiver is a routing bug visible
on the dashboard rather than discovered during an outage.

## 8. The heartbeat is the only alert that matters when everything else is quiet

`Watchdog` fires forever and is routed to a heartbeat receiver. The absence of the
heartbeat is the signal that the pipeline is broken. In the kit the check lives in
the metrics generator for demonstration; in production it must run outside the
monitored Prometheus and Alertmanager, otherwise it dies with them.

A single Alertmanager instance is a single point of failure. The kit runs one on
purpose (`--cluster.listen-address=`) and shows the heartbeat age on the On-call
View as the compensating control.

## 9. Trading hours on the on-call page

For IT support in a trading firm, "is the market open" changes what an alert means.
The same API outage at 09:31 New York time and at 03:00 is a different incident.
The On-call View shows four exchange clocks, a session timeline from the
`market_session_open` metric, and the time to the next open or close, so the
on-call engineer reads the paging timeline against the sessions without doing the
timezone arithmetic in their head.

The session metric is computed from weekday session hours only; there is no
holiday calendar. That is documented on the panel, because a confident wrong
"OPEN" is worse than no indicator.

## 10. On-call budget as a rule

`PagingBudgetExceeded` fires when the pager receiver got more than 6 notifications
in 24 hours. Google's SRE guidance is at most two incidents per 12-hour shift; the
kit's threshold is deliberately a little above that so the rule points at a trend,
not at one bad night. The number is a starting point, not an agreed target; the
right value is whatever the team decides it can investigate properly.
