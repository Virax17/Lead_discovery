import pymongo
from app.db.connection import get_db

async def ensure_indexes():
    db = get_db()
    
    # 1. master_businesses: unique index on place_id
    await db.master_businesses.create_index(
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
    print("Database indexes ensured.")
