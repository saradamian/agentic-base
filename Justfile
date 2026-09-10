set dotenv-load

default: check

test:
    uv run pytest --cov --cov-report=term-missing

lint:
    uv run ruff format --check .
    uv run ruff check .

mypy:
    uv run mypy src tests

check: lint mypy test

fix:
    uv run ruff format .
    uv run ruff check . --fix

run:
    uv run uvicorn --app-dir src app.main:get_app --factory --port 8080 --reload

suspend cluster:
    flux suspend helmrelease --context {{cluster}} -n services-agentic-base agentic-base
resume cluster:
    flux resume helmrelease --context {{cluster}} -n services-agentic-base agentic-base
reconcile cluster:
    flux reconcile helmrelease --context {{cluster}} -n services-agentic-base agentic-base

docs:
    uv run mkdocs serve
