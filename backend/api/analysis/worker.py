"""Runs turn analyses one at a time in the background (never on the conversation path)."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from api.analysis.pipeline import TurnJob, analyze_turn
from api.db.models import InterviewSession, Turn
from api.db.session import SessionLocal
from api.drills.generate import generate_drills
from api.llm.client import LLMClient
from api.realtime.model_client import ModelClient
from api.reports.report import generate_report

log = logging.getLogger("analysis")


@dataclass
class ReportJob:
    """Queued after the session's turn analyses (FIFO), so the report sees every error."""

    session_id: uuid.UUID
    llm: LLMClient | None
    drills: bool = True


async def run_report(job: ReportJob) -> None:
    await generate_report(job.session_id, job.llm)
    if job.drills:
        async with SessionLocal() as db:
            session = await db.get(InterviewSession, job.session_id)
            counts = await generate_drills(db, job.session_id, session.user_id, job.llm)
        log.info("session %s: report done, drills %s", job.session_id, counts)


class AnalysisWorker:
    def __init__(self, models: ModelClient) -> None:
        self.models = models
        self.queue: asyncio.Queue[TurnJob | ReportJob] = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.idle = asyncio.Event()
        self.idle.set()

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()

    def submit(self, job: TurnJob | ReportJob) -> None:
        self.idle.clear()
        self.queue.put_nowait(job)

    async def _run(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                if isinstance(job, ReportJob):
                    await run_report(job)
                else:
                    await analyze_turn(job, self.models)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                if isinstance(job, ReportJob):
                    log.exception("report of session %s failed", job.session_id)
                else:
                    log.exception("analysis of turn %s failed", job.turn_id)
                    async with SessionLocal() as db:
                        turn = await db.get(Turn, job.turn_id)
                        if turn:
                            turn.analysis_status = "failed"
                            await db.commit()
            finally:
                if isinstance(job, TurnJob):
                    job.pcm = b""
                if self.queue.empty():
                    self.idle.set()
