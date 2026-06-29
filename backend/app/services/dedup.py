from app.db.connection import get_db
from bson import ObjectId
from datetime import datetime

async def is_known_business(place_id: str) -> ObjectId | None:
    db = get_db()
    doc = await db.master_businesses.find_one({"place_id": place_id}, {"_id": 1})
    return doc["_id"] if doc else None

async def update_last_seen(master_business_id: ObjectId) -> None:
    db = get_db()
    await db.master_businesses.update_one(
        {"_id": master_business_id},
        {"$set": {"last_seen_at": datetime.utcnow()}}
    )
