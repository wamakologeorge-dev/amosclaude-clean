PYTHON ?= python3

.PHONY: help setup build test quality package doctor start stop status logs clean

help:
	@echo "Amosclaud workspace commands"
	@echo "  make setup    Install runtime and development dependencies"
	@echo "  make build    Build Python distribution artifacts"
	@echo "  make test     Run the complete test suite"
	@echo "  make quality  Run formatting, lint, and security checks"
	@echo "  make package  Build and verify release artifacts"
	@echo "  make doctor   Inspect the installed workspace"

setup:
	$(PYTHON) scripts/workspace_task.py setup

build:
	$(PYTHON) scripts/workspace_task.py build

test:
	$(PYTHON) scripts/workspace_task.py test

quality:
	$(PYTHON) scripts/workspace_task.py quality

package:
	$(PYTHON) scripts/workspace_task.py package

doctor start stop status logs:
	$(PYTHON) -m amoscloud_ai.workspace_control $@

clean:
	rm -rf build dist .pytest_cache .mypy_cache .coverage
