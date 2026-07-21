from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_admin
from app.db.connection import get_db
from app.models.schemas import AppSettings, AppSettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


async def _get_settings_document():
    db = get_db()
    settings_doc = await db.app_settings.find_one({"_id": "singleton"})
    if not settings_doc:
        settings_doc = {
            "_id": "singleton",
            "active_plan": "free",
            "allow_paid_overage": False,
            "updated_at": datetime.utcnow(),
        }
        await db.app_settings.insert_one(settings_doc)
    return settings_doc


@router.get("")
async def get_settings(current_user: dict = Depends(get_current_admin)):
    settings_doc = await _get_settings_document()
    settings_doc["id"] = str(settings_doc["_id"])
    return settings_doc


@router.put("")
async def update_settings(settings_in: AppSettingsUpdate, current_user: dict = Depends(get_current_admin)):
    db = get_db()
    update_payload = {}

    if settings_in.active_plan is not None:
        update_payload["active_plan"] = settings_in.active_plan
    if settings_in.allow_paid_overage is not None:
        update_payload["allow_paid_overage"] = settings_in.allow_paid_overage

    if not update_payload:
        raise HTTPException(status_code=400, detail="No settings provided")

    update_payload["updated_at"] = datetime.utcnow()

    await db.app_settings.update_one(
        {"_id": "singleton"},
        {"$set": update_payload},
        upsert=True,
    )

    settings_doc = await db.app_settings.find_one({"_id": "singleton"})
    settings_doc["id"] = str(settings_doc["_id"])
    return settings_doc
