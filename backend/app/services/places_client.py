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


class GoogleRateLimitedError(Exception):
    pass


BUSINESS_SEARCH_VARIANTS = [
    "{keyword} in {location}",
    "{keyword} companies in {location}",
    "{keyword} suppliers in {location}",
    "{keyword} services in {location}",
]

INDUSTRY_SEARCH_VARIANTS = [
    "{keyword} for {industry} in {location}",
    "{industry} {keyword} companies in {location}",
]


def _country_code_from_components(address_components: list[dict]) -> str | None:
    for component in address_components:
        if "country" in component.get("types", []):
            return component.get("shortText")
    return None


def _details_from_place_payload(place: dict) -> PlaceDetails:
    return PlaceDetails(
        name=place.get("displayName", {}).get("text", "Unknown"),
        address=place.get("formattedAddress", "Unknown"),
        website=_clean_url(place.get("websiteUri")),
        phone_number=place.get("internationalPhoneNumber"),
        country_code=_country_code_from_components(place.get("addressComponents", [])),
    )


def _build_text_queries(keyword: str, location: str, industries: list[str] | None = None) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()

    def add(template: str, **kwargs):
        query = template.format(**kwargs).strip()
        normalized = " ".join(query.lower().split())
        if query and normalized not in seen:
            seen.add(normalized)
            queries.append(query)

    for template in BUSINESS_SEARCH_VARIANTS:
        add(template, keyword=keyword, location=location)

    for industry in (industries or [])[:3]:
        for template in INDUSTRY_SEARCH_VARIANTS:
            add(template, keyword=keyword, industry=industry, location=location)

    return queries

async def text_search_ids(keyword: str, country: str, state: str | None, city: str | None, max_results: int, country_code: str | None = None) -> list[str]:
    results, _calls_used = await text_search_places(keyword, country, state, city, max_results, country_code=country_code)
    return [place_id for place_id, _details in results]


async def text_search_places(
    keyword: str,
    country: str,
    state: str | None,
    city: str | None,
    max_results: int,
    country_code: str | None = None,
    industries: list[str] | None = None,
    username: str | None = None,
) -> tuple[list[tuple[str, PlaceDetails]], int]:
    # Build query
    location_parts = [city, state, country]
    location = ", ".join(filter(None, location_parts))
    queries = _build_text_queries(keyword, location, industries)

    max_results = min(max_results, 100)

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": TEXT_SEARCH_FIELD_MASK,
        "Content-Type": "application/json"
    }

    results: list[tuple[str, PlaceDetails]] = []
    seen_place_ids: set[str] = set()
    calls_used = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        for query in queries:
            page_token = None
            while len(results) < max_results:
                payload = {
                    "textQuery": query
                }
                if country_code:
                    payload["regionCode"] = country_code
                if page_token:
                    payload["pageToken"] = page_token

                try:
                    status = await check_quota_before_call(username=username)
                    if status in {"BLOCKED", "USER_BLOCKED"}:
                        raise QuotaBlockedError("Monthly quota limit reached.")

                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code == 429:
                        await log_error(search_id=None, stage="text_search_rate_limited", place_id=None, error_message=response.text[:1000])
                        raise GoogleRateLimitedError("Google Places Text Search rate limit reached.")
                    response.raise_for_status()
                    await increment_usage(username=username)
                    calls_used += 1
                    data = response.json()

                    places = data.get("places", [])
                    for p in places:
                        place_id = p.get("id")
                        if place_id and place_id not in seen_place_ids:
                            seen_place_ids.add(place_id)
                            results.append((place_id, _details_from_place_payload(p)))
                            if len(results) >= max_results:
                                break

                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
                except GoogleRateLimitedError:
                    raise
                except QuotaBlockedError:
                    raise
                except Exception as e:
                    await log_error(search_id=None, stage="text_search", place_id=None, error_message=f"{query}: {str(e)}")
                    break
            if len(results) >= max_results:
                break

    return results, calls_used

def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, '', ''))
    except:
        return url

async def get_place_details(place_id: str, username: str | None = None) -> PlaceDetails | None:
    # Pre-call quota check
    status = await check_quota_before_call(username=username)
    if status in {'BLOCKED', 'USER_BLOCKED'}:
        raise QuotaBlockedError("Monthly quota limit reached.")

    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": PLACE_DETAILS_FIELD_MASK
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if attempt < MAX_RETRIES:
                        delay = int(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                        await asyncio.sleep(delay)
                        continue
                    await log_error(search_id=None, stage="place_details_rate_limited", place_id=place_id, error_message=response.text[:1000])
                    raise GoogleRateLimitedError("Google Places API rate limit reached.")

                response.raise_for_status()
                
                # Success
                await increment_usage(username=username)
                
                data = response.json()
                return PlaceDetails(
                    name=data.get("displayName", {}).get("text", "Unknown"),
                    address=data.get("formattedAddress", "Unknown"),
                    website=_clean_url(data.get("websiteUri")),
                    phone_number=data.get("internationalPhoneNumber"),
                    country_code=_country_code_from_components(data.get("addressComponents", []))
                )
            except GoogleRateLimitedError:
                raise
            except Exception as e:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt])
                else:
                    await log_error(search_id=None, stage="place_details", place_id=place_id, error_message=str(e))
                    return None
