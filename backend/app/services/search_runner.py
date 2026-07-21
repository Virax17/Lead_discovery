from datetime import datetime
from bson import ObjectId
import pymongo

from app.config.countries import normalize_country
from app.db.connection import get_db
from app.services.places_client import text_search_places, get_place_details, QuotaBlockedError, GoogleRateLimitedError
from app.services.dedup import is_known_business, update_last_seen
from app.services.error_logger import log_error
from app.models.schemas import MasterBusiness, SearchResult

def classify_industry(name: str, keyword: str, selected_industries: list[str]) -> str:
    name_lower = name.lower()
    keyword_lower = keyword.lower()

    industry_keywords = {
        "Oil and gas": ["oil", "gas", "pipeline", "drilling", "bop", "refinery", "petro", "artificial lift", "well", "offshore", "petroleum"],
        "Wind energy": ["wind", "turbine", "blade", "solar", "renewable"],
        "Power": ["power", "energy", "electric", "grid", "station", "utility"],
        "Heavy engineering": ["engineering", "machinery", "industrial", "fabrication", "mechanical", "torque", "bolt", "tensioner", "calibration", "heavy equipment"],
        "Turbine manufacturing": ["turbine", "manufacturing", "rotor", "stator"],
        "Construction": ["construction", "contractor", "civil", "build", "developer"]
    }

    target_industries = selected_industries if selected_industries else list(industry_keywords.keys())

    # 1. Check keyword
    for ind in target_industries:
        if ind in industry_keywords:
            for kw in industry_keywords[ind]:
                if kw in keyword_lower:
                    return ind

    # 2. Check business name
    for ind in target_industries:
        if ind in industry_keywords:
            for kw in industry_keywords[ind]:
                if kw in name_lower:
                    return ind

    # 3. Fallback
    return selected_industries[0] if selected_industries else "Unknown"


async def upsert_master_business(master_business: MasterBusiness) -> ObjectId:
    db = get_db()
    payload = master_business.model_dump(by_alias=True, exclude_none=True)
    place_id = payload.pop("place_id")
    first_found_at = payload.pop("first_found_at")
    payload["last_seen_at"] = datetime.utcnow()
    payload["updated_at"] = datetime.utcnow()

    await db.master_businesses.update_one(
        {"place_id": place_id},
        {
            "$set": payload,
            "$setOnInsert": {
                "place_id": place_id,
                "first_found_at": first_found_at,
            },
        },
        upsert=True,
    )

    doc = await db.master_businesses.find_one({"place_id": place_id}, {"_id": 1})
    if not doc:
        raise RuntimeError(f"Failed to persist master business for {place_id}")
    return doc["_id"]

