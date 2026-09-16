from datetime import datetime
from app.db.connection import get_db
from app.config.quota import PLACE_DETAILS_MONTHLY_FREE_LIMIT, QUOTA_WARNING_THRESHOLD
from app.config.settings import settings as app_config
from app.models.schemas import AppSettings
from app.services.users import get_current_month_usage, get_user_by_username, get_user_usage_summary, increment_user_usage

def _current_month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")

# Testing-only hard cap on real Google Places calls, separate from the real
# monthly quota tracked in Mongo. In-memory only (resets on backend
# restart) — this is a manual-testing safety valve, not a persisted limit.
_test_calls_used = 0

async def check_quota_before_call(username: str | None = None) -> str:
    if app_config.test_max_places_calls > 0 and _test_calls_used >= app_config.test_max_places_calls:
        return "BLOCKED"

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
    if app_config.test_max_places_calls > 0:
        global _test_calls_used
        _test_calls_used += 1

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

async def get_admin_usage_stats() -> dict:
    """Aggregates this month's searches into plain-language usage statistics for the admin portal."""
    db = get_db()
    year_month = _current_month_str()
    start = datetime.strptime(year_month, "%Y-%m")
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)

    pipeline = [
        {"$match": {"created_at": {"$gte": start, "$lt": end}}},
        {"$group": {
            "_id": "$status",
            "search_count": {"$sum": 1},
            "companies_found": {"$sum": "$total_results"},
            "credits_used": {"$sum": "$place_details_calls_used"},
        }},
    ]
    rows = await db.searches.aggregate(pipeline).to_list(length=None)
    by_status = {r["_id"]: r for r in rows}

    total_companies = sum(r["companies_found"] for r in rows)
    total_credits_from_searches = sum(r["credits_used"] for r in rows)

    def bucket(key: str) -> dict:
        row = by_status.get(key)
        return {
            "search_count": row["search_count"] if row else 0,
            "companies_found": row["companies_found"] if row else 0,
            "credits_used": row["credits_used"] if row else 0,
        }

    return {
        "year_month": year_month,
        # Derived from the same searches rows as status_breakdown below, so the
        # headline total always equals the sum of the breakdown - intentionally not
        # reusing get_current_usage()'s global counter here, since that counter can
        # drift from the sum of individual search records (pre-existing data from
        # older code revisions) and showing two different "credits used" numbers on
        # one page would be confusing.
        "credits_used": total_credits_from_searches,
        "credits_limit": PLACE_DETAILS_MONTHLY_FREE_LIMIT,
        "companies_found": total_companies,
        "avg_credits_per_company": round(total_credits_from_searches / total_companies, 1) if total_companies else None,
        "total_searches": sum(r["search_count"] for r in rows),
        "status_breakdown": {
            "completed": bucket("completed"),
            "completed_quota_limited": bucket("completed_quota_limited"),
            "completed_rate_limited": bucket("completed_rate_limited"),
            "failed": bucket("failed"),
            "running": bucket("running"),
        },
    }
