from datetime import datetime
from app.db.connection import get_db
from app.config.quota import PLACE_DETAILS_MONTHLY_FREE_LIMIT, QUOTA_WARNING_THRESHOLD
from app.models.schemas import AppSettings
from app.services.users import get_current_month_usage, get_user_by_username, get_user_usage_summary, increment_user_usage

def _current_month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")

async def check_quota_before_call(username: str | None = None) -> str:
    db = get_db()
    year_month = _current_month_str()
    record = await db.api_usage_monthly.find_one({"_id": year_month})
    settings = await db.app_settings.find_one({"_id": "singleton"})
    
    calls = record.get("place_details_calls", 0) if record else 0
    allow_overage = settings.get("allow_paid_overage", False) if settings else False

    if username:
        user = await get_user_by_username(username)
        if not user or not user.get("active", True):
            return "BLOCKED"
        usage = await get_current_month_usage(username)
        credit_limit = user.get("credit_limit", 0)
        if credit_limit and usage.get("credits_used", 0) >= credit_limit:
            return "USER_BLOCKED"
    
    if calls >= PLACE_DETAILS_MONTHLY_FREE_LIMIT and not allow_overage:
        return 'BLOCKED'
    elif calls >= QUOTA_WARNING_THRESHOLD:
        return 'WARNING'
    else:
        return 'OK'

async def increment_usage(username: str | None = None) -> None:
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
    if username:
        await increment_user_usage(username, 1)

async def get_current_usage(username: str | None = None) -> dict:
    db = get_db()
    year_month = _current_month_str()
    record = await db.api_usage_monthly.find_one({"_id": year_month})
    settings = await db.app_settings.find_one({"_id": "singleton"})
    
    calls = record.get("place_details_calls", 0) if record else 0
    app_settings = AppSettings.model_validate(settings) if settings else AppSettings(updated_at=datetime.utcnow())
    allow_overage = app_settings.allow_paid_overage
    active_plan = app_settings.active_plan
    user_summary = await get_user_usage_summary(username) if username else None
    
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
        "overage_cost_estimate": max(0, calls - PLACE_DETAILS_MONTHLY_FREE_LIMIT) * 0.02,
        "user": user_summary,
    }
