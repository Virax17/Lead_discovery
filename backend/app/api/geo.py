from fastapi import APIRouter, Depends, Query

from app.api.auth import get_current_user
from app.config.geo import list_cities, list_states

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/states")
async def get_states(country_code: str = Query(...), current_user: str = Depends(get_current_user)):
    return list_states(country_code)


@router.get("/cities")
async def get_cities(
    country_code: str = Query(...),
    state_code: str = Query(...),
    current_user: str = Depends(get_current_user),
):
    return list_cities(country_code, state_code)
