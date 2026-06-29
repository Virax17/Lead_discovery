import httpx
import asyncio
from app.config.settings import settings
from app.config.places_fields import TEXT_SEARCH_FIELD_MASK, PLACE_DETAILS_FIELD_MASK
from app.config.retry import MAX_RETRIES, BACKOFF_SECONDS
from app.models.schemas import PlaceDetails
from app.services.quota_tracker import check_quota_before_call, increment_usage
from app.services.error_logger import log_error

from urllib.parse import urlparse, urlunparse

class QuotaBlockedError(Exception):
    pass

async def text_search_ids(keyword: str, country: str, country_code: str, state: str | None, city: str | None, max_results: int) -> list[str]:
    # Build query
    location_parts = [city, state, country]
    location = ", ".join(filter(None, location_parts))
    query = f"{keyword} in {location}"

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": TEXT_SEARCH_FIELD_MASK,
        "Content-Type": "application/json"
    }

    place_ids = []
    page_token = None

    async with httpx.AsyncClient() as client:
        while len(place_ids) < max_results:
            payload = {
                "textQuery": query,
                "regionCode": country_code
            }
            if page_token:
                payload["pageToken"] = page_token

            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                places = data.get("places", [])
                for p in places:
                    if "id" in p:
                        place_ids.append(p["id"])
                        if len(place_ids) >= max_results:
                            break

                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                await log_error(search_id=None, stage="text_search", place_id=None, error_message=str(e))
                break

    return place_ids

def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, '', ''))
    except:
        return url

async def get_place_details(place_id: str) -> PlaceDetails | None:
    # Pre-call quota check
    status = await check_quota_before_call()
    if status == 'BLOCKED':
        raise QuotaBlockedError("Monthly quota limit reached.")

    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": PLACE_DETAILS_FIELD_MASK
    }

    async with httpx.AsyncClient() as client:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                # Success
                await increment_usage()
                
                data = response.json()
                return PlaceDetails(
                    name=data.get("displayName", {}).get("text", "Unknown"),
                    address=data.get("formattedAddress", "Unknown"),
                    website=_clean_url(data.get("websiteUri")),
                    phone_number=data.get("internationalPhoneNumber")
                )
            except Exception as e:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt])
                else:
                    await log_error(search_id=None, stage="place_details", place_id=place_id, error_message=str(e))
                    return None
