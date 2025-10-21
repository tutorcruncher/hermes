.PHONY: install install-dev test lint format clean run migrate reset-db setup setup-fields setup-admins

install:
	uv sync

install-dev:
	uv sync --all-groups

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ --cov=app --cov-report=html --cov-report=term-missing

lint:
	uv run ruff check app/ tests/

format:
	uv run ruff format app/ tests/
	uv run ruff check app/ tests/ --fix

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf htmlcov/ .coverage

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate:
	uv run alembic upgrade head

migrate-create:
	uv run alembic revision --autogenerate -m "$(msg)"

reset-db:
	dropdb hermes || true
	createdb hermes
	uv run alembic upgrade head

setup:
	uv run python system_setup.py setup

setup-fields:
	uv run python system_setup.py fields

setup-admins:
	uv run python system_setup.py admins


