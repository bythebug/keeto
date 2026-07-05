.PHONY: install lint fmt typecheck test test-unit test-integration benchmark clean docs docs-serve

install:
	uv pip install -e ".[dev]"

lint:
	uv run ruff check src tests

fmt:
	uv run ruff format src tests

typecheck:
	uv run pyright

test:
	uv run pytest tests/unit/

test-unit:
	uv run pytest tests/unit/ -v

test-integration:
	uv run pytest tests/integration/ -m integration -v

benchmark:
	uv run pytest tests/benchmarks/ -m benchmark --benchmark-autosave

coverage:
	uv run pytest tests/unit/ --cov=src/keeto --cov-report=term-missing

docs:
	uv run --extra docs mkdocs build

docs-serve:
	uv run --extra docs mkdocs serve

clean:
	rm -rf .venv dist build src/keeto.egg-info .pytest_cache .ruff_cache site
