import pymongo
from app.db.connection import get_db

async def ensure_indexes():
    db = get_db()

    await db.users.create_index([("username", pymongo.ASCENDING)], unique=True)
    await db.users.create_index([("role", pymongo.ASCENDING)])
    await db.users.create_index([("active", pymongo.ASCENDING)])

    await db.user_credits_monthly.create_index([("username", pymongo.ASCENDING)])
    await db.user_credits_monthly.create_index([("year_month", pymongo.ASCENDING)])

    # 1. master_businesses: unique index on place_id
    await db.master_businesses.create_index(
        [("place_id", pymongo.ASCENDING)],
        unique=True
    )

    # master_businesses: index on country for fast country-wise browsing/export
    await db.master_businesses.create_index([("country", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("crawl_tier", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("crawl_version", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("source_query", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("detected_language", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("scoring_language", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("source_query_language", pymongo.ASCENDING)])
    await db.master_businesses.create_index([("business_role", pymongo.ASCENDING)])

    # 2. search_results: compound unique index on (search_id, master_business_id)
    await db.search_results.create_index(
        [("search_id", pymongo.ASCENDING), ("master_business_id", pymongo.ASCENDING)],
        unique=True
    )
    
    # search_results: index on search_id for fast lookups
    await db.search_results.create_index([("search_id", pymongo.ASCENDING)])
    
    # 3. app_errors: indexes
    await db.app_errors.create_index([("search_id", pymongo.ASCENDING)])
    await db.app_errors.create_index([("occurred_at", pymongo.ASCENDING)])
    
    # Note: searches and api_usage_monthly use _id as their primary lookups.
    await db.searches.create_index([("created_by", pymongo.ASCENDING)])
    await db.searches.create_index([("created_at", pymongo.ASCENDING)])

    # Note: industrial_anchors uses _id (version|country_code|state_code) as
    # its primary lookup in get_fanout_anchors(); these support maintenance
    # queries (e.g. clearing/inspecting a country's cache, staleness sweeps).
    await db.industrial_anchors.create_index([("country_code", pymongo.ASCENDING)])
    await db.industrial_anchors.create_index([("discovered_at", pymongo.ASCENDING)])

    # company_profiles: the URL-to-company-profile enrichment crawler's
    # dedup/cache store, keyed on normalized domain (see
    # app/services/company_cache.py).
    await db.company_profiles.create_index([("domain", pymongo.ASCENDING)], unique=True)
    await db.company_profiles.create_index([("last_crawled_at", pymongo.ASCENDING)])
    await db.company_profiles.create_index([("crawl_status", pymongo.ASCENDING)])
    await db.company_profiles.create_index([("crawl_version", pymongo.ASCENDING)])

    # company_profiles: single-field indexes mirroring master_businesses'
    # crawl_tier/business_role pattern, plus a compound index on the query an
    # email-generation engine actually runs -- "good leads to email"
    # (relevance_tier in best/strong, customer_type not irrelevant) -- so that
    # filter doesn't fall back to a full collection scan.
    await db.company_profiles.create_index([("business_role", pymongo.ASCENDING)])
    await db.company_profiles.create_index([("industry_type", pymongo.ASCENDING)])
    await db.company_profiles.create_index(
        [("relevance_tier", pymongo.ASCENDING), ("customer_type", pymongo.ASCENDING)]
    )

    # company_enrichments: Company Enrichment results + crawled page cache
    # (app/services/enrichment_store.py). Lookup paths: cache_key (domain or
    # name:<key>), domain, name_keys (multikey), place_ids (multikey; links
    # to master_businesses for the Places/map pipeline).
    await db.company_enrichments.create_index([("cache_key", pymongo.ASCENDING)], unique=True)
    await db.company_enrichments.create_index([("domain", pymongo.ASCENDING)])
    await db.company_enrichments.create_index([("name_keys", pymongo.ASCENDING)])
    await db.company_enrichments.create_index([("place_ids", pymongo.ASCENDING)])
    await db.company_enrichments.create_index([("company_category", pymongo.ASCENDING)])
    await db.company_enrichments.create_index([("updated_at", pymongo.DESCENDING)])
    print("Database indexes ensured.")
