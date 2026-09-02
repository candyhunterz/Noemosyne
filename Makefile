.PHONY: bootstrap check test e2e start stop migrate seed generate-api

PYTHONPATH := apps/api:apps/worker:packages/domain:packages/db:packages/retrieval:packages/testkit
export PYTHONPATH

bootstrap:
	uv sync --all-groups
	pnpm install --frozen-lockfile

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest
	pnpm typecheck
	pnpm build

test:
	uv run pytest

e2e:
	pnpm e2e

start:
	docker compose up --build

stop:
	docker compose down

migrate:
	uv run alembic upgrade head

seed:
	uv run noemosyne-seed import examples/ai-research/seed.yaml

generate-api:
	pnpm generate:api
