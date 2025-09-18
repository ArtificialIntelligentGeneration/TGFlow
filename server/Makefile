PY=python3
PIP=pip3

.PHONY: run dev migrate upgrade downgrade seed fmt lint typecheck test test-load openapi load-rps

run:
	uvicorn app.main:app --reload --port 8000

dev:
	docker compose up --build

migrate:
	alembic -c alembic.ini revision --autogenerate -m "auto"

upgrade:
	alembic -c alembic.ini upgrade head

downgrade:
	alembic -c alembic.ini downgrade -1

seed:
	$(PY) scripts/seed.py

fmt:
	ruff fix . || true
	black . || true

lint:
	ruff check .

typecheck:
	mypy app || true

test:
	pytest -q

test-load:
	$(PY) scripts/load_test_basic.py

load-rps:
	BASE_URL=http://127.0.0.1:8000 WARMUP_SEC=60 PLATEAU_SEC=900 RPS=20 THREADS=4 $(PY) scripts/load_test_rps.py

openapi:
	@echo "TODO: add openapi lint (e.g., spectral)"


