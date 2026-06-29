import os
import pandas as pd
from typing import Literal, Optional
from bson import ObjectId
from app.db.connection import get_db
from app.services.error_logger import log_error

EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

async def export_search(search_id_str: str, fmt: Literal["xlsx", "csv"], selected_columns: Optional[list[str]] = None) -> str | None:
    try:
        search_id = ObjectId(search_id_str)
        db = get_db()
        
        search = await db.searches.find_one({"_id": search_id})
        if not search:
            return None
            
        path = os.path.join(EXPORT_DIR, f"{search_id_str}.{fmt}")
        
        # Check staleness
        if os.path.exists(path):
            file_mtime = os.path.getmtime(path)
            if search.get("completed_at"):
                completed_ts = search["completed_at"].timestamp()
                if file_mtime >= completed_ts:
                    return path # Reuse file
        
        # Regenerate
        pipeline = [
            {"$match": {"search_id": search_id}},
            {"$lookup": {
                "from": "master_businesses",
                "localField": "master_business_id",
                "foreignField": "_id",
                "as": "business"
            }},
            {"$unwind": "$business"},
            {"$project": {
                "Company Name": "$business.name",
                "Address": "$business.address",
                "Website": "$business.website",
                "Phone Number": "$business.phone_number",
                "Google Maps URL": "$business.maps_url",
                "Industry Type": "$business.industry_type",
                "Industry Sector": "$business.industry_sector",
                "Customer Type": "$business.customer_type"
            }}
        ]
        
        cursor = db.search_results.aggregate(pipeline)
        docs = await cursor.to_list(length=None)
        
        if not docs:
            df = pd.DataFrame(columns=["Company Name", "Address", "Website", "Phone Number", "Google Maps URL", "Industry Type", "Industry Sector", "Customer Type"])
        else:
            df = pd.DataFrame(docs)
            if "_id" in df.columns:
                df = df.drop(columns=["_id"])

        if selected_columns:
            available_columns = [column for column in selected_columns if column in df.columns]
            if available_columns:
                df = df[available_columns]
        
        if fmt == "xlsx":
            df.to_excel(path, index=False)
        else:
            df.to_csv(path, index=False)
            
        return path
        
    except Exception as e:
        await log_error(search_id=ObjectId(search_id_str) if ObjectId.is_valid(search_id_str) else None, 
                        stage="export", place_id=None, error_message=str(e))
        return None
