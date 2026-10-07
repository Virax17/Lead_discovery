from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from typing import List, Optional

from app.api.auth import get_current_user
from app.config.countries import normalize_country
from app.db.connection import get_db
from app.services.company_cache import normalize_domain
from app.services.country_maintenance import normalize_all_countries
from app.services.export_engine import export_country
from app.services.storage import s3_enabled, local_path, presigned_url

router = APIRouter(prefix="/businesses", tags=["businesses"])

PAGE_SIZE = 100


@router.get("/countries")
async def list_populated_countries(current_user: str = Depends(get_current_user)):
    db = get_db()
    await normalize_all_countries(db)
    pipeline = [
        {"$match": {"country": {"$nin": [None, ""]}}},
        {"$group": {
            "_id": "$country",
            "country_code": {"$first": "$country_code"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    docs = await db.master_businesses.aggregate(pipeline).to_list(length=None)
    return [
        {
            "country": d["_id"],
            "country_code": d.get("country_code"),
            "count": d["count"],
        }
        for d in docs
    ]


ENRICHMENT_SUMMARY_FIELDS = (
    "company_name", "business_description", "country", "hq_city", "hq_address", "industry",
    "company_category", "tritorc_relevance", "key_operations", "contact_emails", "contact_phones",
    "social_links", "crawl_tier", "crawl_score", "business_role",
)


async def _enrichment_summaries(db, docs: list[dict]) -> dict:
    """LLM-enriched profile (description, HQ, Tritorc relevance, contacts) for
    the page's businesses that have been through Company Enrichment, keyed by
    domain. One query for the whole page; crawled page text is not loaded."""
    domains = {normalize_domain(d.get("website") or "") for d in docs}
    domains.discard(None)
    if not domains:
        return {}
    projection = {field: 1 for field in ENRICHMENT_SUMMARY_FIELDS}
    projection["domain"] = 1
    found = {}
    async for e in db.company_enrichments.find({"domain": {"$in": list(domains)}}, projection):
        found[e["domain"]] = {k: e.get(k) for k in ENRICHMENT_SUMMARY_FIELDS}
    return found


@router.get("")
async def list_businesses(
    country: str = Query(..., description="Country name, e.g. 'India'"),
    page: int = Query(1, ge=1),
    crawl_tier: Optional[str] = None,
    business_role: Optional[str] = None,
    current_user: str = Depends(get_current_user),
):
    db = get_db()
    country, _country_code = normalize_country(country)
    skip = (page - 1) * PAGE_SIZE

    query = {"country": country}
    if crawl_tier and crawl_tier != "all":
        if crawl_tier == "unknown":
            query["$or"] = [{"crawl_tier": "unknown"}, {"crawl_tier": {"$exists": False}}, {"crawl_tier": None}]
        else:
            query["crawl_tier"] = crawl_tier
    if business_role and business_role != "all":
        if business_role == "unknown":
            query["business_role"] = {"$in": ["unknown", None]}
        else:
            query["business_role"] = business_role

    total = await db.master_businesses.count_documents(query)
    cursor = (
        db.master_businesses.find(query)
        .sort("last_seen_at", -1)
        .skip(skip)
        .limit(PAGE_SIZE)
    )
    docs = await cursor.to_list(length=PAGE_SIZE)

    enrichments = await _enrichment_summaries(db, docs)
    businesses = []
    for d in docs:
        d["id"] = str(d["_id"])
        del d["_id"]
        d["enrichment"] = enrichments.get(normalize_domain(d.get("website") or ""))
        businesses.append(d)

    return {
        "country": country,
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "businesses": businesses,
    }


@router.get("/export")
async def export_businesses(
    country: str = Query(..., description="Country name, e.g. 'India'"),
    format: str = "xlsx",
    selected_columns: Optional[List[str]] = Query(None),
    selected_tiers: Optional[List[str]] = Query(None),
    selected_roles: Optional[List[str]] = Query(None),
    current_user: str = Depends(get_current_user),
):
    country, _country_code = normalize_country(country)
    if format not in ["xlsx", "csv"]:
        raise HTTPException(status_code=400, detail="Format must be xlsx or csv")

    stored_filename = await export_country(country, format, selected_columns=selected_columns, selected_tiers=selected_tiers, selected_roles=selected_roles)
    if not stored_filename:
        raise HTTPException(status_code=404, detail="Export failed or not found")

    if s3_enabled():
        return RedirectResponse(presigned_url(stored_filename))

    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv"
    safe_country = "".join(c if c.isalnum() else "_" for c in country)
    download_filename = f"country_{safe_country}.{format}"

    return FileResponse(local_path(stored_filename), media_type=media_type, filename=download_filename)
