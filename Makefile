RUN ?= pipenv run

.PHONY: check lint type test wheel

check: lint type test

lint:
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests

type:
	$(RUN) mypy

test:
	$(RUN) pytest

wheel:
	rm -rf dist
	$(RUN) python -m build --wheel
