from collections import defaultdict
from typing import Any

from app.config.countries import normalize_country


async def normalize_collection_countries(db, collection_name: str, field: str = "country", code_field: str = "country_code") -> list[dict[str, Any]]:
    """Collapse country values that differ only by casing/whitespace (e.g. "Spain" vs
    "spain") into a single canonical value, so a country's data never gets split
    across multiple buckets. Returns one entry per casing variant that was merged."""
    collection = db[collection_name]
    docs = await collection.aggregate([
        {"$match": {field: {"$nin": [None, ""]}}},
        {"$group": {"_id": f"${field}", "code": {"$first": f"${code_field}"}, "count": {"$sum": 1}}},
    ]).to_list(length=None)

    groups: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        groups[d["_id"].strip().lower()].append(d)

    merges: list[dict[str, Any]] = []
    for variants in groups.values():
        # Prefer a COUNTRIES match; otherwise fall back to the most common casing.
        best_variant = max(variants, key=lambda v: v["count"])
        canonical_name, canonical_code = normalize_country(best_variant["_id"], best_variant.get("code"))

        for variant in variants:
            if variant["_id"] == canonical_name:
                continue
            result = await collection.update_many(
                {field: variant["_id"]},
                {"$set": {field: canonical_name, code_field: canonical_code}},
            )
            merges.append({
                "collection": collection_name,
                "from": variant["_id"],
                "to": canonical_name,
                "modified_count": result.modified_count,
            })

    return merges


async def normalize_all_countries(db) -> list[dict[str, Any]]:
    merges = await normalize_collection_countries(db, "master_businesses")
    merges += await normalize_collection_countries(db, "searches")
    return merges
