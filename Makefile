# FamQuiz developer shortcuts.
#
#   make test      run the suite (no credits, no mail)
#   make test-live run the live tests (spends credits / sends mail)
#   make lint      ruff check
#   make typecheck mypy
#   make build     build the one-file exe (needs requirements-build.txt)

PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest

.PHONY: help test test-live lint typecheck build install-dev clean

help:
	@echo "test        run the test suite (free: live tests are skipped)"
	@echo "test-live   run the live tests (spends Ollama credits / sends mail)"
	@echo "lint        ruff check ."
	@echo "typecheck   mypy app.py routes.py run_famquiz.py"
	@echo "build       build the one-file exe"

test:
	$(PYTEST) -m "not live"

test-live:
	$(PYTEST) -m live

lint:
	ruff check .

typecheck:
	mypy app.py routes.py run_famquiz.py

build:
	$(PYTHON) -m PyInstaller --clean FamQuiz.spec

install-dev:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

clean:
	rm -rf build dist .pytest_cache .coverage htmlcov
	find . -name '__pycache__' -type d -exec rm -rf {} +
