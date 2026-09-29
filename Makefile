.PHONY: install dev test lint serve clean selftest example

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

lint:
	ruff check src/ tests/ examples/
	mypy src/keyforge/

selftest: example
	@echo "==> Init DB"
	keyforge init --db keyforge.db
	@echo "==> Create key"
	KEY=$$(keyforge create --name "selftest" --db keyforge.db --prefix kf_test | grep "kf_test" | tr -d ' '); \
	echo "Key: $$KEY"; \
	echo "==> Verify key"; \
	keyforge verify "$$KEY" --db keyforge.db; \
	echo "==> List keys"; \
	keyforge list --db keyforge.db

example:
	@echo "Start example: uvicorn examples.fastapi_app.main:app --port 8000"

serve:
	keyforge serve

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ htmlcov/ .coverage
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -f keyforge.db
