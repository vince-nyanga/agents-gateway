.PHONY: dev test test-e2e lint check typecheck

dev:  ## Run the test project (standalone)
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	uv run --directory examples/test-project python app.py

dev-mounted:  ## Run the test project (mounted sub-app at /ai)
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	uv run --directory examples/test-project python app_mounted.py

test:  ## Run library tests (excludes e2e)
	uv run pytest -m "not e2e"

test-e2e:  ## Run e2e tests (requires GEMINI_API_KEY)
	uv run pytest -m e2e -v

lint:  ## Lint with ruff
	uv run ruff check src/ tests/

typecheck:  ## Type check with mypy
	uv run mypy src/

check: lint typecheck test  ## Run all checks
