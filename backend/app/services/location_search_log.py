from datetime import datetime, timedelta

from app.db.connection import get_db

# Bump whenever the sourcing geometry or query strategy changes in a way that
# would make a location worth searching again. Without this in the key, a pair
# searched under the old strategy stays marked "exhausted" for 90 days, so
# improvements to where/how we search are silently skipped for everything
# already touched — the improvement then looks like it did nothing.
SOURCING_VERSION = "v2-anchor-seeded"


def _key(country_code: str, state: str | None, keyword: str, city: str | None = None) -> str:
    normalized_keyword = " ".join(keyword.lower().split())
    return f"{SOURCING_VERSION}|{(country_code or '').upper()}|{state or ''}|{city or ''}|{normalized_keyword}"


async def is_recently_searched(country_code: str, state: str | None, keyword: str, max_age_days: int = 90, city: str | None = None) -> bool:
    """True only if this (country, state, [city,] keyword) combo was already
    fully searched (Google's own pagination was drained, not cut short by
    quota) within the last `max_age_days`. A combo cut short by quota/rate-limit
    is never considered done and stays eligible for retry immediately,
    regardless of age. `city` scopes an adaptive drill-down entry separately
    from its parent state-level entry (city=None)."""
    db = get_db()
    doc = await db.location_search_log.find_one({"_id": _key(country_code, state, keyword, city)})
    if not doc or not doc.get("exhausted"):
        return False
    last_searched_at = doc.get("last_searched_at")
    if not last_searched_at:
        return False
    return datetime.utcnow() - last_searched_at < timedelta(days=max_age_days)


async def mark_searched(country_code: str, state: str | None, keyword: str, exhausted: bool, city: str | None = None) -> None:
    db = get_db()
    await db.location_search_log.update_one(
        {"_id": _key(country_code, state, keyword, city)},
        {
            "$set": {
                "country_code": (country_code or "").upper(),
                "state": state,
                "city": city,
                "keyword": keyword,
                "last_searched_at": datetime.utcnow(),
                "exhausted": exhausted,
            }
        },
        upsert=True,
    )
