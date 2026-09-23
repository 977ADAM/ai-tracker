.DEFAULT_GOAL := help

.PHONY: help install backend frontend frontend-prod build check test verify

help:
	@echo "install  Install Python and Node.js dependencies"
	@echo "backend       Start the Python API"
	@echo "frontend      Start the web interface for development"
	@echo "frontend-prod Start the built web interface"
	@echo "build         Build the web interface"
	@echo "check         Check Svelte and TypeScript"
	@echo "test          Run Node.js and Python tests"
	@echo "verify        Run tests, checks, and build"

install:
	cd backend && uv sync
	cd frontend && npm ci

backend:
	cd backend && uv run ai-tracker

frontend:
	cd frontend && npm run dev

frontend-prod:
	cd frontend && HOST=127.0.0.1 PORT=5173 ORIGIN=http://127.0.0.1:5173 node build/index.js

build:
	cd frontend && npm run build

check:
	cd frontend && npm run check

test:
	cd frontend && npm test
	cd backend && uv run --with pytest pytest -q

verify: test check build