async def run_region_search(
    search_id: ObjectId,
    created_by: str | None,
    country: str,
    state: str | None,
    city: str | None,
    max_results: int,
    keywords: list[str],
    industries: list[str],
    website_only: bool,
    country_code: str | None = None,
) -> ObjectId:
    db = get_db()
    country, country_code = normalize_country(country, country_code)

    seen_place_ids: set[str] = set()
    quota_limited = False
    google_rate_limited = False
    total_results = 0
    total_place_details_calls = 0

    try:
        for keyword in keywords:
            if quota_limited or google_rate_limited:
                break
            keyword_results = 0
            keyword_place_details_calls = 0

            try:
                places, text_search_calls = await text_search_places(
                    keyword,
                    country,
                    state,
                    city,
                    max_results,
                    country_code=country_code,
                    industries=industries,
                    username=created_by,
                )
                keyword_place_details_calls += text_search_calls
            except QuotaBlockedError:
                quota_limited = True
                await log_error(search_id=search_id, stage="skipped_quota_blocked", place_id=None, error_message=f"Monthly quota limit reached before keyword '{keyword}'.")
                continue
            except GoogleRateLimitedError:
                google_rate_limited = True
                await log_error(search_id=search_id, stage="skipped_google_rate_limited", place_id=None, error_message=f"Google Places Text Search rate-limited keyword '{keyword}'.")
                continue
            except Exception as e:
                await log_error(search_id=search_id, stage="text_search", place_id=None, error_message=f"Failed keyword '{keyword}': {str(e)}")
                continue  # skip to next keyword

            for pid, text_details in places:
                if pid in seen_place_ids:
                    continue
                seen_place_ids.add(pid)

                # Known business: no API call, no export row, just refresh last_seen.
                existing_id = await is_known_business(pid)
                if existing_id:
                    await update_last_seen(existing_id, country=country, country_code=country_code)
                    search_result = SearchResult(
                        search_id=search_id,
                        master_business_id=existing_id,
                        matched_keyword=keyword,
                        details_status="known",
                        created_at=datetime.utcnow(),
                    )
                    try:
                        await db.search_results.insert_one(search_result.model_dump(by_alias=True, exclude_none=True))
                        keyword_results += 1
                        total_results += 1
                    except pymongo.errors.DuplicateKeyError:
                        pass
                    continue

                details = text_details
                details_counted = False

                if not details or details.name == "Unknown" or details.address == "Unknown":
                    # Fallback for rare Text Search responses without enough fields.
                    try:
                        details = await get_place_details(pid, username=created_by)
                        details_counted = details is not None
                    except QuotaBlockedError:
                        quota_limited = True
                        await log_error(search_id=search_id, stage="skipped_quota_blocked", place_id=pid, error_message="Monthly quota limit reached and paid overage is disabled.")
                        break
                    except GoogleRateLimitedError:
                        google_rate_limited = True
                        await log_error(search_id=search_id, stage="skipped_google_rate_limited", place_id=pid, error_message="Google Places API returned 429 Too Many Requests. Search stopped so it can be retried later.")
                        break

                if details_counted:
                    keyword_place_details_calls += 1

                if not details:
                    await log_error(search_id=search_id, stage="place_details", place_id=pid, error_message="Failed to fetch place details after retries.")
                    continue

                if country_code and details.country_code and details.country_code.upper() != country_code.upper():
                    await log_error(
                        search_id=search_id,
                        stage="country_mismatch",
                        place_id=pid,
                        error_message=f"Skipped place from {details.country_code}; selected country was {country_code}.",
                    )
                    continue

                if website_only and not details.website:
                    continue

                industry = classify_industry(details.name, keyword, industries)
                master_business = MasterBusiness(
                    place_id=pid,
                    name=details.name,
                    address=details.address,
                    website=details.website,
                    phone_number=details.phone_number,
                    maps_url=f"https://www.google.com/maps/place/?q=place_id:{pid}",
                    data_source="google_places",
                    country=country,
                    country_code=country_code,
                    industry_sector=industry,
                    industry_type=industry,
                    customer_type="Unknown",
                    first_found_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow(),
                )

                try:
                    master_business_id = await upsert_master_business(master_business)
                except Exception as e:
                    await log_error(search_id=search_id, stage="master_business", place_id=pid, error_message=str(e))
                    continue

                keyword_results += 1
                total_results += 1
                search_result = SearchResult(
                    search_id=search_id,
                    master_business_id=master_business_id,
                    matched_keyword=keyword,
                    details_status='ok',
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
    except Exception as e:
        await log_error(search_id=search_id, stage="search_runner", place_id=None, error_message=str(e))
        await db.searches.update_one(
            {"_id": search_id},
            {
                "$set": {
                    "status": "failed",
                    "completed_at": datetime.utcnow(),
                    "failure_reason": str(e),
                    "total_results": total_results,
                    "place_details_calls_used": total_place_details_calls,
                }
            },
        )
        return search_id

    if quota_limited:
        final_status = "completed_quota_limited"
    elif google_rate_limited:
        final_status = "completed_rate_limited"
    else:
        final_status = "completed"

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
