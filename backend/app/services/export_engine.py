import pandas as pd
from typing import Literal, Optional
from bson import ObjectId
from app.db.connection import get_db
from app.services.error_logger import log_error
from app.services.storage import local_path, upload_if_needed

EXPORT_SOURCE_VALUE = "LeadDiscovery"

async def export_search(search_id_str: str, fmt: Literal["xlsx", "csv"], selected_columns: Optional[list[str]] = None) -> str | None:
    try:
        search_id = ObjectId(search_id_str)
        db = get_db()

        search = await db.searches.find_one({"_id": search_id})
        if not search:
            return None

        filename = f"{search_id_str}.{fmt}"
        path = local_path(filename)

        # Check staleness (local disk only — S3 objects are always freshly regenerated below)
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
                "Source": {"$literal": EXPORT_SOURCE_VALUE},
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
            df = pd.DataFrame(columns=["Source", "Company Name", "Address", "Website", "Phone Number", "Google Maps URL", "Industry Type", "Industry Sector", "Customer Type"])
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

        await upload_if_needed(filename)
        return filename

    except Exception as e:
        await log_error(search_id=ObjectId(search_id_str) if ObjectId.is_valid(search_id_str) else None,
                        stage="export", place_id=None, error_message=str(e))
        return None


async def export_country(country: str, fmt: Literal["xlsx", "csv"], selected_columns: Optional[list[str]] = None) -> str | None:
    try:
        db = get_db()
        safe_country = "".join(c if c.isalnum() else "_" for c in country)
        filename = f"country_{safe_country}.{fmt}"
        path = local_path(filename)

        cursor = db.master_businesses.find({"country": country})
        docs = await cursor.to_list(length=None)

        columns = ["Source", "Company Name", "Address", "Website", "Phone Number", "Google Maps URL", "Industry Type", "Industry Sector", "Customer Type", "First Found", "Last Seen"]

        if not docs:
            df = pd.DataFrame(columns=columns)
        else:
            rows = [{
                "Source": EXPORT_SOURCE_VALUE,
                "Company Name": d.get("name"),
                "Address": d.get("address"),
                "Website": d.get("website"),
                "Phone Number": d.get("phone_number"),
                "Google Maps URL": d.get("maps_url"),
                "Industry Type": d.get("industry_type"),
                "Industry Sector": d.get("industry_sector"),
                "Customer Type": d.get("customer_type"),
                "First Found": d.get("first_found_at"),
                "Last Seen": d.get("last_seen_at"),
            } for d in docs]
            df = pd.DataFrame(rows, columns=columns)

        if selected_columns:
            available_columns = [column for column in selected_columns if column in df.columns]
            if available_columns:
                df = df[available_columns]

        if fmt == "xlsx":
            df.to_excel(path, index=False)
        else:
            df.to_csv(path, index=False)

        await upload_if_needed(filename)
        return filename

    except Exception as e:
        await log_error(search_id=None, stage="export_country", place_id=None, error_message=str(e))
        return None
