models: cd backend && .venv/bin/uvicorn model_server.main:app --port 8001
api: cd backend && .venv/bin/python scripts/wait_for.py http://localhost:8001/health && .venv/bin/uvicorn api.main:app --port 8000 --reload
web: cd frontend && npm run dev
