from fastapi import APIRouter, Depends
from app.api.auth import get_current_user
from app.services.quota_tracker import get_current_usage

router = APIRouter(prefix="/quota", tags=["quota"])

@router.get("/status")
async def get_quota_status(current_user: str = Depends(get_current_user)):
    return await get_current_usage()
