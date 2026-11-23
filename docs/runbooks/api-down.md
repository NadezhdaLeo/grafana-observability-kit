# API down

**Fires when:** no production API instance answers its health check for 2 minutes.

**Severity:** critical, pages

## First five minutes

1. Check the deployment: are the instances running, are they restarting?
2. Check the last deploy. A bad release is the most common cause; roll it back first, investigate later.
3. Check `DbDown` and `DbConnectionsNearLimit`. An API that cannot reach its database fails its health check.

## If that did not help

- Scale the deployment up by one instance to get a fresh process while you read logs.
- Look at the load balancer: are health checks reaching the instances at all?

## After the incident

- Confirm the alert resolved on its own after the fix; if it needed a silence, note why.
- If this page was not actionable, open a change to the rule, not a silence.
