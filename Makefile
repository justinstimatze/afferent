.PHONY: check test typecheck lint broker-up broker-down run-polar stop-polar tail-polar run-co2 stop-co2 tail-co2 run-aggregator stop-aggregator tail-aggregator

# The Go-equivalent gate (house rule): everything here must pass before a
# change counts as done. CI runs this on every push/PR (.github/workflows/
# ci.yml). It's also wired as a local pre-commit hook, but .git/hooks/ isn't
# part of the clone -- CI is the gate a fresh clone actually gets for free.
check: typecheck lint test

typecheck:
	.venv/bin/python -m mypy --strict src/afferent

lint:
	.venv/bin/python -m ruff check src/afferent tests

test:
	.venv/bin/python -m pytest tests/ -q

# The loopback-only port binding lives in docker-compose.yml, not a
# hand-typed docker run command -- see its comment and mosquitto.conf's.
broker-up:
	docker compose up -d

broker-down:
	docker compose down

# Background each poller with a durable log + pid file (logs/ is
# gitignored) so `make tail-*` works the same in every session, independent
# of any one session's scratchpad path.
#
# --verbose is opt-in (`make run-polar VERBOSE=1`), not the default: at
# DEBUG level these processes log raw per-beat HR/PPI values (a real health
# record, not just diagnostics) plus bleak's own D-Bus dump (paired-device
# MACs, adapter address). logs/ is chmod 700 and each log file chmod 600
# before the process's own redirect ever creates it, so this stays owner-
# readable even when VERBOSE is on.
run-polar:
	@mkdir -p logs && chmod 700 logs
	@touch logs/polar.log && chmod 600 logs/polar.log
	@.venv/bin/python -m afferent.polar_poller $(if $(VERBOSE),--verbose) > logs/polar.log 2>&1 & echo $$! > logs/polar.pid
	@echo "polar_poller running (pid $$(cat logs/polar.pid)) -- logs/polar.log"

stop-polar:
	kill $$(cat logs/polar.pid) && rm -f logs/polar.pid

tail-polar:
	tail -f logs/polar.log

run-co2:
	@mkdir -p logs && chmod 700 logs
	@touch logs/co2.log && chmod 600 logs/co2.log
	@.venv/bin/python -m afferent.co2_poller $(if $(VERBOSE),--verbose) > logs/co2.log 2>&1 & echo $$! > logs/co2.pid
	@echo "co2_poller running (pid $$(cat logs/co2.pid)) -- logs/co2.log"

stop-co2:
	kill $$(cat logs/co2.pid) && rm -f logs/co2.pid

tail-co2:
	tail -f logs/co2.log

run-aggregator:
	@mkdir -p logs && chmod 700 logs
	@touch logs/aggregator.log && chmod 600 logs/aggregator.log
	@.venv/bin/python -m afferent.aggregator $(if $(VERBOSE),--verbose) > logs/aggregator.log 2>&1 & echo $$! > logs/aggregator.pid
	@echo "aggregator running (pid $$(cat logs/aggregator.pid)) -- logs/aggregator.log"

stop-aggregator:
	kill $$(cat logs/aggregator.pid) && rm -f logs/aggregator.pid

tail-aggregator:
	tail -f logs/aggregator.log
