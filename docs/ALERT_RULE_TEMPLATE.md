# Alert rule template

Every rule in `prometheus/rules/` follows this shape. The labels are what Alertmanager
routes on; the annotations are what the responder reads at 3 a.m.

```yaml
- alert: ServiceSymptom            # CamelCase, service first, symptom second
  expr: |
    <PromQL that is true while the condition holds>
  for: 5m                           # long enough that a single bad scrape cannot fire it
  labels:
    owner: web                      # the team that fixes it: web | jobs | storage | sre
    severity: critical              # critical | warning | info
    page: "true"                    # "true" only when a human must act now
    service: api                    # omit when the metric already carries it
    alertname_family: api_errors    # optional: ties the critical and warning tiers together
  annotations:
    summary: "One line: what is wrong, with the number"
    description: >-
      What the number means and the first thing to check. Two or three sentences.
    runbook_url: https://example.org/runbooks/service-symptom
```

## Severity means a reaction, not an importance

| severity   | page    | Who sees it                      | When                          | Example                         |
|------------|---------|----------------------------------|-------------------------------|---------------------------------|
| `critical` | `true`  | On-call engineer, by pager       | Now, day or night             | `ApiDown`, `DbConnectionsNearLimit` |
| `warning`  | `false` | Owning team, in chat             | Next working hour             | `ApiHighLatency`, `DbSlowQueries`   |
| `info`     | `false` | Nobody directly; weekly report   | When someone reads the report | `DeprecatedRuntimeInUse`        |

`critical` without `page: "true"` is a contradiction. The `CriticalAlertNotPaging` meta
rule lists every such case as a cleanup backlog.

## Why `page` exists separately from `severity`

Severity describes the condition. `page` describes the decision to interrupt a person.
They usually agree, but two cases need them apart:

- A non-production environment can have a `critical` condition that must never page.
  The Alertmanager pager route requires `environment="production"` on top of
  `page="true"`, and `PagingAlertOnNonProd` flags any rule that gets this wrong.
- During a migration from one routing scheme to another, `page` is the transitional key
  while `severity` is cleaned up. Once every `critical` pages and nothing else does,
  the `page` label can be dropped and routing moves to severity alone.

## Rules of thumb

- **Alert on symptoms, not causes.** `QueueOldestMessageTooOld` pages; `QueueDepthHigh`
  does not. Customers feel the age, not the depth.
- **`for:` is not optional.** A rule with `for: 1m` on a metric that oscillates around
  its threshold flaps. `QueueDepthHigh` is left that way on purpose as the worked
  example; the Alert Noise dashboard catches it.
- **Count events for crash loops.** `WorkerCrashLooping` counts restarts. An
  `instance == 0 for 5m` rule never fires on a process that is back within 30 seconds.
- **Two tiers, one family.** When a condition has a warning and a critical threshold,
  give both the same `alertname_family` so the critical inhibits the warning.
- **Non-prod is visible, never paging.** Same symptoms, lower tier, own rule.
- **Always firing is a report.** A condition that holds for weeks (`DeprecatedRuntimeInUse`)
  carries no information as an alert. Make it `info` or delete it.
