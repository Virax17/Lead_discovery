from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, RedirectResponse
from typing import List
from datetime import datetime
from bson import ObjectId

from app.api.auth import get_current_user, get_current_user_profile
from app.config.countries import normalize_country
from app.models.schemas import SearchCreate, Search, MasterBusiness, SearchResult
from app.db.connection import get_db
from app.services.search_runner import run_region_search
from app.services.search_recovery import mark_stale_running_searches
from app.services.export_engine import export_search
from app.services.storage import s3_enabled, local_path, presigned_url

router = APIRouter(prefix="/searches", tags=["searches"])

@router.post("", status_code=202)
async def create_search(search_in: SearchCreate, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user_profile)):
    db = get_db()
    username = current_user["username"]

    # Normalize to the canonical country name/code so the same country never
    # ends up split across multiple casings in the master database (e.g. "spain" vs "Spain").
    country, country_code = normalize_country(search_in.country, search_in.country_code)

    search = Search(
        created_by=username,
        country=country,
        country_code=country_code,
        state=search_in.state,
        city=search_in.city,
        max_results=search_in.max_results,
        status="running",
        keywords_total=len(search_in.keywords),
        created_at=datetime.utcnow()
    )

    result = await db.searches.insert_one(search.model_dump(by_alias=True, exclude_none=True))
    search_id = result.inserted_id

    background_tasks.add_task(
        run_region_search,
        search_id=search_id,
        created_by=username,
        country=country,
        state=search_in.state,
        city=search_in.city,
        max_results=search_in.max_results,
        keywords=search_in.keywords,
        industries=search_in.industries,
        website_only=search_in.website_only,
        country_code=country_code
    )

    return {"search_id": str(search_id), "status": "running"}

@router.get("/{id}")
async def get_search(id: str, current_user: dict = Depends(get_current_user_profile)):
    db = get_db()
    username = current_user["username"]
    is_admin = current_user.get("role") == "admin"
    try:
        obj_id = ObjectId(id)
    except:
        raise HTTPException(status_code=400, detail="Invalid search ID")
        
    search = await db.searches.find_one({"_id": obj_id})
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    if not is_admin and search.get("created_by") != username:
        raise HTTPException(status_code=404, detail="Search not found")
        
    response = {
        "id": str(search["_id"]),
        "status": search["status"],
        "keywords_completed": search.get("keywords_completed", 0),
        "keywords_total": search["keywords_total"],
        "total_results": search.get("total_results", 0),
        "place_details_calls_used": search.get("place_details_calls_used", 0),
        "quota_status": "OK" # Ideally this would fetch from quota tracker, but UI pulls banner separately
    }
    
    if search["status"] in ["completed", "completed_quota_limited", "completed_rate_limited", "failed"]:
        # Fetch results
        pipeline = [
            {"$match": {"search_id": obj_id}},
            {"$lookup": {
                "from": "master_businesses",
                "localField": "master_business_id",
                "foreignField": "_id",
                "as": "business"
            }},
            {"$unwind": "$business"}
        ]
        cursor = db.search_results.aggregate(pipeline)
        docs = await cursor.to_list(length=None)
        
        results = []
        for d in docs:
            b = d["business"]
            b["id"] = str(b["_id"])
            del b["_id"]
            results.append(b)
            
        response["businesses"] = results
        
    return response

@router.get("")
async def list_searches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user_profile),
):
    db = get_db()
    await mark_stale_running_searches()
    username = current_user["username"]
    is_admin = current_user.get("role") == "admin"
    skip = (page - 1) * page_size

    query = {} if is_admin else {"created_by": username}
    total = await db.searches.count_documents(query)
    cursor = db.searches.find(query).sort("created_at", -1).skip(skip).limit(page_size)
    searches = await cursor.to_list(length=page_size)
    for s in searches:
        s["id"] = str(s["_id"])
        del s["_id"]
    return {
        "items": searches,
        "page": page,
        "page_size": page_size,
        "total": total,
    }

@router.get("/{id}/export")
async def download_export(
    id: str,
    format: str = "xlsx",
    selected_columns: List[str] | None = Query(None),
    selected_tiers: List[str] | None = Query(None),
    selected_roles: List[str] | None = Query(None),
    current_user: dict = Depends(get_current_user_profile),
):
    username = current_user["username"]
    is_admin = current_user.get("role") == "admin"
    db = get_db()
    try:
        obj_id = ObjectId(id)
    except:
        raise HTTPException(status_code=400, detail="Invalid search ID")
    search = await db.searches.find_one({"_id": obj_id})
    if not search:
        raise HTTPException(status_code=404, detail="Export failed or not found")
    if not is_admin and search.get("created_by") != username:
        raise HTTPException(status_code=404, detail="Export failed or not found")

    if format not in ["xlsx", "csv"]:
        raise HTTPException(status_code=400, detail="Format must be xlsx or csv")

    stored_filename = await export_search(id, format, selected_columns=selected_columns, selected_tiers=selected_tiers, selected_roles=selected_roles)
    if not stored_filename:
        raise HTTPException(status_code=404, detail="Export failed or not found")

    if s3_enabled():
        return RedirectResponse(presigned_url(stored_filename))

    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv"
    download_filename = f"export_{id}.{format}"

    return FileResponse(local_path(stored_filename), media_type=media_type, filename=download_filename)
