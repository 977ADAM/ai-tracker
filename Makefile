.DEFAULT_GOAL := help

.PHONY: help install ruff backend frontend frontend-prod build check types lint lint-fix format format-check docker-build docker-up docker-down docker-logs

help:
	@echo "install  Install Python and Node.js dependencies"
	@echo "backend       Start the Python API"
	@echo "frontend      Start the web interface for development"
	@echo "frontend-prod Start the built web interface"
	@echo "build         Build the web interface"
	@echo "types         Check Svelte and TypeScript"
	@echo "lint          Check the frontend with ESLint"
	@echo "lint-fix      Apply the ESLint fixes"
	@echo "format        Format the frontend with Prettier"
	@echo "format-check  Check the Prettier formatting"
	@echo "check         Types, formatting, and lint in one go"
	@echo "docker-up     Build and start the whole app with docker compose"
	@echo "docker-down   Stop the compose stack"
	@echo "docker-logs   Follow the logs of the compose stack"

install:
	cd backend && uv sync
	cd frontend && npm ci

ruff:
	cd backend && ruff check --fix .
	
backend:
	@cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

frontend-prod:
	cd frontend && HOST=127.0.0.1 PORT=5173 ORIGIN=http://127.0.0.1:5173 node build/index.js

build:
	cd frontend && npm run build

check: types format-check lint

types:
	cd frontend && npm run check

lint:
	cd frontend && npm run lint

lint-fix:
	cd frontend && npm run lint:fix

format:
	cd frontend && npm run format

format-check:
	cd frontend && npm run format:check

docker-build:
	docker compose build

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
