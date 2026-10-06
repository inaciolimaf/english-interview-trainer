from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.constants import DEFAULT_USER_ID
from api.db.models import User
from api.db.session import get_db


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    """Return the current user. Single-user for now: always the seeded default user.

    Swap this for real authentication later; routes only depend on this function.
    """
    user = await db.get(User, DEFAULT_USER_ID)
    if user is None:
        raise HTTPException(503, "Default user not found — run `python scripts/seed.py`")
    return user
