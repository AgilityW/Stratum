.PHONY: test test-unit test-schema test-data test-cov test-cov-html clean

# Default: run all tests
test:
	python -m pytest tests/ -v

# Only unit tests (source-graph-engine)
test-unit:
	python -m pytest tests/unit/ -v -m unit

# Only schema validation tests
test-schema:
	python -m pytest tests/schema/ -v -m schema

# Only data integrity tests
test-data:
	python -m pytest tests/data/ -v -m data

# Coverage report (terminal)
test-cov:
	python -m pytest tests/ --cov --cov-report=term-missing

# Coverage report (HTML)
test-cov-html:
	python -m pytest tests/ --cov --cov-report=html
	@echo "Open htmlcov/index.html"

# Run specific test file
# Usage: make test-file FILE=tests/unit/test_graph.py
test-file:
	python -m pytest $(FILE) -v

# Clean up artifacts
clean:
	rm -rf htmlcov/ .coverage .pytest_cache/ tests/__pycache__ tests/**/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
