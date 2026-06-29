from datetime import datetime
from bson import ObjectId
import pymongo

from app.db.connection import get_db
from app.services.places_client import text_search_ids, get_place_details, QuotaBlockedError
from app.services.dedup import is_known_business, update_last_seen
from app.services.error_logger import log_error
from app.models.schemas import MasterBusiness, SearchResult, PlaceDetails

async def run_region_search(search_id: ObjectId, country: str, country_code: str, state: str | None, city: str | None, max_results: int, keywords: list[str], industries: list[str], website_only: bool) -> ObjectId:
    db = get_db()
    
    seen_place_ids: set[str] = set()
    quota_limited = False
    total_results = 0
    total_place_details_calls = 0
    
    default_industry = industries[0] if industries else "Unknown"
    
    for keyword in keywords:
        if quota_limited:
            break
        keyword_results = 0
        keyword_place_details_calls = 0
            
        try:
            place_ids = await text_search_ids(keyword, country, country_code, state, city, max_results)
        except Exception as e:
            await log_error(search_id=search_id, stage="text_search", place_id=None, error_message=f"Failed keyword '{keyword}': {str(e)}")
            continue # skip to next keyword
            
        for pid in place_ids:
            if pid in seen_place_ids:
                continue
            seen_place_ids.add(pid)
            
            master_business_id = await is_known_business(pid)
            details_status = 'ok'
            details = None
            
            if master_business_id:
                mb = await db.master_businesses.find_one({"_id": master_business_id})
                if mb:
                    details = PlaceDetails(name=mb["name"], address=mb["address"], website=mb.get("website"), phone_number=mb.get("phone_number"))
                await update_last_seen(master_business_id)
            else:
                try:
                    details = await get_place_details(pid)
                    keyword_place_details_calls += 1

                    addr = (details.address if details else "").lower()
                    if details and country.lower() not in addr and country_code.lower() not in addr:
                        await log_error(search_id=search_id, stage="country_mismatch_filtered", place_id=pid, error_message=f"Address {addr} doesn't match {country}")
                        continue

                    if website_only and not (details and details.website):
                        continue
                    
                    master_business = MasterBusiness(
                        place_id=pid,
                        name=details.name if details else "Unknown",
                        address=details.address if details else "Unknown",
                        website=details.website if details else None,
                        phone_number=details.phone_number if details else None,
                        maps_url=f"https://www.google.com/maps/place/?q=place_id:{pid}",
                        industry_sector=default_industry,
                        industry_type=default_industry,
                        customer_type="Unknown",
                        first_found_at=datetime.utcnow(),
                        last_seen_at=datetime.utcnow()
                    )
                    
                    if not details:
                        details_status = 'failed_after_retries'
                        
                    try:
                        result = await db.master_businesses.insert_one(master_business.model_dump(by_alias=True, exclude_none=True))
                        master_business_id = result.inserted_id
                    except pymongo.errors.DuplicateKeyError:
                        master_business_id = await is_known_business(pid)
                        if master_business_id:
                            await update_last_seen(master_business_id)
                        
                except QuotaBlockedError:
                    quota_limited = True
                    details_status = 'skipped_quota_blocked'
                    await log_error(search_id=search_id, stage="skipped_quota_blocked", place_id=pid, error_message="Monthly quota limit reached and paid overage is disabled.")
                    break # Stop processing new place_ids, move to wrap up
                except Exception as e:
                    await log_error(search_id=search_id, stage="place_details", place_id=pid, error_message=str(e))
                    details_status = 'failed_after_retries'
                    master_business = MasterBusiness(
                        place_id=pid, name="Error", address="Error",
                        first_found_at=datetime.utcnow(), last_seen_at=datetime.utcnow()
                    )
                    result = await db.master_businesses.insert_one(master_business.model_dump(by_alias=True, exclude_none=True))
                    master_business_id = result.inserted_id

            if master_business_id:
                addr = (details.address if details else "").lower()
                if country.lower() not in addr and country_code.lower() not in addr:
                    await log_error(search_id=search_id, stage="country_mismatch_filtered", place_id=pid, error_message=f"Address {addr} doesn't match {country}")
                    continue
                
                if website_only and not (details and details.website):
                    continue

                keyword_results += 1
                total_results += 1
                search_result = SearchResult(
                    search_id=search_id,
                    master_business_id=master_business_id,
                    matched_keyword=keyword,
                    details_status=details_status,
                    created_at=datetime.utcnow()
                )
                try:
                    await db.search_results.insert_one(search_result.model_dump(by_alias=True, exclude_none=True))
                except pymongo.errors.DuplicateKeyError:
                    keyword_results -= 1
                    total_results -= 1
                    
        total_place_details_calls += keyword_place_details_calls
        # Update completed keywords
        await db.searches.update_one(
            {"_id": search_id},
            {"$inc": {"keywords_completed": 1, "total_results": keyword_results, "place_details_calls_used": keyword_place_details_calls}}
        )
        
    final_status = "completed_quota_limited" if quota_limited else "completed"
    
    await db.searches.update_one(
        {"_id": search_id},
        {
            "$set": {
                "status": final_status,
                "completed_at": datetime.utcnow(),
                "total_results": total_results,
                "place_details_calls_used": total_place_details_calls
            }
        }
    )
    
    return search_id
