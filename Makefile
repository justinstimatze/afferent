.PHONY: check test typecheck lint

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
