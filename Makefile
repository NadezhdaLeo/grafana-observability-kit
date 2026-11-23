.PHONY: up down restart logs dashboards check screenshots clean demo

GRAFANA_URL ?= http://localhost:3000
GRAFANA_AUTH ?= admin:admin

up:            ## Start the stack
	docker compose up -d --build
	@echo
	@echo "Grafana      $(GRAFANA_URL)   (admin / admin, anonymous viewer enabled)"
	@echo "Prometheus   http://localhost:9090"
	@echo "Alertmanager http://localhost:9093"
	@echo "Generator    http://localhost:8000/metrics"

demo:          ## Start with incidents injected 4x more often (for screenshots and demos)
	SCENARIO_SPEED=4.0 docker compose up -d --build

down:          ## Stop the stack, keep data
	docker compose --profile screenshots down

clean:         ## Stop the stack and delete all data volumes
	docker compose --profile screenshots down -v

restart:
	docker compose restart prometheus alertmanager

logs:
	docker compose logs -f --tail=50 metrics-generator alertmanager

dashboards:    ## Regenerate dashboard JSON from tools/build_dashboards.py
	python3 tools/build_dashboards.py

check:         ## Validate rules, Alertmanager config and dashboard JSON; run the leak check
	docker run --rm -v $(PWD)/prometheus:/p:ro --entrypoint promtool prom/prometheus:v3.5.0 check rules /p/rules/*.yml
	docker run --rm -v $(PWD)/alertmanager:/a:ro --entrypoint amtool prom/alertmanager:v0.28.1 check-config /a/alertmanager.yml
	python3 -c "import json,glob; [json.load(open(f)) for f in glob.glob('grafana/provisioning/dashboards/json/*.json')]; print('dashboard JSON ok')"
	./tools/check_leaks.sh

screenshots:   ## Render every dashboard to docs/screenshots/*.png (starts the renderer profile)
	docker compose --profile screenshots up -d renderer grafana
	GRAFANA_URL=$(GRAFANA_URL) GRAFANA_AUTH=$(GRAFANA_AUTH) ./tools/screenshots.sh

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'
