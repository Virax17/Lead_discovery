"""
Re-scores master_businesses stuck on a missing or stale crawl_version.

These are businesses Google Places already returned and whose website was
already fetched by an earlier search -- their Places API cost was paid long
ago. This script consumes NO Google Places quota; it only re-runs the
crawler + LLM fallback against the website already on file.

Confirmed via a live audit: 2,904 of 3,269 businesses in this database (89%)
have never been scored at all, and 2,571 of those already have a website
stored -- this script is how that backlog gets processed.

Usage (from backend/):
    python -m scripts.backfill_scores --dry-run --limit 20
    python -m scripts.backfill_scores --limit 500 --concurrency 4
    python -m scripts.backfill_scores --country India
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db
from app.services.crawl_scorer import CRAWL_VERSION, crawl_business_website, crawl_score_payload
from app.services.llm_fallback import apply_llm_fallback, llm_fallback_payload
from app.services.search_runner import _customer_type_from_tier, _details_from_existing, _industry_from_signals


async def _process_one(db, business: dict, dry_run: bool, llm_calls: list[int]) -> str:
    details = _details_from_existing(business, business.get("source_query"), business.get("source_query_language"))
    crawl_score = await crawl_business_website(details)

    llm_payload = await llm_fallback_payload(details, crawl_score, calls_used_in_search=llm_calls[0])
    if llm_payload.get("llm_fallback_status") in {"completed", "failed"}:
        llm_calls[0] += 1
    crawl_score = apply_llm_fallback(crawl_score, llm_payload)
    crawl_payload = {**crawl_score_payload(crawl_score), **llm_payload}

    industry = "Unknown"
    if crawl_score.tier in {"best", "strong", "weak"} and crawl_score.positive_concepts:
        industry = _industry_from_signals(crawl_score.positive_concepts)

    update = {
        **crawl_payload,
        "customer_type": _customer_type_from_tier(crawl_score.tier),
        "industry_sector": industry,
        "industry_type": industry,
        "updated_at": datetime.utcnow(),
    }

    if not dry_run:
        await db.master_businesses.update_one({"_id": business["_id"]}, {"$set": update})

    return crawl_score.tier


async def backfill(limit: int | None, dry_run: bool, country: str | None, concurrency: int):
    db = get_db()

    query = {
        "website": {"$nin": [None, ""]},
        "$or": [{"crawl_version": {"$exists": False}}, {"crawl_version": {"$ne": CRAWL_VERSION}}],
    }
    if country:
        query["country"] = country

    cursor = db.master_businesses.find(query)
    if limit:
        cursor = cursor.limit(limit)
    businesses = await cursor.to_list(length=None)

    print(f"{'[DRY RUN] ' if dry_run else ''}Backfilling {len(businesses)} businesses (crawl_version stale/missing, website on file)")
    print("No Google Places quota is consumed by this script.\n")

    semaphore = asyncio.Semaphore(concurrency)
    tier_counts: dict[str, int] = {}
    llm_calls = [0]  # shared mutable counter across concurrent tasks
    done = 0
    lock = asyncio.Lock()

    async def worker(business: dict):
        nonlocal done
        async with semaphore:
            try:
                tier = await _process_one(db, business, dry_run, llm_calls)
            except Exception as e:
                print(f"  FAILED  {business.get('name', '?')[:50]:50s}  {e}")
                return
        async with lock:
            done += 1
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            print(f"  [{done}/{len(businesses)}] {business.get('name', '?')[:50]:50s} -> {tier}")

    await asyncio.gather(*(worker(b) for b in businesses))

    print("\nTier breakdown:")
    for tier, n in sorted(tier_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {tier}: {n}")
    print(f"\nLLM fallback calls used this run: {llm_calls[0]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max businesses to process")
    parser.add_argument("--dry-run", action="store_true", help="Score but don't write updates")
    parser.add_argument("--country", type=str, default=None, help="Restrict to one country")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent crawls")
    args = parser.parse_args()
    asyncio.run(backfill(args.limit, args.dry_run, args.country, args.concurrency))
