"""
One-off migration: collapse country values that differ only by casing/whitespace
(e.g. "Spain" vs "spain") into a single canonical value, so the Master Database's
per-country view stops splitting one country's data across multiple buckets.

This same merge is also available from the Admin page in the app (no server
access needed) — this script is the CLI equivalent.

Usage (from backend/):
    python -m scripts.normalize_countries
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db
from app.services.country_maintenance import normalize_all_countries


async def main():
    db = get_db()
    merges = await normalize_all_countries(db)
    if not merges:
        print("No casing duplicates found.")
        return
    for merge in merges:
        print(f"{merge['collection']}: '{merge['from']}' -> '{merge['to']}' ({merge['modified_count']} docs)")


if __name__ == "__main__":
    asyncio.run(main())
