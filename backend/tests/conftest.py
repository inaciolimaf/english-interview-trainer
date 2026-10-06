"""Shared fixtures: the real API served by uvicorn in a thread (so the async DB engine
lives in one event loop), a scripted fake LLM, and cleanup of rows created by tests.

Tests never touch the database or data folder you use: before anything from ``api`` is
imported, DATABASE_URL points to a separate ``trainer_test`` database (created, migrated and
seeded here, with the phoneme calibration copied from the main database) and DATA_DIR to a
temporary folder.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path as _Path

import asyncpg as _asyncpg


def _isolate_test_environment() -> None:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class _Env(BaseSettings):
        model_config = SettingsConfigDict(env_file=_Path(__file__).resolve().parents[2] / ".env", extra="ignore")
        database_url: str = "postgresql+asyncpg://trainer:trainer@localhost:5432/trainer"

    main_url = _Env().database_url
    base, _, main_db = main_url.rpartition("/")
    test_url = f"{base}/trainer_test"
    plain = lambda url: url.replace("postgresql+asyncpg://", "postgresql://")  # noqa: E731

    async def prepare() -> None:
        try:
            admin = await _asyncpg.connect(plain(main_url))
        except Exception:  # noqa: BLE001 — no database: DB tests skip themselves
            return
        try:
            if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = 'trainer_test'"):
                await admin.execute("CREATE DATABASE trainer_test")
            calibration = await admin.fetch("SELECT phoneme, accent, native_mean, native_std, p05, n_samples FROM phoneme_calibration")
        finally:
            await admin.close()
        env = {**os.environ, "DATABASE_URL": test_url}
        backend = _Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env, check=True,
                       capture_output=True)
        subprocess.run([sys.executable, "scripts/seed.py"], cwd=backend, env=env, check=True, capture_output=True)
        test = await _asyncpg.connect(plain(test_url))
        try:
            await test.execute("DELETE FROM phoneme_calibration")
            await test.executemany(
                "INSERT INTO phoneme_calibration (id, phoneme, accent, native_mean, native_std, p05, n_samples) "
                "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)", [tuple(r.values()) for r in calibration])
        finally:
            await test.close()

    import asyncio as _asyncio

    _asyncio.run(prepare())
    os.environ["DATABASE_URL"] = test_url
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="eit-test-data-")


_isolate_test_environment()

import asyncio  # noqa: E402
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
import pytest
import uvicorn

from api.config import get_settings
from api.db.constants import DEFAULT_USER_ID
from api.llm.client import get_llm
from api.main import app

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
CLEANUP_TABLES = ("interview_sessions", "job_postings", "resumes")
created: dict[str, list[str]] = {t: [] for t in CLEANUP_TABLES}


def is_up(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).is_success
    except httpx.HTTPError:
        return False


class FakeLLM:
    """Scripted LLM: ``replies`` for streaming (last one repeats), ``json_replies`` for JSON mode."""

    def __init__(self, replies: list[str] | None = None, json_replies: list[str] | None = None,
                 json_router: Callable[[list[dict]], str] | None = None) -> None:
        self.replies = replies or ["Okay."]
        self.json_replies = list(json_replies or [])
        self.json_router = json_router  # answers JSON requests by content (for parallel calls)
        self.calls: list[list[dict]] = []
        self.json_calls: list[list[dict]] = []

    async def stream(self, messages, on_retry=None, max_tokens=400):
        self.calls.append(messages)
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        for word in text.split(" "):
            await asyncio.sleep(0.01)
            yield word + " "

    async def complete_json(self, messages) -> str:
        self.json_calls.append(messages)
        if self.json_router:
            return self.json_router(messages)
        return self.json_replies.pop(0)


@pytest.fixture
def use_llm() -> Callable[[FakeLLM], FakeLLM]:
    def install(llm: FakeLLM) -> FakeLLM:
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    yield install
    app.dependency_overrides.pop(get_llm, None)


def track(table: str, row_id: str) -> str:
    created[table].append(row_id)
    return row_id


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


async def db_fetchval(sql: str, *args):
    """Direct DB access for test setup/asserts (separate from the app's engine)."""
    conn = await asyncpg.connect(_dsn())
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


def wait_worker_idle(timeout: float = 30) -> None:
    """Background analyses/reports of earlier tests must finish before rows are deleted."""
    worker = getattr(app.state, "analysis", None)
    deadline = time.time() + timeout
    while worker is not None and not worker.idle.is_set() and time.time() < deadline:
        time.sleep(0.1)


ADJUSTMENT_COLUMNS = ("id", "user_id", "phoneme", "word", "offset", "dismiss_count", "confirm_count",
                      "created_at", "updated_at")


async def snapshot_adjustments() -> list[asyncpg.Record]:
    conn = await asyncpg.connect(_dsn())
    try:
        return await conn.fetch(f"SELECT {', '.join(map(_q, ADJUSTMENT_COLUMNS))} FROM user_phoneme_adjustments")
    finally:
        await conn.close()


async def restore_adjustments_rows(saved: list[asyncpg.Record]) -> None:
    conn = await asyncpg.connect(_dsn())
    try:
        await conn.execute("DELETE FROM user_phoneme_adjustments")
        cols = ", ".join(map(_q, ADJUSTMENT_COLUMNS))
        params = ", ".join(f"${i}" for i in range(1, len(ADJUSTMENT_COLUMNS) + 1))
        for r in saved:
            await conn.execute(f"INSERT INTO user_phoneme_adjustments ({cols}) VALUES ({params})",
                               *(r[c] for c in ADJUSTMENT_COLUMNS))
    finally:
        await conn.close()


def _q(col: str) -> str:
    return f'"{col}"'


async def _cleanup(since: datetime | None = None) -> None:
    conn = await asyncpg.connect(_dsn())
    try:
        if since:  # drills generated in the background from test sessions
            await conn.execute("DELETE FROM drill_sessions WHERE user_id = $1 AND created_at >= $2", DEFAULT_USER_ID, since)
            await conn.execute("DELETE FROM drill_items WHERE user_id = $1 AND created_at >= $2", DEFAULT_USER_ID, since)
        if created["interview_sessions"]:  # error clips: files + rows (they outlive turns by design)
            clips = await conn.fetch(
                "SELECT c.id, c.file_path FROM audio_clips c JOIN turns t ON t.id = c.source_turn_id "
                "WHERE t.session_id = ANY($1::uuid[])", created["interview_sessions"])
            for row in clips:
                Path(row["file_path"]).unlink(missing_ok=True)
            await conn.execute("DELETE FROM audio_clips WHERE id = ANY($1::uuid[])", [r["id"] for r in clips])
        if created["resumes"]:  # uploaded PDFs live on disk, not only in the table
            paths = await conn.fetch("SELECT file_path FROM resumes WHERE id = ANY($1::uuid[])", created["resumes"])
            for row in paths:
                Path(row["file_path"]).unlink(missing_ok=True)
        for table in CLEANUP_TABLES:  # sessions first: they reference jobs and resumes
            if created[table]:
                await conn.execute(f"DELETE FROM {table} WHERE id = ANY($1::uuid[])", created[table])
                created[table].clear()
    finally:
        await conn.close()


@pytest.fixture
def fresh_data(server):
    """Remove rows of earlier tests now (for user-wide aggregates such as the dashboard)."""
    wait_worker_idle()
    asyncio.run(_cleanup())


@pytest.fixture(scope="session")
def server():
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not is_up(f"{BASE}/api/health"):
        if time.time() > deadline:
            pytest.skip("API did not start")
        time.sleep(0.2)
    if not httpx.get(f"{BASE}/api/health").json()["database"]["ok"]:
        pytest.skip("database not available")
    started = datetime.now(UTC)
    adjustments = asyncio.run(snapshot_adjustments())
    yield BASE
    wait_worker_idle()
    srv.should_exit = True
    thread.join(timeout=5)
    asyncio.run(_cleanup(since=started))
    asyncio.run(restore_adjustments_rows(adjustments))
