.PHONY: up down logs test test-backend test-web e2e dev-backend dev-web lint

up:            ## Build and start the stack (http://localhost:8000)
	docker compose up --build -d
	@echo "Dashboard: http://localhost:8000"

down:          ## Stop the stack (data is kept)
	docker compose down

logs:
	docker compose logs -f app

test: test-backend test-web   ## All unit and integration tests

test-backend:  ## Backend tests against a throwaway PostgreSQL (local binaries or TEST_DATABASE_URL)
	cd backend && uv run pytest -q

test-web:
	cd apps/web && npm test

e2e:           ## Browser end-to-end test (builds the dashboard, starts a temp server)
	cd tests/e2e && npm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy command_center
	cd apps/web && npm run lint && npm run typecheck

dev-backend:   ## API with auto-reload on :8000 (needs DATABASE_URL and OWNER_PASSWORD)
	cd backend && ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000 \
	  sh -c 'uv run command-center migrate && uv run uvicorn command_center.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers'

dev-web:       ## Dashboard dev server on :3000, proxying /api to :8000
	cd apps/web && NEXT_PUBLIC_WS_BASE=ws://localhost:8000 npm run dev
