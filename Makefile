# English Interview Trainer — dev shortcuts (see README.md)
BACKEND := backend
VENV := $(BACKEND)/.venv/bin

.PHONY: install db-up db-down migrate seed models api web dev spike test calibrate

install:
	cd $(BACKEND) && uv venv --python 3.12 .venv && uv pip install -e ".[models,dev]"
	cd frontend && npm install

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	cd $(BACKEND) && .venv/bin/alembic upgrade head

seed:
	cd $(BACKEND) && .venv/bin/python scripts/seed.py

models:
	cd $(BACKEND) && .venv/bin/uvicorn model_server.main:app --port 8001

api:
	cd $(BACKEND) && .venv/bin/uvicorn api.main:app --port 8000 --reload

web:
	cd frontend && npm run dev

# db + model server + api + web; the API waits for the model server's /health
dev: db-up
	PYTHONUNBUFFERED=1 $(VENV)/honcho start

spike:
	cd $(BACKEND) && .venv/bin/python scripts/spike_models.py

calibrate:
	cd $(BACKEND) && .venv/bin/python scripts/calibrate_phonemes.py

test:
	cd $(BACKEND) && .venv/bin/pytest
	cd frontend && npm test
