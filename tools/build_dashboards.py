#!/usr/bin/env python3
"""
Generates the four provisioned dashboards as classic Grafana JSON.

Dashboards are kept as code so that queries, thresholds and layout are reviewable
in a diff. Run:

    python3 tools/build_dashboards.py

Output goes to grafana/provisioning/dashboards/json/. Grafana picks the files up
within 30 seconds (see provisioning/dashboards/dashboards.yml).
"""

import json
import os
from itertools import count

OUT = os.path.join(os.path.dirname(__file__), "..", "grafana", "provisioning", "dashboards", "json")
DS = {"type": "prometheus", "uid": "prometheus"}
_ids = count(1)

# Samples per hour written by Prometheus for one series: 3600 / evaluation_interval.
# Must match prometheus.yml (15s). Exposed as a hidden dashboard variable so the
# alert-hours arithmetic has one place to change.
SPH = 240

# --------------------------------------------------------------------------
# PromQL building blocks
# --------------------------------------------------------------------------


def episodes(selector="", by="", window="$__range", window_s="$__range_s"):
    """
    Number of times an alert entered a new active period.

    changes(ALERTS_FOR_STATE) counts transitions of an existing series, but misses
    the FIRST activation of a series that appears inside the window (a new pod, a
    new instance). The second term adds one for every series whose earliest
    activeAt lies inside the window. Without it, counts are roughly halved on
    anything with a per-instance label.
    """
    g = f" by ({by})" if by else ""
    sel = "{" + selector + "}" if selector else ""
    return (
        f"(sum{g} (changes(ALERTS_FOR_STATE{sel}[{window}])) or vector(0))"
        f" + (sum{g} (min_over_time(ALERTS_FOR_STATE{sel}[{window}]) > bool (time() - {window_s})) or vector(0))"
    )


def episodes_by(by, selector=""):
    sel = "{" + selector + "}" if selector else ""
    return (
        f"sum by ({by}) (changes(ALERTS_FOR_STATE{sel}[$__range]))"
        f" + sum by ({by}) (min_over_time(ALERTS_FOR_STATE{sel}[$__range]) > bool (time() - $__range_s))"
    )


PER_DAY = "/ ($__range_s / 86400)"

# --------------------------------------------------------------------------
# Panel helpers
# --------------------------------------------------------------------------


def target(expr, legend="__auto", instant=False, fmt="time_series", ref="A", interval=None):
    t = {
        "datasource": DS,
        "refId": ref,
        "expr": expr,
        "legendFormat": legend,
        "instant": instant,
        "range": not instant,
        "format": fmt,
        "editorMode": "code",
    }
    if interval:
        t["interval"] = interval
    return t


def thresholds(*steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


def _panel(ptype, title, targets, grid, description="", options=None, defaults=None, overrides=None, transformations=None):
    p = {
        "id": next(_ids),
        "type": ptype,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": dict(zip(("x", "y", "w", "h"), grid)),
        "targets": targets if isinstance(targets, list) else [targets],
        "options": options or {},
        "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
    }
    if transformations:
        p["transformations"] = transformations
    return p


def stat(title, expr, grid, unit="short", desc="", thr=None, mappings=None, color_mode="value", decimals=None, no_value=None, instant=True, legend="__auto", text_size=None):
    d = {"unit": unit, "color": {"mode": "thresholds"} if thr else {"mode": "fixed", "fixedColor": "text"},
         "thresholds": thr or thresholds((0, "text"))}
    if mappings:
        d["mappings"] = mappings
    if decimals is not None:
        d["decimals"] = decimals
    if no_value is not None:
        d["noValue"] = no_value
    o = {"colorMode": color_mode, "graphMode": "none", "justifyMode": "auto", "orientation": "auto",
         "textMode": "auto", "wideLayout": True,
         "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}
    if text_size:
        o["text"] = {"valueSize": text_size}
    return _panel("stat", title, target(expr, legend=legend, instant=instant), grid, desc, o, d)


def ok_mappings():
    return [
        {"type": "value", "options": {"0": {"text": "OK", "color": "green", "index": 0}}},
        {"type": "special", "options": {"match": "null", "result": {"text": "OK", "color": "green", "index": 1}}},
    ]


def ts(title, targets, grid, unit="short", desc="", bars=False, stacked=False, log=False, min_=0, fill=None, legend_table=False, calcs=None, overrides=None, thr_line=None, max_=None, decimals=None):
    custom = {
        "drawStyle": "bars" if bars else "line",
        "lineWidth": 0 if bars else 1,
        "fillOpacity": fill if fill is not None else (80 if bars else 12),
        "gradientMode": "none",
        "showPoints": "never",
        "spanNulls": False,
        "axisPlacement": "auto",
        "axisLabel": "",
        "barAlignment": 0,
        "stacking": {"mode": "normal" if stacked else "none", "group": "A"},
        "scaleDistribution": {"type": "log", "log": 10} if log else {"type": "linear"},
        "thresholdsStyle": {"mode": "line" if thr_line else "off"},
    }
    d = {"unit": unit, "color": {"mode": "palette-classic"}, "custom": custom,
         "thresholds": thr_line or thresholds((0, "transparent"))}
    if min_ is not None and not log:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    if decimals is not None:
        d["decimals"] = decimals
    o = {
        "legend": {"displayMode": "table" if legend_table else "list", "placement": "bottom",
                   "showLegend": True, "calcs": calcs or []},
        "tooltip": {"mode": "multi", "sort": "desc"},
    }
    return _panel("timeseries", title, targets, grid, desc, o, d, overrides)


def organize(rename, exclude=("Time",), order=None):
    return [{"id": "organize", "options": {
        "excludeByName": {e: True for e in exclude},
        "renameByName": rename,
        "indexByName": {k: i for i, k in enumerate(order)} if order else {},
        "includeByName": {},
    }}]


def col(name, width=None, align=None, cell=None, unit=None, thr=None, color=None, links=None, decimals=None):
    props = []
    if width:
        props.append({"id": "custom.width", "value": width})
    if align:
        props.append({"id": "custom.align", "value": align})
    if cell:
        props.append({"id": "custom.cellOptions", "value": cell})
    if unit:
        props.append({"id": "unit", "value": unit})
    if thr:
        props.append({"id": "thresholds", "value": thr})
        props.append({"id": "color", "value": {"mode": "thresholds"}})
    if color:
        props.append({"id": "color", "value": {"mode": "fixed", "fixedColor": color}})
    if links:
        props.append({"id": "links", "value": links})
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


GAUGE_CELL = {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}
GRAD_CELL = {"type": "gauge", "mode": "gradient", "valueDisplayMode": "text"}
BG_CELL = {"type": "color-background", "mode": "gradient"}


def table(title, expr, grid, rename, desc="", sort=None, desc_sort=True, overrides=None, no_value=None, unit="short", filterable=False, order=None, exclude=("Time",)):
    d = {"unit": unit, "color": {"mode": "fixed", "fixedColor": "text"},
         "custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": filterable, "inspect": False},
         "thresholds": thresholds((0, "text"))}
    if no_value:
        d["noValue"] = no_value
    o = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False, "reducer": ["sum"], "fields": ""},
         "sortBy": [{"displayName": sort, "desc": desc_sort}] if sort else []}
    return _panel("table", title, target(expr, instant=True, fmt="table"), grid, desc, o, d, overrides,
                  organize(rename, exclude=exclude, order=order))


