import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.models.schemas import PlaceDetails
from app.services.crawl_scorer import crawl_business_website


def load_snapshot(path: Path, limit: int, country: str | None) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if country and (record.get("country") or "").lower() != country.lower():
                continue
            if record.get("website"):
                records.append(record)
            if len(records) >= limit:
                break
    return records


async def score_record(record: dict, max_pages: int) -> dict:
    details = PlaceDetails(
        name=record.get("name") or "Unknown",
        address=record.get("address") or "Unknown",
        website=record.get("website"),
        phone_number=record.get("phone_number"),
        country_code=record.get("country_code"),
        google_types=record.get("google_types", []),
        google_primary_type=record.get("google_primary_type"),
        google_primary_type_display_name=record.get("google_primary_type_display_name"),
        google_business_status=record.get("google_business_status"),
        google_maps_uri=record.get("maps_url"),
        source_query=record.get("source_query") or record.get("source_keyword"),
    )
    score = await crawl_business_website(details, max_pages=max_pages)
    return {
        "id": record.get("_id"),
        "name": record.get("name"),
        "website": record.get("website"),
        "old_customer_type": record.get("customer_type"),
        "old_website_signal": record.get("website_signal"),
        "tier": score.tier,
        "score": score.score,
        "status": score.status,
        "pages_checked": score.pages_checked,
        "positive_signals": score.positive_signals,
        "negative_signals": score.negative_signals,
        "positive_concepts": score.positive_concepts,
        "negative_concepts": score.negative_concepts,
        "business_role": score.business_role,
        "business_role_score": score.business_role_score,
        "business_role_signals": score.business_role_signals,
        "business_role_negative_signals": score.business_role_negative_signals,
        "business_role_reason": score.business_role_reason,
        "reason": score.reason,
        "evidence": score.evidence,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl-score a local exported master_businesses snapshot.")
    parser.add_argument("--input", default="../data/audit/master_businesses.jsonl")
    parser.add_argument("--output", default="../data/audit/crawl_audit_report.json")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--country")
    args = parser.parse_args()

    records = load_snapshot(Path(args.input), args.limit, args.country)
    results = []
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] {record.get('name')} {record.get('website')}")
        results.append(await score_record(record, args.max_pages))

    tier_counts = Counter(item["tier"] for item in results)
    output = {
        "input": args.input,
        "records_scored": len(results),
        "tier_counts": dict(tier_counts),
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"records_scored": len(results), "tier_counts": dict(tier_counts), "output": str(output_path)}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
