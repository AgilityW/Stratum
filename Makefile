.PHONY: pipeline daily weekly monthly quarterly yearly
.PHONY: release deploy deploy-health rollback run-deployed-daily
.PHONY: test test-unit test-schema test-data test-cov test-cov-html clean

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
DOMAIN ?= storage
DATE ?= $(shell date +%F)
OUTPUT_DIR ?=
PIPELINE_ARGS ?=
ENV ?= production
VERSION ?=
DEPLOY_ROOT ?= $(HOME)/stratum/deployments
DEPLOY_CONFIG ?= config.yaml

PIPELINE_CMD = $(PYTHON) stratum/orchestrator/pipeline.py --domain $(DOMAIN) --date $(DATE)
TIMESCALE_CMD = $(PYTHON) stratum/orchestrator/pipeline.py --domain $(DOMAIN) --date $(DATE) --timescale
ifneq ($(strip $(OUTPUT_DIR)),)
PIPELINE_CMD += --output-dir $(OUTPUT_DIR)
TIMESCALE_CMD += --output-dir $(OUTPUT_DIR)
endif

# ── Pipeline ──────────────────────────────────────────────

# Full daily pipeline. Override with DOMAIN=robot DATE=YYYY-MM-DD OUTPUT_DIR=/tmp/out.
pipeline daily:
	$(PIPELINE_CMD) $(PIPELINE_ARGS)

# ── Deployment ─────────────────────────────────────────────

release:
	@test -n "$(VERSION)" || (echo "VERSION is required, e.g. make release VERSION=v0.7.0" && exit 2)
	scripts/release.sh $(VERSION)

deploy:
	@test -n "$(VERSION)" || (echo "VERSION is required, e.g. make deploy VERSION=v0.7.0" && exit 2)
	@test -n "$(OUTPUT_DIR)" || (echo "OUTPUT_DIR is required for deployment" && exit 2)
	scripts/deploy.sh --version $(VERSION) --env $(ENV) --domain $(DOMAIN) --root $(DEPLOY_ROOT) --config $(DEPLOY_CONFIG) --output-dir $(OUTPUT_DIR)

deploy-health:
	scripts/healthcheck.sh --root $(DEPLOY_ROOT) --env $(ENV)

rollback:
	@test -n "$(VERSION)" || (echo "VERSION is required, e.g. make rollback VERSION=v0.6.0" && exit 2)
	scripts/rollback.sh --root $(DEPLOY_ROOT) --env $(ENV) --version $(VERSION)

run-deployed-daily:
	scripts/run_daily.sh --root $(DEPLOY_ROOT) --env $(ENV) --domain $(DOMAIN) --date $(DATE) $(PIPELINE_ARGS)

# Higher-scale runners are not first-class in the current orchestrator.
weekly:
	$(TIMESCALE_CMD) weekly $(PIPELINE_ARGS)

monthly:
	$(TIMESCALE_CMD) monthly $(PIPELINE_ARGS)

quarterly:
	$(TIMESCALE_CMD) quarterly $(PIPELINE_ARGS)

yearly:
	$(TIMESCALE_CMD) yearly $(PIPELINE_ARGS)

# ── Testing ───────────────────────────────────────────────

# Default: run all tests
test:
	$(PYTHON) -m pytest tests/ stratum/stages/ stratum/subsystems/ stratum/source_trace/ stratum/signal_bursts/ -v

# Only focused unit tests
test-unit:
	$(PYTHON) -m pytest tests/test_search.py stratum/stages/ stratum/subsystems/ stratum/source_trace/ stratum/signal_bursts/ -v

# Only schema/contract validation tests
test-schema:
	$(PYTHON) -m pytest tests/test_contracts.py tests/modules/test_schemas.py -v

# Data integrity + infra + module tests
test-data:
	$(PYTHON) -m pytest tests/infra/ tests/modules/ -v

# Only module-level tests (contract + dependency + logic)
test-modules:
	$(PYTHON) -m pytest tests/modules/ -v

# Coverage report (terminal)
test-cov:
	$(PYTHON) -m pytest tests/ stratum/stages/ stratum/subsystems/ stratum/source_trace/ stratum/signal_bursts/ --cov --cov-report=term-missing

# Coverage report (HTML)
test-cov-html:
	$(PYTHON) -m pytest tests/ stratum/stages/ stratum/subsystems/ stratum/source_trace/ stratum/signal_bursts/ --cov --cov-report=html
	@echo "Open htmlcov/index.html"

# Run specific test file
# Usage: make test-file FILE=tests/test_search.py
test-file:
	$(PYTHON) -m pytest $(FILE) -v

# Clean up artifacts
clean:
	rm -rf htmlcov/ .coverage .pytest_cache/ tests/__pycache__ tests/**/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '.DS_Store' -delete 2>/dev/null || true
