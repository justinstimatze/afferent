.PHONY: check test typecheck lint broker-up broker-down run-polar stop-polar tail-polar run-co2 stop-co2 tail-co2 run-aggregator stop-aggregator tail-aggregator

# Everything here must pass before a change counts as done. CI runs it on
# every push and pull request (.github/workflows/ci.yml).
check: typecheck lint test

typecheck:
	.venv/bin/python -m mypy --strict src/afferent

lint:
	.venv/bin/python -m ruff check src/afferent tests

test:
	.venv/bin/python -m pytest tests/ -q

# The loopback-only port binding lives in docker-compose.yml.
broker-up:
	docker compose up -d

broker-down:
	docker compose down

# Run each process in the background with a log and pid file under logs/
# (gitignored), so `make tail-*` works the same every time.
#
# --verbose is opt-in (`make run-polar VERBOSE=1`): at DEBUG level these
# processes log raw per-beat HR/PPI values (health data) plus bleak's D-Bus
# dump (paired-device MACs, adapter address). logs/ is chmod 700 and each
# log and pid file chmod 600, so they stay owner-readable.
run-polar:
	@mkdir -p logs && chmod 700 logs
	@touch logs/polar.log && chmod 600 logs/polar.log
	@.venv/bin/python -m afferent.polar_poller $(if $(VERBOSE),--verbose) > logs/polar.log 2>&1 & echo $$! > logs/polar.pid
	@chmod 600 logs/polar.pid
	@echo "polar_poller running (pid $$(cat logs/polar.pid)) -- logs/polar.log"

stop-polar:
	kill $$(cat logs/polar.pid) && rm -f logs/polar.pid

tail-polar:
	tail -f logs/polar.log

run-co2:
	@mkdir -p logs && chmod 700 logs
	@touch logs/co2.log && chmod 600 logs/co2.log
	@.venv/bin/python -m afferent.co2_poller $(if $(VERBOSE),--verbose) > logs/co2.log 2>&1 & echo $$! > logs/co2.pid
	@chmod 600 logs/co2.pid
	@echo "co2_poller running (pid $$(cat logs/co2.pid)) -- logs/co2.log"

stop-co2:
	kill $$(cat logs/co2.pid) && rm -f logs/co2.pid

tail-co2:
	tail -f logs/co2.log

run-aggregator:
	@mkdir -p logs && chmod 700 logs
	@touch logs/aggregator.log && chmod 600 logs/aggregator.log
	@.venv/bin/python -m afferent.aggregator $(if $(VERBOSE),--verbose) > logs/aggregator.log 2>&1 & echo $$! > logs/aggregator.pid
	@chmod 600 logs/aggregator.pid
	@echo "aggregator running (pid $$(cat logs/aggregator.pid)) -- logs/aggregator.log"

stop-aggregator:
	kill $$(cat logs/aggregator.pid) && rm -f logs/aggregator.pid

tail-aggregator:
	tail -f logs/aggregator.log
