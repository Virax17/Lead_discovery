from datetime import datetime, timedelta

from app.db.connection import get_db
from app.services.error_logger import log_error

STALE_RUNNING_SEARCH_MINUTES = 10


async def mark_stale_running_searches(max_age_minutes: int = STALE_RUNNING_SEARCH_MINUTES) -> int:
    db = get_db()
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    stale_searches = await db.searches.find(
        {
            "status": "running",
            "created_at": {"$lt": cutoff},
        },
        {"_id": 1},
    ).to_list(length=None)

    if not stale_searches:
        return 0

    ids = [search["_id"] for search in stale_searches]
    await db.searches.update_many(
        {"_id": {"$in": ids}, "status": "running"},
        {
            "$set": {
                "status": "failed",
                "completed_at": datetime.utcnow(),
                "failure_reason": "Search was interrupted by a backend restart or stopped worker.",
            }
        },
    )

    for search_id in ids:
        await log_error(
            search_id=search_id,
            stage="search_recovery",
            place_id=None,
            error_message="Marked stale running search as failed after backend startup.",
        )

    return len(ids)
