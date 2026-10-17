.PHONY: dev-setup test test-fast lint format pdf-preview schema-validate eval eval-update bench clean install audit lock

dev-setup:
	if [ -f requirements.lock ]; then pip install -c requirements.lock -e ".[dev]"; else pip install -e ".[dev]"; fi
	pre-commit install

lock:
	uv lock
	uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.lock

install:
	pip install -e .

test:
	pytest --cov --cov-report=term-missing

test-fast:
	pytest -x -q

eval:
	python scripts/eval.py

eval-update:
	python scripts/eval.py --update

bench:
	python benchmarks/perf.py

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

schema-validate:
	python -c "import json, jsonschema; [(jsonschema.Draft202012Validator.check_schema(s), print('Schema valid:', p, s['\$$id'])) for p in ('rmf-1.0.0', 'rmf-1.1.0') for s in [json.load(open(f'src/riskforge/_data/schemas/{p}.schema.json'))]]"

pdf-preview:
	riskforge init --name "Test System" --sys-version "1.0" --purpose "Test" --provider "AiExponent" --category essential_services --non-interactive 2>/dev/null || true
	@echo "Run riskforge assess then riskforge export --format pdf to preview"

clean:
	rm -rf dist/ build/ .eggs/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

audit:
	pip-audit
