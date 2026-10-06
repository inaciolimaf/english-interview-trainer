import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.analysis.worker import AnalysisWorker
from api.realtime import ws
from api.realtime.ws import abandon_stale_sessions
from api.realtime.model_client import ModelClient
from api.routes import coach, dashboard, drills, errors, health, jobs, resumes, sessions, settings, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.models = ModelClient()
    app.state.analysis = AnalysisWorker(app.state.models)
    app.state.analysis.start()
    try:
        await abandon_stale_sessions()
    except Exception:  # noqa: BLE001 — the DB may be down; /health reports it
        logging.getLogger(__name__).exception("stale session cleanup failed")
    yield
    await app.state.analysis.stop()
    await app.state.models.close()


app = FastAPI(title="English Interview Trainer API", lifespan=lifespan)

app.include_router(health.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(resumes.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(errors.router, prefix="/api")
app.include_router(drills.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(coach.router, prefix="/api")
app.include_router(ws.router)
