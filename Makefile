# Thin wrappers. The work is in Python so it runs the same on Windows, where
# there is no make: run the command on the right-hand side directly.

PYTHON ?= python

.PHONY: eval eval-calc test

## Score every eval case end to end and write evals/REPORT.md. Fails on regression.
eval:
	$(PYTHON) -m evals.run

## The engine alone against verified inputs: no OCR, no model, seconds not minutes.
eval-calc:
	$(PYTHON) -m evals.run --calc-only

## Unit, property and harness tests - what CI runs.
test:
	cd backend && $(PYTHON) -m pytest -q
