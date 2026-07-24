PYTHON ?= python3

.PHONY: help setup build test quality package doctor start stop status logs model-init model-train model-serve clean

help:
	@echo "Amosclaud workspace commands"
	@echo "  make setup    Install runtime and development dependencies"
	@echo "  make build    Build Python distribution artifacts"
	@echo "  make test     Run the complete test suite"
	@echo "  make quality  Run formatting, lint, and security checks"
	@echo "  make package  Build and verify release artifacts"
	@echo "  make doctor   Inspect the installed workspace"
	@echo "  make model-init   Create the folder-native model workspace"
	@echo "  make model-train  Train an atomic local checkpoint"
	@echo "  make model-serve  Serve the local model on port 8091"

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

model-init:
	$(PYTHON) -m amosclaud_model.cli init

model-train:
	$(PYTHON) -m amosclaud_model.cli train

model-serve:
	$(PYTHON) -m amosclaud_model.cli serve --host 127.0.0.1 --port 8091

clean:
	rm -rf build dist .pytest_cache .mypy_cache .coverage
