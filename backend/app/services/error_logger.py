from datetime import datetime
from app.db.connection import get_db
from bson import ObjectId

async def log_error(search_id: ObjectId | None, stage: str, place_id: str | None, error_message: str):
    db = get_db()
    await db.app_errors.insert_one({
        "search_id": search_id,
        "stage": stage,
        "place_id": place_id,
        "error_message": error_message,
        "occurred_at": datetime.utcnow()
    })
