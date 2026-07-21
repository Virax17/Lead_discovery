from fastapi import APIRouter, Depends
from app.api.auth import get_current_user_profile
from app.services.quota_tracker import get_current_usage

router = APIRouter(prefix="/quota", tags=["quota"])

@router.get("/status")
async def get_quota_status(current_user: dict = Depends(get_current_user_profile)):
    return await get_current_usage(current_user["username"])
