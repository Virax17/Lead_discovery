from datetime import datetime

from app.db.connection import get_db


def _current_month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _classify_failure(error_message: str) -> str:
    msg = error_message.lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg or "request_quota_exceeded" in msg:
        return "rate_limited"
    if "no text content" in msg or "unterminated string" in msg or "expecting" in msg or "no key configured" in msg:
        return "truncated_or_malformed"
    return "other_error"


async def record_llm_call(provider: str, success: bool, error_message: str | None = None) -> None:
    """Tracks LLM relevance-scoring calls per provider per month — same shape
    as quota_tracker.py's Google Places tracking, but for the LLM layer, so
    rate-limit/truncation issues (like the Cerebras gpt-oss reasoning-token
    bug) show up as visible numbers instead of only surfacing in app_errors."""
    db = get_db()
    year_month = _current_month_str()
    inc = {f"providers.{provider}.calls": 1}
    if success:
        inc[f"providers.{provider}.success"] = 1
    else:
        inc[f"providers.{provider}.failed"] = 1
        reason = _classify_failure(error_message or "")
        inc[f"providers.{provider}.{reason}"] = 1

    await db.llm_usage_monthly.update_one(
        {"_id": year_month},
        {"$inc": inc, "$set": {"updated_at": datetime.utcnow()}},
        upsert=True,
    )


async def get_llm_usage_summary() -> dict:
    db = get_db()
    year_month = _current_month_str()
    doc = await db.llm_usage_monthly.find_one({"_id": year_month})
    providers = doc.get("providers", {}) if doc else {}

    def _bucket(p: dict) -> dict:
        return {
            "calls": p.get("calls", 0),
            "success": p.get("success", 0),
            "failed": p.get("failed", 0),
            "rate_limited": p.get("rate_limited", 0),
            "truncated_or_malformed": p.get("truncated_or_malformed", 0),
            "other_error": p.get("other_error", 0),
        }

    return {
        "year_month": year_month,
        "providers": {name: _bucket(p) for name, p in providers.items()},
    }
