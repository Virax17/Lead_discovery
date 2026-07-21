import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.connection import get_db


async def main():
    db = get_db()
    result = await db.searches.update_many(
        {"status": "running"},
        {
            "$set": {
                "status": "failed",
                "completed_at": datetime.utcnow(),
                "failure_reason": "Manually marked failed during local backend recovery.",
            }
        },
    )
    print(f"Marked {result.modified_count} running search(es) as failed.")


if __name__ == "__main__":
    asyncio.run(main())
