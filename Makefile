.PHONY: test test-unit test-schema test-data test-cov test-cov-html clean
.PHONY: daily weekly monthly quarterly yearly

# ── Pipeline ──────────────────────────────────────────────

# Full daily: collect → render → PDF to WeChat
daily:
	hermes cron run 102deb18b91e

# Weekly brief (Sunday)
weekly:
	hermes cron run 46f1a9a31ab2

# Monthly brief (1st)
monthly:
	hermes cron run 505ab3342070

# Quarterly review
quarterly:
	hermes cron run bce084d381c8

# Yearly review
yearly:
	hermes cron run 97fb7165be35

# ── Testing ───────────────────────────────────────────────

# Default: run all tests
test:
	python3 -m pytest tests/ -v

# Only unit tests (source-graph-engine)
test-unit:
	python3 -m pytest tests/unit/ -v

# Only schema validation tests
test-schema:
	python3 -m pytest tests/schema/ -v

# Data integrity + infra + module tests
test-data:
	python3 -m pytest tests/infra/ tests/modules/ -v

# Only module-level tests (contract + dependency + logic)
test-modules:
	python3 -m pytest tests/modules/ -v

# Coverage report (terminal)
test-cov:
	python3 -m pytest tests/ --cov --cov-report=term-missing

# Coverage report (HTML)
test-cov-html:
	python3 -m pytest tests/ --cov --cov-report=html
	@echo "Open htmlcov/index.html"

# Run specific test file
# Usage: make test-file FILE=tests/unit/test_graph.py
test-file:
	python3 -m pytest $(FILE) -v

# Clean up artifacts
clean:
	rm -rf htmlcov/ .coverage .pytest_cache/ tests/__pycache__ tests/**/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '.DS_Store' -delete 2>/dev/null || true
