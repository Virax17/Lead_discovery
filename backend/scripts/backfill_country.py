"""
One-off migration: set country / country_code on master_businesses and searches
documents that predate the country-wise database (implementation_plan3).

Existing data in this deployment was all gathered for India, so that is the
default backfill target. Pass --country/--code to backfill a different value.

Usage (from backend/):
    python -m scripts.backfill_country
    python -m scripts.backfill_country --country Germany --code DE
"""
import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db


async def backfill(country: str, country_code: str):
    db = get_db()

    mb_result = await db.master_businesses.update_many(
        {"country": {"$in": [None, ""]}},
        {"$set": {"country": country, "country_code": country_code}}
    )
    print(f"master_businesses updated: {mb_result.modified_count}")

    search_result = await db.searches.update_many(
        {"country_code": {"$in": [None, ""]}},
        {"$set": {"country_code": country_code}}
    )
    print(f"searches updated: {search_result.modified_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", default="India")
    parser.add_argument("--code", default="IN")
    args = parser.parse_args()

    asyncio.run(backfill(args.country, args.code))