def bargauge(title, targets, grid, desc="", unit="short", color="continuous-BlPu", thr=None, max_=None, lcd=True):
    d = {"unit": unit, "min": 0, "color": {"mode": "thresholds"} if thr else {"mode": color},
         "thresholds": thr or thresholds((0, "green"))}
    if max_ is not None:
        d["max"] = max_
    o = {"displayMode": "lcd" if lcd else "gradient", "orientation": "horizontal", "valueMode": "color",
         "showUnfilled": True, "minVizWidth": 8, "minVizHeight": 16, "maxVizHeight": 300, "sizing": "auto",
         "namePlacement": "auto",
         "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}
    return _panel("bargauge", title, targets, grid, desc, o, d)


def gauge(title, expr, grid, desc="", unit="percentunit", thr=None, min_=0, max_=1, decimals=1):
    d = {"unit": unit, "min": min_, "max": max_, "decimals": decimals, "color": {"mode": "thresholds"},
         "thresholds": thr or thresholds((0, "green"), (0.7, "#EAB839"), (0.9, "red"))}
    o = {"showThresholdLabels": True, "showThresholdMarkers": True, "sizing": "auto",
         "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}
    return _panel("gauge", title, target(expr, instant=True), grid, desc, o, d)


def text(title, md, grid):
    return _panel("text", title, [], grid, "", {"mode": "markdown", "content": md,
                  "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}})


def state_timeline(title, targets, grid, desc="", mappings=None):
    d = {"color": {"mode": "thresholds"}, "thresholds": thresholds((0, "transparent"), (1, "green")),
         "custom": {"fillOpacity": 75, "lineWidth": 0}, "mappings": mappings or []}
    o = {"mergeValues": True, "showValue": "never", "alignValue": "left", "rowHeight": 0.8,
         "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
         "tooltip": {"mode": "single", "sort": "none"}}
    return _panel("state-timeline", title, targets, grid, desc, o, d)


def heatmap(title, expr, grid, desc=""):
    o = {"calculate": False, "yAxis": {"unit": "s", "axisPlacement": "left"},
         "color": {"mode": "scheme", "scheme": "Oranges", "steps": 64, "exponent": 0.5, "fill": "dark-orange"},
         "cellGap": 1, "showValue": "never", "legend": {"show": True},
         "tooltip": {"mode": "single", "yHistogram": True, "showColorScale": False},
         "exemplars": {"color": "rgba(255,0,255,0.7)"}, "rowsFrame": {"layout": "auto"}, "filterValues": {"le": 1e-9}}
    return _panel("heatmap", title, target(expr, fmt="heatmap", legend="{{le}}"), grid, desc, o, {"custom": {"scaleDistribution": {"type": "linear"}}})


def clock(title, tz, grid):
    return {
        "id": next(_ids), "type": "grafana-clock-panel", "title": title,
        "gridPos": dict(zip(("x", "y", "w", "h"), grid)),
        "options": {"mode": "time", "clockType": "24 hour", "timezone": tz, "refresh": "sec",
                    "timeSettings": {"fontSize": "32px", "fontWeight": "bold"},
                    "dateSettings": {"showDate": True, "dateFormat": "ddd D MMM", "fontSize": "14px", "fontWeight": "normal"},
                    "bgColor": ""},
    }


def row(title, y, collapsed=False):
    return {"id": next(_ids), "type": "row", "title": title, "collapsed": collapsed,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def variable_query(name, label, query, multi=True, hide=0):
    return {
        "name": name, "label": label, "type": "query", "datasource": DS,
        "definition": query, "query": {"query": query, "refId": name},
        "refresh": 2, "multi": multi, "includeAll": multi, "allValue": ".*",
        "current": {"selected": True, "text": ["All"] if multi else "", "value": ["$__all"] if multi else ""},
        "hide": hide, "sort": 1,
    }


def variable_const(name, label, value, description=""):
    return {"name": name, "label": label, "type": "constant", "query": str(value),
            "current": {"text": str(value), "value": str(value)}, "hide": 2, "description": description}


def dashboard(uid, title, panels, variables, tags, time_from="now-6h", refresh="30s", description=""):
    return {
        "uid": uid, "title": title, "description": description, "tags": tags, "timezone": "browser",
        "editable": True, "graphTooltip": 1, "schemaVersion": 39, "version": 1,
        "time": {"from": time_from, "to": "now"}, "refresh": refresh,
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                                   "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                                   "name": "Annotations & Alerts", "type": "dashboard"}]},
        "templating": {"list": variables},
        "panels": panels,
        "links": [{"title": "Observability Kit", "type": "dashboards", "tags": ["observability-kit"],
                   "asDropdown": True, "includeVars": False, "keepTime": True}],
    }


# --------------------------------------------------------------------------
# 1. Service overview
# --------------------------------------------------------------------------


def service_overview():
    S = 'service=~"$service", environment=~"$env"'
    red_thr = thresholds((0, "green"), (0.01, "#EAB839"), (0.05, "red"))
    panels = [
        row("Health", 0),
        stat("Instances up", f'sum(app_up{{{S}}}) / count(app_up{{{S}}})', (0, 1, 4, 5), unit="percentunit",
             desc="Share of instances answering their health check.", decimals=0,
             thr=thresholds((0, "red"), (0.5, "#EAB839"), (1, "green")), color_mode="background"),
        stat("Request rate", f'sum(rate(http_requests_total{{{S}}}[5m]))', (4, 1, 4, 5), unit="reqps",
             desc="API requests per second across the selected services.", decimals=1),
        stat("Error ratio", f'sum(rate(http_requests_total{{{S}, status=~"5.."}}[5m])) / sum(rate(http_requests_total{{{S}}}[5m]))',
             (8, 1, 4, 5), unit="percentunit", decimals=2, thr=red_thr, color_mode="background",
             desc="5xx share of all requests over 5 minutes. Yellow at 1%, red at 5% (the paging threshold)."),
        stat("p95 latency", f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))',
             (12, 1, 4, 5), unit="s", decimals=2, thr=thresholds((0, "green"), (0.5, "#EAB839"), (1, "red")),
             color_mode="background", desc="Warning tier starts at 1s."),
        stat("Firing alerts", f'count(ALERTS{{alertstate="firing", {S}, severity!="info"}}) or vector(0)', (16, 1, 4, 5),
             desc="critical and warning alerts firing for the selected services. info is excluded on purpose.",
             thr=thresholds((0, "green"), (1, "#EAB839"), (3, "red")), mappings=ok_mappings()),
        stat("Paging now", f'count(ALERTS{{alertstate="firing", {S}, page="true", environment="production"}}) or vector(0)', (20, 1, 4, 5),
             desc="Alerts that have a human on the pager right now.",
             thr=thresholds((0, "green"), (1, "red")), mappings=ok_mappings(), color_mode="background"),

        row("Traffic and errors", 6),
        ts("Requests per second by service", [target(f'sum by (service) (rate(http_requests_total{{{S}}}[5m]))', "{{service}}")],
           (0, 7, 12, 8), unit="reqps", fill=20, stacked=True),
        ts("5xx ratio by service", [target(f'sum by (service) (rate(http_requests_total{{{S}, status=~"5.."}}[5m])) / sum by (service) (rate(http_requests_total{{{S}}}[5m]))', "{{service}}")],
           (12, 7, 12, 8), unit="percentunit", thr_line=thresholds((0, "transparent"), (0.05, "red")),
           desc="The red line is the ApiHighErrorRate paging threshold."),

        row("Latency", 15),
        ts("API latency percentiles", [
            target(f'histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', "p50"),
            target(f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', "p95", ref="B"),
            target(f'histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', "p99", ref="C"),
        ], (0, 16, 12, 8), unit="s", thr_line=thresholds((0, "transparent"), (1, "#EAB839"))),
        ts("Database p95 query latency by operation", [target(f'histogram_quantile(0.95, sum by (le, op) (rate(db_query_duration_seconds_bucket{{environment=~"$env"}}[5m])))', "{{op}}")],
           (12, 16, 12, 8), unit="s", desc="API latency usually follows this panel with a few minutes of delay."),

        row("Background work", 24),
        ts("Worker jobs per second by result", [target(f'sum by (result) (rate(worker_jobs_total{{environment=~"$env"}}[5m]))', "{{result}}")],
           (0, 25, 8, 8), unit="ops", stacked=True, fill=60,
           overrides=[{"matcher": {"id": "byName", "options": "failed"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                      {"matcher": {"id": "byName", "options": "retried"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#EAB839"}}]},
                      {"matcher": {"id": "byName", "options": "ok"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]),
        ts("Queue depth", [target(f'queue_depth{{environment=~"$env"}}', "{{queue}}")], (8, 25, 8, 8),
           thr_line=thresholds((0, "transparent"), (500, "#EAB839")), desc="Yellow line: QueueDepthHigh threshold, the kit's deliberately flapping rule."),
        ts("Oldest message age", [target(f'queue_oldest_message_age_seconds{{environment=~"$env"}}', "{{queue}}")], (16, 25, 8, 8),
           unit="s", thr_line=thresholds((0, "transparent"), (300, "red")), desc="Red line: QueueOldestMessageTooOld pages at 5 minutes."),

        row("Storage", 33),
        ts("Database connections, share of limit", [target(f'db_connections_active{{environment=~"$env"}} / db_connections_max{{environment=~"$env"}}', "{{instance}}")],
           (0, 34, 8, 8), unit="percentunit", max_=1, thr_line=thresholds((0, "transparent"), (0.75, "#EAB839"), (0.9, "red"))),
        ts("Replication lag", [target(f'db_replication_lag_seconds{{instance="db-replica", environment=~"$env"}}', "{{instance}}")],
           (8, 34, 8, 8), unit="s", thr_line=thresholds((0, "transparent"), (30, "#EAB839"), (90, "red"))),
        ts("Worker restarts per 15 minutes", [target(f'increase(worker_restarts_total{{environment=~"$env"}}[15m])', "{{instance}}")],
           (16, 34, 8, 8), bars=True, thr_line=thresholds((0, "transparent"), (3, "red")),
           desc="WorkerCrashLooping counts restarts instead of watching app_up, because a crash loop is up again before any for: clause elapses."),

        row("Firing now", 42),
        table("Alerts firing for the selected services", f'ALERTS{{alertstate="firing", {S}}}', (0, 43, 24, 8),
              {"alertname": "Alert", "severity": "Severity", "page": "Pages", "owner": "Owner", "service": "Service", "instance": "Instance", "environment": "Env"},
              exclude=("Time", "Value", "__name__", "alertstate", "job", "alertname_family", "route", "method", "status", "op", "queue", "version", "cluster"),
              order=["alertname", "severity", "page", "owner", "service", "environment", "instance"],
              no_value="Nothing firing", filterable=True,
              overrides=[col("Alert", 300, "left"), col("Severity", 100), col("Pages", 80), col("Owner", 100)]),
    ]
    variables = [
        variable_query("service", "Service", "label_values(app_up, service)"),
        variable_query("env", "Environment", "label_values(app_up, environment)"),
    ]
    return dashboard("svc-overview", "Service Overview", panels, variables, ["observability-kit", "services"],
                     description="One page per fleet: health, traffic, errors, latency, saturation, and what is firing.")


# --------------------------------------------------------------------------
# 2. Golden signals (latency / errors / saturation) for one service
# --------------------------------------------------------------------------


def golden_signals():
    S = 'service="$service", environment=~"$env"'
    panels = [
        row("Latency", 0),
        heatmap("Request latency distribution", f'sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[1m]))', (0, 1, 14, 9),
                desc="A second band appearing above the main one is a slow dependency, not a general slowdown."),
        ts("Percentiles", [
            target(f'histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', "p50"),
            target(f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', "p95", ref="B"),
            target(f'histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', "p99", ref="C"),
        ], (14, 1, 10, 9), unit="s", thr_line=thresholds((0, "transparent"), (1, "#EAB839")), legend_table=True, calcs=["mean", "max"]),
        table("p95 by route", f'histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket{{{S}}}[5m])))', (0, 10, 12, 7),
              {"route": "Route", "Value": "p95"}, sort="p95", unit="s",
              overrides=[col("Route", 200, "left"), col("p95", cell=GAUGE_CELL, thr=thresholds((0, "green"), (0.5, "#EAB839"), (1, "red")), decimals=3)]),
        ts("Slowest route, p95", [target(f'topk(1, histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket{{{S}}}[5m]))))', "{{route}}")],
           (12, 10, 12, 7), unit="s"),

        row("Traffic", 17),
        ts("Requests per second by route", [target(f'sum by (route) (rate(http_requests_total{{{S}}}[5m]))', "{{route}}")], (0, 18, 12, 8), unit="reqps", stacked=True, fill=50),
        ts("Requests per second by status", [target(f'sum by (status) (rate(http_requests_total{{{S}}}[5m]))', "{{status}}")], (12, 18, 12, 8), unit="reqps", stacked=True, fill=50,
           overrides=[{"matcher": {"id": "byRegexp", "options": "5.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                      {"matcher": {"id": "byRegexp", "options": "4.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#EAB839"}}]},
                      {"matcher": {"id": "byRegexp", "options": "2.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]),

        row("Errors", 26),
        ts("5xx ratio", [target(f'sum(rate(http_requests_total{{{S}, status=~"5.."}}[5m])) / sum(rate(http_requests_total{{{S}}}[5m]))', "5xx ratio")],
           (0, 27, 8, 8), unit="percentunit", thr_line=thresholds((0, "transparent"), (0.01, "#EAB839"), (0.05, "red")),
           desc="Yellow: ApiElevatedErrorRate (chat). Red: ApiHighErrorRate (pages)."),
        ts("Error budget burn rate (SLO 99.5%)", [
            target(f'(sum(rate(http_requests_total{{{S}, status=~"5.."}}[1h])) / sum(rate(http_requests_total{{{S}}}[1h]))) / 0.005', "1h window"),
            target(f'(sum(rate(http_requests_total{{{S}, status=~"5.."}}[6h])) / sum(rate(http_requests_total{{{S}}}[6h]))) / 0.005', "6h window", ref="B"),
        ], (8, 27, 8, 8), decimals=1, thr_line=thresholds((0, "transparent"), (14.4, "red")),
           desc="Burn rate 1 = the budget lasts exactly 30 days. ApiErrorBudgetBurn pages at 14.4x on the 1h window, confirmed by 5m."),
        table("5xx per second by route", f'sum by (route) (rate(http_requests_total{{{S}, status=~"5.."}}[5m]))', (16, 27, 8, 8),
              {"route": "Route", "Value": "5xx/s"}, sort="5xx/s", unit="reqps",
              overrides=[col("Route", 160, "left"), col("5xx/s", cell=GAUGE_CELL, color="red", decimals=2)]),

        row("Saturation", 35),
        ts("CPU per instance", [target(f'process_cpu_ratio{{{S}}}', "{{instance}}")], (0, 36, 8, 8), unit="percentunit", max_=1,
           thr_line=thresholds((0, "transparent"), (0.8, "#EAB839"))),
        ts("Memory, share of limit", [target(f'process_memory_bytes{{{S}}} / process_memory_limit_bytes{{{S}}}', "{{instance}}")], (8, 36, 8, 8),
           unit="percentunit", max_=1, thr_line=thresholds((0, "transparent"), (0.9, "red"))),
        ts("Dependency saturation", [
            target('max(db_connections_active{instance="db-primary"} / db_connections_max{instance="db-primary"})', "db connections"),
            target('max(queue_depth) / 5000', "queue depth (of 5000)", ref="B"),
        ], (16, 36, 8, 8), unit="percentunit", max_=1,
           desc="What the service depends on. Saturation here shows up as latency on this service before it shows up as errors."),
    ]
    variables = [
        variable_query("service", "Service", "label_values(http_requests_total, service)", multi=False),
        variable_query("env", "Environment", "label_values(app_up, environment)"),
    ]
    variables[0]["current"] = {"selected": True, "text": "api", "value": "api"}
    return dashboard("golden-signals", "Golden Signals", panels, variables, ["observability-kit", "services"],
                     description="Latency, traffic, errors and saturation for one service, with the alert thresholds drawn on the panels.")


# --------------------------------------------------------------------------
# 3. Alert noise overview
# --------------------------------------------------------------------------


def alert_noise():
    O = 'owner=~"$owner"'
    F = f'alertstate="firing", {O}'
    CRIT = f'severity="critical", {O}'
    INFO = f'severity="info", {O}'
    panels = [
        row("Volume", 0),
        stat("Total firings", episodes(O), (0, 1, 4, 5), text_size=56,
             desc="Episodes: how many times any alert entered the firing state in the range. Not samples, not notifications."),
        stat("Critical firings per day", f'({episodes(CRIT)}) {PER_DAY}', (4, 1, 4, 5), decimals=1,
             desc="What the pager would see if routing followed severity. Green under 5, red above 10 (Google SRE: two incidents per 12-hour shift).",
             thr=thresholds((0, "green"), (5, "#EAB839"), (10, "red")), color_mode="background", text_size=56),
        stat("Info share", f'({episodes(INFO)}) / ({episodes(O)})', (8, 1, 4, 5), unit="percentunit", decimals=0,
             desc="Share of episodes that are report-only. High is fine; it means the info tier is used.", text_size=56),
        stat("Alerts without owner", 'count(count by (alertname) (count_over_time(ALERTS{alertstate="firing", owner=""}[$__range]))) or vector(0)',
             (12, 1, 4, 5), desc="Distinct rules that fired without an owner label. Routing by team cannot work for these.",
             thr=thresholds((0, "green"), (1, "#EAB839"), (5, "red")), mappings=ok_mappings(), text_size=56),
        stat("Alerts without service", 'count(count by (alertname) (count_over_time(ALERTS{alertstate="firing", service=""}[$__range]))) or vector(0)',
             (16, 1, 4, 5), desc="Distinct rules that fired without a service label. These cannot be mapped to a catalog entry.",
             thr=thresholds((0, "green"), (1, "#EAB839"), (5, "red")), mappings=ok_mappings(), text_size=56),
        stat("Distinct rules fired", f'count(count by (alertname) (count_over_time(ALERTS{{{F}}}[$__range])))', (20, 1, 4, 5),
             desc="How many different rules produced at least one episode.", text_size=56),

        ts("Firings per hour", [
            target(episodes(O, window="1h", window_s="3600"), "All firings", interval="1h"),
            target(episodes(CRIT, window="1h", window_s="3600"), "Critical", ref="B", interval="1h"),
        ], (0, 6, 16, 8), bars=True, log=True, legend_table=True, calcs=["max", "mean"],
           desc="Log scale: the two series differ by an order of magnitude. Min step 1h so the window equals the step and bars never overlap.",
           overrides=[{"matcher": {"id": "byName", "options": "All firings"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "semi-dark-orange"}}]},
                      {"matcher": {"id": "byName", "options": "Critical"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "semi-dark-red"}}]}]),
        ts("Firings per hour by severity", [target(episodes(O, by="severity", window="1h", window_s="3600"), "{{severity}}", interval="1h")],
           (16, 6, 8, 8), bars=True, stacked=True,
           overrides=[{"matcher": {"id": "byName", "options": "critical"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                      {"matcher": {"id": "byName", "options": "warning"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#EAB839"}}]},
                      {"matcher": {"id": "byName", "options": "info"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "blue"}}]}]),

        row("Who makes the noise", 14),
        table("Top rules by firings", f'topk(15, {episodes_by("alertname", O)})', (0, 15, 12, 9),
              {"alertname": "Rule", "Value": "Firings"}, sort="Firings",
              desc="Rules that start most often. Fix: longer for:, wider threshold, or a rate-based condition.",
              overrides=[col("Rule", 300, "left"), col("Firings", cell=GAUGE_CELL, color="semi-dark-orange")]),
        table("Top rules by alert-hours", f'topk(15, sum by (alertname) (count_over_time(ALERTS{{{F}}}[$__range])) / $sph)', (12, 15, 12, 9),
              {"alertname": "Rule", "Value": "Alert-hours"}, sort="Alert-hours",
              desc="Summed time in the firing state across all series of the rule. Sample count divided by $sph (samples per hour). Fix: repair the cause, or stop calling it an alert.",
              overrides=[col("Rule", 300, "left"), col("Alert-hours", cell=GAUGE_CELL, color="semi-dark-purple", decimals=1)]),
        table("Flapping: mean minutes per episode", f'bottomk(15, (sum by (alertname) (count_over_time(ALERTS{{{F}}}[$__range])) / $sph * 60) / ({episodes_by("alertname", O)} > 3))',
              (0, 24, 12, 9), {"alertname": "Rule", "Value": "Minutes per episode"}, sort="Minutes per episode", desc_sort=False,
              desc="Alert-hours divided by firings, for rules with more than 3 episodes. Under 5 minutes the alert resolves before anyone can look. QueueDepthHigh is the planted example.",
              overrides=[col("Rule", 300, "left"), col("Minutes per episode", cell=BG_CELL, thr=thresholds((0, "red"), (5, "#EAB839"), (30, "green")), decimals=1)]),
        table("Always firing: share of range", f'topk(15, max by (alertname) (count_over_time(ALERTS{{{F}}}[$__range])) / ($__range_s / 3600 * $sph))',
              (12, 24, 12, 9), {"alertname": "Rule", "Value": "Time firing"}, sort="Time firing", unit="percentunit",
              desc="Busiest series of each rule as a fraction of the range. Near 100% means the rule never changes state and carries no information. Delete it or make it a report.",
              overrides=[col("Rule", 300, "left"), col("Time firing", cell=GRAD_CELL, thr=thresholds((0, "green"), (0.5, "#EAB839"), (0.9, "red")), decimals=0)]),
        table("Cardinality: series per rule", f'topk(15, count by (alertname) (count_over_time(ALERTS{{{F}}}[$__range])))', (0, 33, 12, 8),
              {"alertname": "Rule", "Value": "Series"}, sort="Series",
              desc="Distinct label sets that fired. Many series with few episodes is one systemic fact spread across instances: fix Alertmanager group_by before touching the rule.",
              overrides=[col("Rule", 300, "left"), col("Series", cell=GAUGE_CELL, color="semi-dark-blue")]),
        bargauge("Firings by owner", [target(episodes_by("owner", O), "{{owner}}", instant=True)], (12, 33, 12, 8),
                 desc="Whose rules make the noise. Not a league table; a routing check before a conversation."),

        row("Label hygiene", 41),
        table("Severity values in use", f'{episodes_by("severity", O)}', (0, 42, 8, 7), {"severity": "Severity", "Value": "Firings"}, sort="Firings",
              desc="Every severity value that produced an episode. Anything outside critical / warning / info is a typo in a rule.",
              overrides=[col("Severity", 140, "left"), col("Firings", cell=GAUGE_CELL, color="semi-dark-orange")]),
        table("Rules missing owner or service", 'count by (alertname, owner, service) (count_over_time(ALERTS{alertstate="firing", owner=""}[$__range]) or count_over_time(ALERTS{alertstate="firing", service=""}[$__range]))',
              (8, 42, 16, 7), {"alertname": "Rule", "owner": "Owner", "service": "Service", "Value": "Series"}, sort="Series",
              no_value="OK: every firing rule carries owner and service",
              overrides=[col("Rule", 300, "left"), col("Owner", 120), col("Service", 120)]),

        row("Currently firing", 49, collapsed=False),
        table("Firing now, all labels", f'ALERTS{{{F}}}', (0, 50, 24, 9),
              {"alertname": "Rule", "severity": "Severity", "page": "Pages", "owner": "Owner", "service": "Service", "environment": "Env", "instance": "Instance"},
              exclude=("Time", "Value", "__name__", "alertstate", "job", "alertname_family", "cluster"),
              order=["alertname", "severity", "page", "owner", "service", "environment", "instance"],
              filterable=True, no_value="Nothing firing",
              overrides=[col("Rule", 280, "left"), col("Severity", 100), col("Pages", 80)]),
    ]
    variables = [
        variable_query("owner", "Owner", "label_values(ALERTS, owner)"),
        variable_const("sph", "Samples per hour", SPH, "3600 / evaluation_interval. Prometheus evaluates every 15s, so 240."),
    ]
    return dashboard("alert-noise", "Alert Noise Overview", panels, variables, ["observability-kit", "alerting"], time_from="now-24h",
                     description="Which rules produce the noise, how much, and what kind: frequent, long-lived, flapping, or always on.")


# --------------------------------------------------------------------------
# 4. On-call view
# --------------------------------------------------------------------------


def oncall_view():
    PROD = 'environment="production"'
    PAGE = f'page="true", {PROD}'
    CRIT = f'severity="critical", {PROD}'
    BACKLOG = f'severity="critical", page!="true", {PROD}'
    page_thr = thresholds((0, "green"), (4, "#EAB839"), (8, "red"))
    session_map = [{"type": "value", "options": {"1": {"text": "OPEN", "color": "green", "index": 0}, "0": {"text": "closed", "color": "#555", "index": 1}}}]
    panels = [
        row("Right now", 0),
        stat("Paging now", f'count(ALERTS{{alertstate="firing", page="true", {PROD}}}) or vector(0)', (0, 1, 4, 5),
             thr=thresholds((0, "green"), (1, "red")), mappings=ok_mappings(), color_mode="background", text_size=56,
             desc="Alerts with page=\"true\" in production, firing right now. Each one has a human on the hook."),
        stat("Firing, not paging", f'count(ALERTS{{alertstate="firing", page!="true", severity!="info"}}) or vector(0)', (4, 1, 4, 5),
             mappings=ok_mappings(), thr=thresholds((0, "green"), (1, "#EAB839"), (5, "red")), text_size=56,
             desc="critical and warning alerts that stay in chat."),
        stat("Active silences", 'sum(alertmanager_silences{state="active"}) or vector(0)', (8, 1, 4, 5),
             thr=thresholds((0, "green"), (1, "#EAB839"), (5, "red")), text_size=56,
             desc="From Alertmanager itself. Every silence should carry a ticket in its comment; review weekly."),
        stat("Suppressed alerts", 'sum(alertmanager_alerts{state="suppressed"}) or vector(0)', (12, 1, 4, 5),
             thr=thresholds((0, "green"), (1, "#EAB839"), (10, "red")), text_size=56,
             desc="Alerts hidden by a silence or an inhibition rule. What you are choosing not to see."),
        stat("Heartbeat age", 'time() - watchdog_last_received_timestamp_seconds', (16, 1, 4, 5), unit="s", decimals=0, text_size=48,
             thr=thresholds((0, "green"), (120, "#EAB839"), (300, "red")), color_mode="background",
             desc="Seconds since the Watchdog alert last reached the heartbeat receiver. Above 5 minutes the alerting pipeline is broken and nothing else will page."),
        stat("Alertmanager up", 'min(up{job="alertmanager"})', (20, 1, 4, 5), text_size=48,
             mappings=[{"type": "value", "options": {"1": {"text": "UP", "color": "green", "index": 0}, "0": {"text": "DOWN", "color": "red", "index": 1}}}],
             thr=thresholds((0, "red"), (1, "green")), color_mode="background",
             desc="A single Alertmanager is a single point of failure. The heartbeat on the left is the external check."),

        row("Trading hours", 6),
        clock("New York", "America/New_York", (0, 7, 4, 5)),
        clock("London", "Europe/London", (4, 7, 4, 5)),
        clock("Frankfurt", "Europe/Berlin", (8, 7, 4, 5)),
        clock("Tokyo", "Asia/Tokyo", (12, 7, 4, 5)),
        stat("Sessions", 'market_session_open', (16, 7, 8, 5), mappings=session_map, legend="{{exchange}}",
             thr=thresholds((0, "#555"), (1, "green")), color_mode="background",
             desc="Live from the market_session_open metric (weekday sessions only, no holiday calendar). An outage during an open session is a different incident from the same outage at 3 a.m."),
        state_timeline("Session timeline", [target('market_session_open', "{{exchange}}")], (0, 12, 16, 6), mappings=session_map,
                       desc="When each exchange was open across the dashboard range. Overlay this mentally on the paging timeline below."),
        bargauge("Next session event", [target('market_seconds_to_next_event', "{{exchange}}", instant=True)], (16, 12, 8, 6), unit="dtdurations",
                 color="continuous-GrYlRd", desc="Time until the exchange opens (if closed) or closes (if open).", lcd=False),

        row("Paging load", 18),
        stat("Pages delivered per day", f'(sum(increase(alertmanager_webhook_notifications_total{{receiver="pager", status="firing"}}[$__range])) or vector(0)) {PER_DAY}',
             (0, 19, 6, 6), decimals=1, thr=page_thr, color_mode="background", text_size=56,
             desc="Notifications the pager receiver actually got, averaged per day over the range. Green under 4 (Google SRE: two incidents per 12-hour shift)."),
        stat("Page-worthy episodes per day", f'({episodes(PAGE)}) {PER_DAY}', (6, 19, 6, 6), decimals=1, thr=page_thr, text_size=56,
             desc="Episodes of page=\"true\" rules. The gap to the left-hand number is what grouping and inhibition saved."),
        stat("Severity model: critical per day", f'({episodes(CRIT)}) {PER_DAY}', (12, 19, 6, 6), decimals=1, thr=page_thr, text_size=56,
             desc="What the pager would see if routing followed severity alone. Compare with the left: the difference is the cleanup backlog."),
        stat("Critical rules that do not page", f'count(count by (alertname) (count_over_time(ALERTS{{alertstate="firing", severity="critical", page!="true", {PROD}}}[$__range]))) or vector(0)',
             (18, 19, 6, 6), mappings=ok_mappings(), thr=thresholds((0, "green"), (1, "#EAB839"), (5, "red")), text_size=56,
             desc="Distinct rules labelled critical in production without page=\"true\". Each needs a decision: page, or downgrade."),
        ts("Pages per day", [target(f'sum(increase(alertmanager_webhook_notifications_total{{receiver="pager", status="firing"}}[$__interval]))', "pages", interval="1d")],
           (0, 25, 12, 8), bars=True, thr_line=thresholds((0, "transparent"), (4, "#EAB839")), legend_table=True, calcs=["sum", "max"],
           desc="Daily pages with the sustainable budget drawn at 4."),
        ts("Pages per hour", [target(f'sum(increase(alertmanager_webhook_notifications_total{{receiver="pager", status="firing"}}[$__interval]))', "pages", interval="1h")],
           (12, 25, 12, 8), bars=True, desc="Hourly resolution. Read against the session timeline above: pages outside working hours are the ones that cost sleep."),

        row("What pages, what should", 33),
        table("Rules that paged", f'topk(15, {episodes_by("alertname, owner, service", PAGE)})', (0, 34, 12, 9),
              {"alertname": "Rule", "owner": "Owner", "service": "Service", "Value": "Firings"}, sort="Firings",
              no_value="No rule paged in this range",
              desc="A paging rule with many firings is paging noise: the on-call engineer sees it too often to treat it as urgent.",
              overrides=[col("Rule", 260, "left"), col("Owner", 90), col("Service", 90), col("Firings", cell=GAUGE_CELL, color="semi-dark-red")]),
        table("Severity cleanup backlog", f'topk(15, {episodes_by("alertname, owner", BACKLOG)})', (12, 34, 12, 9),
              {"alertname": "Rule", "owner": "Owner", "Value": "Firings"}, sort="Firings",
              no_value="OK: every critical rule in production pages",
              desc="critical without page=\"true\". Work through it from the top: must this wake someone at 03:00? If not, it is a warning.",
              overrides=[col("Rule", 300, "left"), col("Owner", 100), col("Firings", cell=GAUGE_CELL, color="semi-dark-orange")]),
        table("Paging rules outside production", f'count by (alertname, environment) (count_over_time(ALERTS{{alertstate="firing", page="true", environment!="production"}}[$__range]))',
              (0, 43, 12, 7), {"alertname": "Rule", "environment": "Env", "Value": "Series"}, sort="Series",
              no_value="OK: nothing pages for non-production", desc="The pager route ignores these, but the label is wrong and will bite after the next routing change.",
              overrides=[col("Rule", 300, "left")]),
        bargauge("Deliveries by receiver", [target('sum by (receiver) (increase(alertmanager_webhook_notifications_total{status="firing"}[$__range]))', "{{receiver}}", instant=True)],
                 (12, 43, 12, 7), desc="What Alertmanager delivered where. critical goes to both pager and team-chat by design; a page=\"true\" alert missing from the pager receiver is a routing bug."),

        row("Firing now", 50),
        table("Firing now", 'ALERTS{alertstate="firing", severity!="info"}', (0, 51, 24, 9),
              {"alertname": "Rule", "severity": "Severity", "page": "Pages", "owner": "Owner", "service": "Service", "environment": "Env", "instance": "Instance"},
              exclude=("Time", "Value", "__name__", "alertstate", "job", "alertname_family", "cluster"),
              order=["alertname", "severity", "page", "owner", "service", "environment", "instance"],
              filterable=True, no_value="Nothing firing",
              overrides=[col("Rule", 280, "left", links=[{"title": "Open in Prometheus", "url": "http://localhost:9090/alerts?search=${__data.fields.Rule}", "targetBlank": True}]),
                         col("Severity", 100, cell={"type": "color-text"}, thr=thresholds((0, "text"))),
                         col("Pages", 80)]),
    ]
    variables = [variable_const("sph", "Samples per hour", SPH, "3600 / evaluation_interval.")]
    return dashboard("on-call-view", "On-call View", panels, variables, ["observability-kit", "alerting", "on-call"], time_from="now-24h",
                     description="Who is being paged, how often, whether that matches the severity labels, and what the markets are doing while it happens.")


# --------------------------------------------------------------------------


def main():
    os.makedirs(OUT, exist_ok=True)
    for build in (service_overview, golden_signals, alert_noise, oncall_view):
        d = build()
        path = os.path.join(OUT, f"{d['uid']}.json")
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
            f.write("\n")
        n = sum(1 for p in d["panels"] if p["type"] != "row")
        print(f"{d['uid']:<16} {n:>2} panels -> {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
