"""
One-off cleanup: re-score every existing master_businesses entry with the
current LLM-primary relevance filter (same logic search_runner.py now uses
for every new candidate), and remove the ones that don't align with
Tritorc's actual business.

Dry-run by default — only prints what would be removed. Pass --apply to
actually delete the master_businesses docs + their search_results, and
record them in rejected_businesses so future searches skip them for good.

Usage (from backend/):
    python -m scripts.reject_unaligned_businesses
    python -m scripts.reject_unaligned_businesses --apply
    python -m scripts.reject_unaligned_businesses --concurrency 20
"""
import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db
from app.services.website_scanner import scan_website
from app.services.relevance_llm import score_relevance
from app.services.rejected_businesses import mark_rejected


async def _check_one(doc: dict, semaphore: asyncio.Semaphore) -> dict | None:
    async with semaphore:
        website = doc.get("website")
        scan_result = await scan_website(website)

        llm_result = await score_relevance(
            doc.get("name", ""), doc.get("address", ""), scan_result["raw_text"], ""
        )
        if llm_result is not None and llm_result["aligned"]:
            return None

        reason = llm_result["reason"] if llm_result else "no_domain_term_match_and_no_llm_available"
        return {
            "place_id": doc["place_id"],
            "master_business_id": doc["_id"],
            "name": doc.get("name"),
            "website": website,
            "reason": reason,
        }


async def run(apply: bool, concurrency: int):
    db = get_db()
    cursor = db.master_businesses.find({}, {"_id": 1, "place_id": 1, "name": 1, "address": 1, "website": 1})
    docs = await cursor.to_list(length=None)
    print(f"Checking {len(docs)} existing businesses (concurrency={concurrency})...", flush=True)

    semaphore = asyncio.Semaphore(concurrency)
    to_reject: list[dict] = []
    completed = 0

    async def _wrapped(doc):
        nonlocal completed
        result = await _check_one(doc, semaphore)
        completed += 1
        if completed % 25 == 0 or completed == len(docs):
            print(f"  ...{completed}/{len(docs)} checked, {len(to_reject) + (1 if result else 0)} flagged so far", flush=True)
        return result

    results = await asyncio.gather(*(_wrapped(doc) for doc in docs))
    to_reject = [r for r in results if r is not None]

    print(f"\n{len(to_reject)} of {len(docs)} would be removed:", flush=True)
    for entry in to_reject:
        print(f"  - {entry['name']} ({entry['website']}) -> {entry['reason']}", flush=True)

    if not apply:
        print("\nDry run only — pass --apply to actually delete these and record them as rejected.", flush=True)
        return

    for entry in to_reject:
        await mark_rejected(entry["place_id"], entry["name"], entry["website"], reason=entry["reason"])
        await db.search_results.delete_many({"master_business_id": entry["master_business_id"]})
        await db.master_businesses.delete_one({"_id": entry["master_business_id"]})

    print(f"\nRemoved {len(to_reject)} businesses and recorded them in rejected_businesses.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually delete; default is dry-run only.")
    parser.add_argument("--concurrency", type=int, default=12, help="Max concurrent website scans + LLM calls.")
    args = parser.parse_args()

    asyncio.run(run(args.apply, args.concurrency))
