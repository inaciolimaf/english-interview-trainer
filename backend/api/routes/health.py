import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        database = {"ok": True}
    except Exception as exc:  # noqa: BLE001 — report any DB failure to the UI
        database = {"ok": False, "error": str(exc)}

    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(f"{get_settings().model_server_url}/health")
            model_server = {"ok": r.is_success, **(r.json() if r.is_success else {})}
    except Exception as exc:  # noqa: BLE001
        model_server = {"ok": False, "error": str(exc) or type(exc).__name__}

    return {"api": {"ok": True}, "database": database, "model_server": model_server}
