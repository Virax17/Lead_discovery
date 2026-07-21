from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.config.countries import COUNTRIES

router = APIRouter(prefix="/countries", tags=["countries"])


@router.get("")
async def list_countries(current_user: str = Depends(get_current_user)):
    return COUNTRIES
