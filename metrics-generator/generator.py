"""
Synthetic application fleet for the observability kit.

Exposes Prometheus metrics for four simulated services (api, worker, db, queue)
with a scenario engine that injects realistic trouble: error bursts, latency
spikes, outages, connection exhaustion, queue backlogs, crash loops and a
deliberately flapping signal. Also exposes market-session metrics for the
trading-hours widget and accepts Alertmanager webhooks on /alerts so that what
Alertmanager actually delivered can be graphed.

Endpoints
  GET  /metrics   Prometheus exposition
  POST /alerts    Alertmanager webhook sink (?receiver=<name>)
  GET  /healthz
"""

import json
import math
import os
import random
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

SPEED = float(os.environ.get("SCENARIO_SPEED", "1.0"))
PORT = int(os.environ.get("LISTEN_PORT", "8000"))
TICK = 1.0  # seconds between simulation steps

# ----------------------------------------------------------------------------
# Fleet layout
# ----------------------------------------------------------------------------

INSTANCES = [
    # service, instance, environment
    ("api", "api-0", "production"),
    ("api", "api-1", "production"),
    ("api", "api-stg-0", "staging"),
    ("worker", "worker-0", "production"),
    ("worker", "worker-1", "production"),
    ("db", "db-primary", "production"),
    ("db", "db-replica", "production"),
    ("queue", "queue-0", "production"),
]
ROUTES = ["/orders", "/users", "/search", "/health"]
QUEUES = ["orders", "notifications"]

# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------

app_up = Gauge("app_up", "1 if the instance answers its health check", ["service", "instance", "environment"])
build_info = Gauge("app_build_info", "Build metadata", ["service", "instance", "environment", "version"])

http_requests = Counter(
    "http_requests_total", "HTTP requests", ["service", "instance", "environment", "route", "method", "status"]
)
http_latency = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "instance", "environment", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

