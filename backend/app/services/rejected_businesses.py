from datetime import datetime

from app.db.connection import get_db


async def is_rejected(place_id: str) -> bool:
    db = get_db()
    doc = await db.rejected_businesses.find_one({"place_id": place_id}, {"_id": 1})
    return doc is not None


async def mark_rejected(place_id: str, name: str, website: str | None, reason: str) -> None:
    db = get_db()
    await db.rejected_businesses.update_one(
        {"place_id": place_id},
        {
            "$set": {
                "place_id": place_id,
                "name": name,
                "website": website,
                "reason": reason,
                "rejected_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )
