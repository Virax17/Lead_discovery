from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.config.settings import settings
from app.db.connection import get_db
from app.services.company_profile_crawler import crawl_company_profile

# In-process short-circuit only, same pattern as
# quota_tracker._test_calls_used: resets on backend restart, and Mongo
# (company_profiles, below) remains the real source of truth. This purely
# avoids a redundant Mongo round-trip for repeated calls to the same domain
# within one process's lifetime -- no Redis, no separate cache service.
_MEMORY_CACHE: dict[str, dict] = {}


def normalize_domain(url: str) -> str | None:
    """Normalizes any URL/domain input to the bare registrable host used as
    the company_profiles cache/dedup key (lowercase, no scheme, no "www.",
    no path/query)."""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    netloc = urlparse(raw).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def _is_fresh(doc: dict) -> bool:
    last_crawled_at = doc.get("last_crawled_at")
    if not last_crawled_at:
        return False
    # A failed crawl (unreachable/blocked) is retried much sooner than a
    # successful one, so a transient failure doesn't get frozen in for
    # company_profile_cache_max_age_days -- same caution as
    # industrial_anchors.get_fanout_anchors() only caching completed results.
    max_age_days = (
        settings.company_profile_cache_max_age_days
        if doc.get("crawl_status") == "ok"
        else settings.company_profile_error_retry_days
    )
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    return last_crawled_at > cutoff


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def get_company_profile(url: str, force_refresh: bool = False) -> dict:
    """memory -> Mongo cache -> crawl, in that order. Returns the stored
    profile dict plus `cache_hit`: True if a fresh cached copy was reused
    without crawling."""
    domain = normalize_domain(url)
    if not domain:
        return {
            "input_url": url,
            "domain": None,
            "crawl_status": "invalid_url",
            "crawl_error": "Could not parse a domain from the given URL.",
            "cache_hit": False,
        }

    db = get_db()

    if not force_refresh:
        memory_hit = _MEMORY_CACHE.get(domain)
        if memory_hit and _is_fresh(memory_hit):
            return {**memory_hit, "cache_hit": True}

        db_hit = await db.company_profiles.find_one({"domain": domain})
        if db_hit and _is_fresh(db_hit):
            db_hit = _serialize(db_hit)
            _MEMORY_CACHE[domain] = db_hit
            return {**db_hit, "cache_hit": True}

    profile = await crawl_company_profile(url)
    now = datetime.utcnow()
    update_fields = {**profile, "input_url": url, "last_crawled_at": now}

    await db.company_profiles.update_one(
        {"domain": domain},
        {"$set": update_fields, "$setOnInsert": {"domain": domain, "first_crawled_at": now}},
        upsert=True,
    )
    stored = await db.company_profiles.find_one({"domain": domain})
    stored = _serialize(stored)
    _MEMORY_CACHE[domain] = stored
    return {**stored, "cache_hit": False}


async def lookup_company_profile(domain: str) -> dict | None:
    """Pure cache/DB read -- never triggers a crawl."""
    normalized = normalize_domain(domain) or domain.strip().lower()
    db = get_db()
    doc = await db.company_profiles.find_one({"domain": normalized})
    if not doc:
        return None
    return _serialize(doc)