worker_jobs = Counter("worker_jobs_total", "Jobs processed", ["instance", "environment", "result"])
worker_job_latency = Histogram(
    "worker_job_duration_seconds",
    "Job duration",
    ["instance", "environment"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)
worker_restarts = Counter("worker_restarts_total", "Process restarts", ["instance", "environment"])

queue_depth = Gauge("queue_depth", "Messages waiting", ["queue", "environment"])
queue_oldest_age = Gauge("queue_oldest_message_age_seconds", "Age of the oldest waiting message", ["queue", "environment"])
queue_consumers = Gauge("queue_consumers", "Active consumers", ["queue", "environment"])
queue_published = Counter("queue_messages_published_total", "Messages published", ["queue", "environment"])
queue_consumed = Counter("queue_messages_consumed_total", "Messages consumed", ["queue", "environment"])

db_conn_active = Gauge("db_connections_active", "Open connections", ["instance", "environment"])
db_conn_max = Gauge("db_connections_max", "Connection limit", ["instance", "environment"])
db_query_latency = Histogram(
    "db_query_duration_seconds",
    "Query latency",
    ["instance", "environment", "op"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
db_replication_lag = Gauge("db_replication_lag_seconds", "Replica lag", ["instance", "environment"])
db_disk_used = Gauge("db_disk_used_ratio", "Data volume usage 0..1", ["instance", "environment"])

proc_cpu = Gauge("process_cpu_ratio", "CPU usage 0..1 of one core", ["service", "instance", "environment"])
proc_mem = Gauge("process_memory_bytes", "Resident memory", ["service", "instance", "environment"])
proc_mem_limit = Gauge("process_memory_limit_bytes", "Memory limit", ["service", "instance", "environment"])

market_open = Gauge("market_session_open", "1 while the exchange is in a trading session", ["exchange", "timezone"])
market_next = Gauge("market_seconds_to_next_event", "Seconds until the session opens (if closed) or closes (if open)", ["exchange"])
local_hour = Gauge("local_hour", "Hour of day in the given timezone", ["timezone"])
local_minute = Gauge("local_minute", "Minute of hour in the given timezone", ["timezone"])

webhook_received = Counter(
    "alertmanager_webhook_notifications_total",
    "Notifications delivered by Alertmanager to this sink",
    ["receiver", "status", "alertname", "severity"],
)
watchdog_last = Gauge("watchdog_last_received_timestamp_seconds", "Last time the Watchdog heartbeat arrived")
scenario_active = Gauge("scenario_active", "1 while a fault-injection scenario is running", ["scenario"])

# ----------------------------------------------------------------------------
# Trading sessions (no holiday calendar; documented limitation)
# ----------------------------------------------------------------------------

EXCHANGES = {
    # exchange: (timezone, [(open_hhmm, close_hhmm), ...])
    "XNYS": ("America/New_York", [("09:30", "16:00")]),
    "XLON": ("Europe/London", [("08:00", "16:30")]),
    "XETR": ("Europe/Berlin", [("09:00", "17:30")]),
    "XTKS": ("Asia/Tokyo", [("09:00", "11:30"), ("12:30", "15:00")]),
}


def _hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def update_market_metrics(now_utc):
    for ex, (tz, sessions) in EXCHANGES.items():
        local = now_utc.astimezone(ZoneInfo(tz))
        local_hour.labels(tz).set(local.hour)
        local_minute.labels(tz).set(local.minute)
        is_open = False
        next_event = None
        if local.weekday() < 5:
            for o, c in sessions:
                oh, om = _hm(o)
                ch, cm = _hm(c)
                open_dt = local.replace(hour=oh, minute=om, second=0, microsecond=0)
                close_dt = local.replace(hour=ch, minute=cm, second=0, microsecond=0)
                if open_dt <= local < close_dt:
                    is_open = True
                    next_event = close_dt
                    break
                if local < open_dt and (next_event is None or open_dt < next_event):
                    next_event = open_dt
        if next_event is None:
            # next weekday's first open
            d = local
            for _ in range(7):
                d = (d + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                if d.weekday() < 5:
                    oh, om = _hm(sessions[0][0])
                    next_event = d.replace(hour=oh, minute=om)
                    break
        market_open.labels(ex, tz).set(1 if is_open else 0)
        market_next.labels(ex).set(max(0, (next_event - local).total_seconds()))


# ----------------------------------------------------------------------------
# Scenario engine
# ----------------------------------------------------------------------------


class Scenario:
    def __init__(self, name, mean_gap_min, duration_sec):
        self.name = name
        self.mean_gap = mean_gap_min * 60 / SPEED
        self.duration = duration_sec  # (min_seconds, max_seconds)
        self.until = 0.0
        self.was_active = False
        self.next_at = time.time() + random.uniform(0.2, 1.0) * self.mean_gap
        scenario_active.labels(name).set(0)

    @property
    def active(self):
        return time.time() < self.until

    def maybe_start(self):
        now = time.time()
        if not self.active and now >= self.next_at:
            lo, hi = self.duration
            self.until = now + random.uniform(lo, hi)
            self.next_at = self.until + random.expovariate(1 / self.mean_gap)
            self.was_active = True
            scenario_active.labels(self.name).set(1)
            print(f"[scenario] start {self.name} for {int(self.until - now)}s", flush=True)
        elif not self.active and self.was_active:
            self.was_active = False
            scenario_active.labels(self.name).set(0)
            print(f"[scenario] end {self.name}", flush=True)


SCENARIOS = {
    # name: mean gap between occurrences (minutes, divided by SCENARIO_SPEED), duration range (seconds).
    # Durations are longer than the matching rules' `for:` clauses so every rule can be seen firing.
    "api_error_burst": Scenario("api_error_burst", 25, (6 * 60, 12 * 60)),
    "api_latency_spike": Scenario("api_latency_spike", 35, (12 * 60, 18 * 60)),
    "api_down": Scenario("api_down", 70, (4 * 60, 7 * 60)),
    "db_slow": Scenario("db_slow", 45, (12 * 60, 18 * 60)),
    "db_connections": Scenario("db_connections", 60, (7 * 60, 10 * 60)),
    "replication_lag": Scenario("replication_lag", 50, (7 * 60, 11 * 60)),
    "queue_backlog": Scenario("queue_backlog", 40, (10 * 60, 14 * 60)),
    "queue_flap": Scenario("queue_flap", 55, (15 * 60, 25 * 60)),
    "worker_crashloop": Scenario("worker_crashloop", 65, (9 * 60, 13 * 60)),
    "staging_chaos": Scenario("staging_chaos", 12, (12 * 60, 20 * 60)),
}


def diurnal(now_utc):
    """Load multiplier 0.35..1.0 following a working-day curve in UTC."""
    h = now_utc.hour + now_utc.minute / 60
    base = 0.35 + 0.65 * max(0.0, math.sin((h - 6) / 14 * math.pi)) if 6 <= h <= 20 else 0.35
    if now_utc.weekday() >= 5:
        base *= 0.5
    return base


class Fleet:
    def __init__(self):
        self.q_depth = {q: 50.0 for q in QUEUES}
        self.q_oldest = {q: 5.0 for q in QUEUES}
        self.disk = {"db-primary": 0.62, "db-replica": 0.58}
        self.crash_tick = 0
        self.mem_limit = {}
        for svc, inst, env in INSTANCES:
            app_up.labels(svc, inst, env).set(1)
            build_info.labels(svc, inst, env, "1.14.2" if env == "production" else "1.15.0-rc3").set(1)
            self.mem_limit[inst] = 512 * 1024 * 1024 if svc != "db" else 2048 * 1024 * 1024
            proc_mem_limit.labels(svc, inst, env).set(self.mem_limit[inst])
        for inst in ("db-primary", "db-replica"):
            db_conn_max.labels(inst, "production").set(100)
        for q in QUEUES:
            queue_consumers.labels(q, "production").set(4)

    # -- api --------------------------------------------------------------
    def step_api(self, load, s):
        for svc, inst, env in INSTANCES:
            if svc != "api":
                continue
            staging = env == "staging"
            # api_down takes the whole production pool out, so the "all instances down" rule can page.
            down = (s["api_down"].active and not staging) or (staging and s["staging_chaos"].active and random.random() < 0.4)
            app_up.labels(svc, inst, env).set(0 if down else 1)
            if down:
                proc_cpu.labels(svc, inst, env).set(0)
                proc_mem.labels(svc, inst, env).set(0)
                continue

            err_share = 0.004
            if s["api_error_burst"].active:
                err_share = random.uniform(0.15, 0.4)
            if staging:
                err_share *= 6
            lat_mult = 1.0
            if s["api_latency_spike"].active or s["db_slow"].active:
                lat_mult = 4.0
            rps = (18 if not staging else 2) * load * random.uniform(0.85, 1.15)
            n = max(1, int(rps * TICK))
            for _ in range(n):
                route = random.choices(ROUTES, weights=[5, 3, 2, 1])[0]
                method = "GET" if route != "/orders" or random.random() < 0.6 else "POST"
                r = random.random()
                status = "500" if r < err_share else ("404" if r < err_share + 0.01 else "200")
                if route == "/health":
                    status = "200"
                http_requests.labels(svc, inst, env, route, method, status).inc()
                base = {"/orders": 0.12, "/users": 0.05, "/search": 0.25, "/health": 0.004}[route]
                http_latency.labels(svc, inst, env, route).observe(random.lognormvariate(math.log(base * lat_mult), 0.45))

            proc_cpu.labels(svc, inst, env).set(min(0.98, 0.15 + 0.5 * load * lat_mult * random.uniform(0.9, 1.1)))
            limit = self.mem_limit[inst]
            proc_mem.labels(svc, inst, env).set(limit * (0.45 + 0.3 * load + random.uniform(-0.02, 0.02)))

    # -- worker -----------------------------------------------------------
    def step_worker(self, load, s):
        crash = s["worker_crashloop"].active
        for svc, inst, env in INSTANCES:
            if svc != "worker":
                continue
            if crash and inst == "worker-1":
                self.crash_tick += 1
                if self.crash_tick % 30 == 0:
                    worker_restarts.labels(inst, env).inc()
                up = 0 if (self.crash_tick % 30) < 12 else 1
                app_up.labels(svc, inst, env).set(up)
                proc_cpu.labels(svc, inst, env).set(0.05 if not up else 0.4)
                proc_mem.labels(svc, inst, env).set(60 * 1024 * 1024 if not up else 300 * 1024 * 1024)
                if not up:
                    continue
            else:
                app_up.labels(svc, inst, env).set(1)
                proc_cpu.labels(svc, inst, env).set(min(0.95, 0.2 + 0.4 * load))
                limit = self.mem_limit[inst]
                proc_mem.labels(svc, inst, env).set(limit * (0.5 + 0.2 * load))

            jobs = max(1, int(6 * load * TICK * random.uniform(0.8, 1.2)))
            fail_share = 0.02 if not s["db_slow"].active else 0.12
            for _ in range(jobs):
                r = random.random()
                result = "failed" if r < fail_share else ("retried" if r < fail_share + 0.03 else "ok")
                worker_jobs.labels(inst, env, result).inc()
                worker_job_latency.labels(inst, env).observe(random.lognormvariate(math.log(1.8), 0.6))

    # -- queue ------------------------------------------------------------
    def step_queue(self, load, s):
        for q in QUEUES:
            published = 40 * load * random.uniform(0.9, 1.1)
            consumers = 4
            if s["worker_crashloop"].active:
                consumers = 2
            consume_rate = 11 * consumers
            if s["queue_backlog"].active:
                consume_rate *= 0.4
            if s["queue_flap"].active and q == "orders":
                # oscillate around the warning threshold (depth 500) every ~90s
                target = 500 + 120 * math.sin(time.time() / 90 * 2 * math.pi)
                self.q_depth[q] += (target - self.q_depth[q]) * 0.3
            else:
                self.q_depth[q] = max(0.0, self.q_depth[q] + (published - consume_rate) * TICK)
                self.q_depth[q] = min(self.q_depth[q], 5000)
            queue_published.labels(q, "production").inc(published * TICK)
            queue_consumed.labels(q, "production").inc(min(consume_rate, published + self.q_depth[q]) * TICK)
            queue_depth.labels(q, "production").set(self.q_depth[q])
            queue_consumers.labels(q, "production").set(consumers)
            self.q_oldest[q] = self.q_depth[q] / max(1.0, consume_rate) * 1.4 + random.uniform(0, 2)
            queue_oldest_age.labels(q, "production").set(self.q_oldest[q])
        app_up.labels("queue", "queue-0", "production").set(1)
        proc_cpu.labels("queue", "queue-0", "production").set(0.1 + 0.2 * load)
        proc_mem.labels("queue", "queue-0", "production").set(180 * 1024 * 1024)

    # -- db ---------------------------------------------------------------
    def step_db(self, load, s):
        for inst in ("db-primary", "db-replica"):
            app_up.labels("db", inst, "production").set(1)
            conns = 25 + 50 * load
            if s["db_connections"].active and inst == "db-primary":
                conns = random.uniform(94, 100)
            db_conn_active.labels(inst, "production").set(min(100, conns + random.uniform(-3, 3)))
            lat_mult = 6.0 if s["db_slow"].active else 1.0
            for op, base, n in (("select", 0.004, 40), ("insert", 0.012, 8), ("update", 0.015, 5)):
                for _ in range(max(1, int(n * load))):
                    db_query_latency.labels(inst, "production", op).observe(random.lognormvariate(math.log(base * lat_mult), 0.5))
            self.disk[inst] = min(0.97, self.disk[inst] + 0.0000003)
            db_disk_used.labels(inst, "production").set(self.disk[inst])
            proc_cpu.labels("db", inst, "production").set(min(0.95, 0.2 + 0.5 * load * (lat_mult / 3 if lat_mult > 1 else 1)))
            proc_mem.labels("db", inst, "production").set(1400 * 1024 * 1024 + random.uniform(-20, 20) * 1024 * 1024)
        lag = 0.3 + random.uniform(0, 0.5)
        if s["replication_lag"].active:
            lag = random.uniform(45, 120)
        db_replication_lag.labels("db-replica", "production").set(lag)
        db_replication_lag.labels("db-primary", "production").set(0)


def simulation():
    fleet = Fleet()
    while True:
        now = datetime.now(tz=ZoneInfo("UTC"))
        for sc in SCENARIOS.values():
            sc.maybe_start()
        load = diurnal(now)
        fleet.step_api(load, SCENARIOS)
        fleet.step_worker(load, SCENARIOS)
        fleet.step_queue(load, SCENARIOS)
        fleet.step_db(load, SCENARIOS)
        update_market_metrics(now)
        time.sleep(TICK)


# ----------------------------------------------------------------------------
# HTTP: metrics + webhook sink
# ----------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/metrics":
            body = generate_latest(REGISTRY)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/alerts":
            self.send_response(404)
            self.end_headers()
            return
        receiver = parse_qs(parsed.query).get("receiver", ["unknown"])[0]
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            name = labels.get("alertname", "unknown")
            webhook_received.labels(receiver, alert.get("status", "unknown"), name, labels.get("severity", "")).inc()
            if name == "Watchdog":
                watchdog_last.set(time.time())
            print(f"[webhook] {receiver:<11} {alert.get('status', '?'):<8} {name} {labels.get('service', '')}", flush=True)
        self.send_response(200)
        self.end_headers()


if __name__ == "__main__":
    # Grace period: count from startup, not from zero, so WatchdogNotReceived
    # does not page while Alertmanager is still coming up.
    watchdog_last.set(time.time())
    threading.Thread(target=simulation, daemon=True).start()
    print(f"metrics-generator listening on :{PORT} (SCENARIO_SPEED={SPEED})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
