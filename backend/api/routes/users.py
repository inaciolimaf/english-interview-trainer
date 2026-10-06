from fastapi import APIRouter, Depends

from api.db.models import User
from api.deps import get_current_user

router = APIRouter()


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": str(user.id), "display_name": user.display_name, "email": user.email}
