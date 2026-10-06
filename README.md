# English Interview Trainer

Local, single-user web app that runs voice job interviews in English, with phoneme-level
pronunciation feedback. Specs live in [`specs/`](specs/00-overview.md).

- **Frontend:** React + Vite + TypeScript (`frontend/`), http://localhost:5173
- **API:** FastAPI with `--reload` (`backend/api`), port 8000
- **Model server:** FastAPI without reload, holds the AI models (`backend/model_server`), port 8001
- **Database:** PostgreSQL in Docker (the only containerized service)

## Prerequisites

| Tool | Notes |
|---|---|
| Linux + NVIDIA GPU | Driver with CUDA 12/13 support (`nvidia-smi` must work) |
| Docker + Docker Compose | For Postgres only |
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.12 and the backend deps |
| Node.js 20+ and npm | Frontend |
| espeak-ng | Phonemes (`sudo apt install espeak-ng`) |
| make | Shortcuts |

## Install from scratch

```bash
# 1. Environment
cp .env.example .env
#    - set OPENROUTER_API_KEY (LLM = DeepSeek V4.1 Flash via OpenRouter)
#    - if port 5432 is already taken, set POSTGRES_PORT (e.g. 5433) and use the
#      same port in DATABASE_URL

# 2. Dependencies (backend venv with the AI stack + frontend)
make install        # = uv venv + uv pip install -e ".[models,dev]" + npm install

# 3. Database
make db-up          # starts Postgres (docker compose)
make migrate        # alembic upgrade head: creates every table
make seed           # default user/settings, accepted variants, tech vocabulary (idempotent)
make calibrate      # once: downloads LibriSpeech test-clean (~350 MB) and calibrates the
                    # pronunciation thresholds (~2 min on the GPU); data/calibration can be
                    # deleted afterwards

# 4. Run everything
make dev            # db + model server + API (waits for the model server) + web
```

Open http://localhost:5173: the dashboard shows the status of the API, database and model server.

The first run downloads the models (~3 GB) to `~/.cache/huggingface`.

## Commands

| Command | What it does |
|---|---|
| `make db-up` / `make db-down` | Start / stop Postgres |
| `make migrate` | Apply migrations (`alembic upgrade head`) |
| `make seed` | Seed the database (safe to run any number of times) |
| `make models` | Model server only (port 8001, no reload) |
| `make api` | API only (port 8000, `--reload`) |
| `make web` | Vite dev server (HMR) |
| `make dev` | Everything together (via `honcho`, see `Procfile`) |
| `make calibrate` | Native phoneme score calibration → `phoneme_calibration` (idempotent) |
| `make spike` | Model check on the GPU: VRAM + latencies → `docs/spike-report.md` |
| `make test` | Backend + frontend tests. Backend tests use a separate `trainer_test` database and a temporary data folder — your interviews are never touched |

New migration after changing `backend/api/db/models.py`:

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "describe change"
```

## Layout

```
backend/   api/ (business logic), model_server/ (models), scripts/, alembic/, tests/
frontend/  src/pages, src/api, src/audio, src/realtime
data/      audio clips, uploads, calibration corpus (git-ignored)
docs/      spike report
specs/     specifications
```
