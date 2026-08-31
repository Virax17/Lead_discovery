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

    # rejected_businesses: unique index on place_id, so a business that failed
    # the relevance check is never re-fetched or re-scanned on a later search.
    await db.rejected_businesses.create_index(
        [("place_id", pymongo.ASCENDING)],
        unique=True
    )

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
    print("Database indexes ensured.")
