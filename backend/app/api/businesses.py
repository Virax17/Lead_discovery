from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from typing import List, Optional

from app.api.auth import get_current_user
from app.config.countries import normalize_country
from app.db.connection import get_db
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


@router.get("")
async def list_businesses(
    country: str = Query(..., description="Country name, e.g. 'India'"),
    page: int = Query(1, ge=1),
    current_user: str = Depends(get_current_user),
):
    db = get_db()
    country, _country_code = normalize_country(country)
    skip = (page - 1) * PAGE_SIZE

    total = await db.master_businesses.count_documents({"country": country})
    cursor = (
        db.master_businesses.find({"country": country})
        .sort("last_seen_at", -1)
        .skip(skip)
        .limit(PAGE_SIZE)
    )
    docs = await cursor.to_list(length=PAGE_SIZE)

    businesses = []
    for d in docs:
        d["id"] = str(d["_id"])
        del d["_id"]
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
    selected_columns: Optional[List[str]] = None,
    current_user: str = Depends(get_current_user),
):
    country, _country_code = normalize_country(country)
    if format not in ["xlsx", "csv"]:
        raise HTTPException(status_code=400, detail="Format must be xlsx or csv")

    stored_filename = await export_country(country, format, selected_columns=selected_columns)
    if not stored_filename:
        raise HTTPException(status_code=404, detail="Export failed or not found")

    if s3_enabled():
        return RedirectResponse(presigned_url(stored_filename))

    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv"
    safe_country = "".join(c if c.isalnum() else "_" for c in country)
    download_filename = f"country_{safe_country}.{format}"

    return FileResponse(local_path(stored_filename), media_type=media_type, filename=download_filename)
