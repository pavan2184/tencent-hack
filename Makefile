SHELL := /bin/bash
COMPOSE := docker compose
LIB ?= groundedness

.PHONY: help up down reset build logs ps migrate seed test test-app test-lib lint fmt typecheck dev-api dev-web smoke mcp-smoke lock

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the full stack (postgres, redis, migrate, api, worker, beat, frontend)
	$(COMPOSE) up --build -d
	@echo "Waiting for api to be healthy..."
	@for i in $$(seq 1 60); do \
	  if curl -fs http://localhost:8000/healthz >/dev/null 2>&1; then echo "api healthy"; exit 0; fi; sleep 2; done; \
	  echo "api did not become healthy in time"; $(COMPOSE) logs api --tail=50; exit 1

down: ## Stop the stack
	$(COMPOSE) down

reset: ## Stop the stack and delete volumes (database, redis, uploads)
	$(COMPOSE) down -v

build: ## Build images
	$(COMPOSE) build

logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100

ps: ## Service status
	$(COMPOSE) ps

migrate: ## Apply SQL migrations (infra/postgres/migrations)
	$(COMPOSE) run --rm migrate

seed: ## Load demo personas, policies and the synthetic corpus
	$(COMPOSE) run --rm -e ROLE=seed api

test: ## Run backend app + all three library test suites (offline, mock mode)
	cd backend && uv run pytest -q

test-app: ## Run only the backend app tests
	cd backend && uv run pytest -q app/tests

test-lib: ## Run one library's tests: make test-lib LIB=freshness
	cd backend && uv run pytest -q libs/$(LIB)/tests

lint: ## Ruff (backend + libs) and frontend lint
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint --if-present

fmt: ## Auto-format backend + libs
	cd backend && uv run ruff format . && uv run ruff check . --fix

typecheck: ## Frontend typecheck
	cd frontend && npm run typecheck

dev-api: ## Run the API locally with reload (expects local postgres/redis or in-memory settings)
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-web: ## Run the Next.js dev server
	cd frontend && npm run dev

smoke: ## End-to-end curl smoke test against a running stack
	bash scripts/smoke.sh

mcp-smoke: ## Initialize + list tools against the MCP endpoint
	bash scripts/smoke.sh mcp

lock: ## Regenerate lockfiles
	cd backend && uv lock
	cd frontend && npm install --package-lock-only
