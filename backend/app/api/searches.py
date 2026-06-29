from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from typing import List
from datetime import datetime
from bson import ObjectId
import os

from app.api.auth import get_current_user
from app.models.schemas import SearchCreate, Search, MasterBusiness, SearchResult
from app.db.connection import get_db
from app.services.search_runner import run_region_search
from app.services.export_engine import export_search

router = APIRouter(prefix="/searches", tags=["searches"])

@router.post("", status_code=202)
async def create_search(search_in: SearchCreate, background_tasks: BackgroundTasks, current_user: str = Depends(get_current_user)):
    db = get_db()
    
    search = Search(
        country=search_in.country,
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
        country=search_in.country,
        country_code=search_in.country_code,
        state=search_in.state,
        city=search_in.city,
        max_results=search_in.max_results,
        keywords=search_in.keywords,
        industries=search_in.industries,
        website_only=search_in.website_only
    )
    
    return {"search_id": str(search_id), "status": "running"}

@router.get("/{id}")
async def get_search(id: str, current_user: str = Depends(get_current_user)):
    db = get_db()
    try:
        obj_id = ObjectId(id)
    except:
        raise HTTPException(status_code=400, detail="Invalid search ID")
        
    search = await db.searches.find_one({"_id": obj_id})
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
        
    response = {
        "id": str(search["_id"]),
        "status": search["status"],
        "keywords_completed": search.get("keywords_completed", 0),
        "keywords_total": search["keywords_total"],
        "total_results": search.get("total_results", 0),
        "quota_status": "OK" # Ideally this would fetch from quota tracker, but UI pulls banner separately
    }
    
    if search["status"] in ["completed", "completed_quota_limited"]:
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
async def list_searches(current_user: str = Depends(get_current_user)):
    db = get_db()
    cursor = db.searches.find().sort("created_at", -1)
    searches = await cursor.to_list(length=None)
    for s in searches:
        s["id"] = str(s["_id"])
        del s["_id"]
    return searches

@router.get("/{id}/export")
async def download_export(id: str, format: str = "xlsx", selected_columns: List[str] | None = None, current_user: str = Depends(get_current_user)):
    if format not in ["xlsx", "csv"]:
        raise HTTPException(status_code=400, detail="Format must be xlsx or csv")
        
    path = await export_search(id, format, selected_columns=selected_columns)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Export failed or not found")
        
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv"
    filename = f"export_{id}.{format}"
    
    return FileResponse(path, media_type=media_type, filename=filename)
