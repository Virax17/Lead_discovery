from datetime import datetime
from app.db.connection import get_db
from app.config.quota import PLACE_DETAILS_MONTHLY_FREE_LIMIT, QUOTA_WARNING_THRESHOLD
from app.models.schemas import AppSettings

def _current_month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")

async def check_quota_before_call() -> str:
    db = get_db()
    year_month = _current_month_str()
    record = await db.api_usage_monthly.find_one({"_id": year_month})
    settings = await db.app_settings.find_one({"_id": "singleton"})
    
    calls = record.get("place_details_calls", 0) if record else 0
    allow_overage = settings.get("allow_paid_overage", False) if settings else False
    
    if calls >= PLACE_DETAILS_MONTHLY_FREE_LIMIT and not allow_overage:
        return 'BLOCKED'
    elif calls >= QUOTA_WARNING_THRESHOLD:
        return 'WARNING'
    else:
        return 'OK'

async def increment_usage() -> None:
    db = get_db()
    year_month = _current_month_str()
    await db.api_usage_monthly.update_one(
        {"_id": year_month},
        {
            "$inc": {"place_details_calls": 1},
            "$set": {"updated_at": datetime.utcnow()}
        },
        upsert=True
    )

async def get_current_usage() -> dict:
    db = get_db()
    year_month = _current_month_str()
    record = await db.api_usage_monthly.find_one({"_id": year_month})
    settings = await db.app_settings.find_one({"_id": "singleton"})
    
    calls = record.get("place_details_calls", 0) if record else 0
    app_settings = AppSettings.model_validate(settings) if settings else AppSettings(updated_at=datetime.utcnow())
    allow_overage = app_settings.allow_paid_overage
    active_plan = app_settings.active_plan
    
    status = "OK"
    if calls >= PLACE_DETAILS_MONTHLY_FREE_LIMIT and not allow_overage:
        status = "BLOCKED"
    elif calls >= QUOTA_WARNING_THRESHOLD:
        status = "WARNING"
        
    return {
        "year_month": year_month,
        "calls_used": calls,
        "calls_remaining": max(0, PLACE_DETAILS_MONTHLY_FREE_LIMIT - calls) if not allow_overage else None,
        "status": status,
        "active_plan": active_plan,
        "allow_paid_overage": allow_overage,
        "quota_warning_threshold": QUOTA_WARNING_THRESHOLD,
        "quota_block_threshold": PLACE_DETAILS_MONTHLY_FREE_LIMIT,
        "overage_calls": max(0, calls - PLACE_DETAILS_MONTHLY_FREE_LIMIT),
        "overage_cost_estimate": max(0, calls - PLACE_DETAILS_MONTHLY_FREE_LIMIT) * 0.02
    }
