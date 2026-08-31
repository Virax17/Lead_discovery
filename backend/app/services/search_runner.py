from datetime import datetime

from bson import ObjectId
import pymongo

from app.config.countries import normalize_country
from app.db.connection import get_db
from app.models.schemas import MasterBusiness, PlaceDetails, SearchResult
from app.services.crawl_scorer import CRAWL_VERSION, crawl_business_website, crawl_score_payload
from app.services.dedup import get_known_business, update_last_seen
from app.services.error_logger import log_error
from app.services.llm_fallback import apply_llm_fallback, llm_fallback_payload
from app.services.places_client import GoogleRateLimitedError, QuotaBlockedError, get_place_details, text_search_places
from app.services.website_scanner import scan_website, summarize_signal


def _customer_type_from_tier(tier: str | None) -> str:
    if tier in {"best", "strong"}:
        return "Crawler Qualified"
    if tier == "weak":
        return "Crawler Weak"
    if tier == "reject":
        return "Crawler Rejected"
    return "Unknown"


def _industry_from_signals(signals: list[str]) -> str:
    joined = " ".join(signals).lower()
    if any(term in joined for term in ("refinery", "petrochemical", "oil_gas", "pipeline")):
        return "Oil and gas"
    if "chemical" in joined or "fertilizer" in joined:
        return "Fertilizer/Chemical"
    if "power_plant" in joined:
        return "Power"
    if "steel" in joined:
        return "Steel"
    if "wind_turbine" in joined:
        return "Wind energy"
    if "epc" in joined:
        return "Industrial EPC"
    return "Heavy engineering"


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


def _details_from_existing(existing: dict, source_query: str | None, source_query_language: str | None) -> PlaceDetails:
    return PlaceDetails(
        name=existing["name"],
        address=existing["address"],
        website=existing.get("website"),
        phone_number=existing.get("phone_number"),
        country_code=existing.get("country_code"),
        google_types=existing.get("google_types", []),
        google_primary_type=existing.get("google_primary_type"),
        google_primary_type_display_name=existing.get("google_primary_type_display_name"),
        google_business_status=existing.get("google_business_status"),
        google_maps_uri=existing.get("maps_url"),
        source_query=source_query or existing.get("source_query"),
        source_query_language=source_query_language or existing.get("source_query_language"),
    )


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
    llm_fallback_calls = 0

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
                total_place_details_calls += text_search_calls
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
                continue

            for pid, text_details in places:
                if pid in seen_place_ids:
                    continue
                seen_place_ids.add(pid)

                existing = await get_known_business(pid)
                if existing and existing.get("crawl_version") == CRAWL_VERSION:
                    await update_last_seen(existing["_id"], country=country, country_code=country_code)
                    search_result = SearchResult(
                        search_id=search_id,
                        master_business_id=existing["_id"],
                        matched_keyword=keyword,
                        source_query=text_details.source_query,
                        source_query_language=text_details.source_query_language,
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

                details_counted = False
                if existing:
                    details = _details_from_existing(existing, text_details.source_query, text_details.source_query_language)
                else:
                    details = text_details
                    if not details or details.name == "Unknown" or details.address == "Unknown":
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
                        if details:
                            details.source_query = text_details.source_query
                            details.source_query_language = text_details.source_query_language

                if details_counted:
                    keyword_place_details_calls += 1
                    total_place_details_calls += 1

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

                scan_result = await scan_website(details.website)
                website_signal = summarize_signal(details.website, scan_result)
                crawl_score = await crawl_business_website(details)
                llm_payload = await llm_fallback_payload(details, crawl_score, calls_used_in_search=llm_fallback_calls)
                if llm_payload.get("llm_fallback_status") in {"completed", "failed"}:
                    llm_fallback_calls += 1
                crawl_score = apply_llm_fallback(crawl_score, llm_payload)
                crawl_payload = {**crawl_score_payload(crawl_score), **llm_payload}
                industry = "Unknown"
                if crawl_score.tier in {"best", "strong", "weak"} and crawl_score.positive_concepts:
                    industry = _industry_from_signals(crawl_score.positive_concepts)

                master_business = MasterBusiness(
                    place_id=pid,
                    name=details.name,
                    address=details.address,
                    website=details.website,
                    phone_number=details.phone_number,
                    maps_url=details.google_maps_uri or f"https://www.google.com/maps/place/?q=place_id:{pid}",
                    data_source="google_places",
                    country=country,
                    country_code=country_code,
                    industry_sector=industry,
                    industry_type=industry,
                    customer_type=_customer_type_from_tier(crawl_score.tier),
                    website_signal=website_signal,
                    source_query=details.source_query,
                    source_query_language=details.source_query_language,
                    source_keyword=keyword,
                    google_types=details.google_types,
                    google_primary_type=details.google_primary_type,
                    google_primary_type_display_name=details.google_primary_type_display_name,
                    google_business_status=details.google_business_status,
                    **crawl_payload,
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
                    source_query=details.source_query,
                    source_query_language=details.source_query_language,
                    details_status="ok",
                    created_at=datetime.utcnow(),
                )
                try:
                    await db.search_results.insert_one(search_result.model_dump(by_alias=True, exclude_none=True))
                except pymongo.errors.DuplicateKeyError:
                    keyword_results -= 1
                    total_results -= 1

            await db.searches.update_one(
                {"_id": search_id},
                {"$inc": {"keywords_completed": 1, "total_results": keyword_results, "place_details_calls_used": keyword_place_details_calls}},
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
                "place_details_calls_used": total_place_details_calls,
            }
        },
    )

    return search_id
