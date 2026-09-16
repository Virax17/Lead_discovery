import asyncio
from datetime import datetime

from bson import ObjectId
import pymongo

from app.config.countries import normalize_country
from app.config.geo import haversine_km, list_cities, list_states
from app.db.connection import get_db
from app.models.schemas import MasterBusiness, PlaceDetails, SearchResult
from app.services.crawl_scorer import CRAWL_VERSION, CrawlScore, crawl_business_website, crawl_score_payload
from app.services.dedup import get_known_business, update_last_seen
from app.services.error_logger import log_error
from app.services.industrial_anchors import SEED_PRIORITY, get_fanout_anchors
from app.services.llm_fallback import apply_llm_fallback, llm_fallback_payload
from app.services.location_search_log import is_recently_searched, mark_searched
from app.services.places_client import GoogleRateLimitedError, QuotaBlockedError, get_place_details, text_search_places
from app.services.website_scanner import scan_website, summarize_signal

# Upper bound on crawling+scoring a single business's website. crawl_scorer's
# own per-request timeouts (10-20s) bound each individual page fetch, but
# nothing previously bounded the crawl as a whole — a redirect loop or a
# hung connection on one business could stall the entire search indefinitely,
# since businesses are processed sequentially.
CRAWL_TIMEOUT_SECONDS = 45

# Hard cap on how many locations a country-level fan-out ever searches,
# regardless of that country's actual state/province count. Raw state count
# varies arbitrarily by country (the US has 60 "states" including scattered
# territories, Russia has 83, many countries have under 10) and has nothing
# to do with how large or business-dense a country really is — using it
# directly as the cost multiplier made cost unpredictable and, for
# many-small-states countries, far more expensive than it needed to be for
# no principled reason. This cap makes cost bounded and identical in shape
# for every country: keywords x min(states, MAX_FANOUT_LOCATIONS).
MAX_FANOUT_LOCATIONS = 25

# Google Places API (New) Text Search's locationBias.circle.radius is
# documented as capped at 50000.0 meters (50km) — this is the maximum
# allowed value, not a starting point that can be grown further.
LOCATION_BIAS_RADIUS_METERS = 50000.0

# Minimum distance (km) kept between any two selected fan-out points.
# Deliberately less than 2x the 50km radius so adjacent circles overlap
# slightly (no coverage gap at the boundary) while still skipping candidates
# close enough to a higher-priority pick that their circle would mostly
# re-search the same ground.
MIN_FANOUT_SEPARATION_KM = 80.0

# Anchor clusters (real industrial sites discovered via Google, see
# industrial_anchors.py) sit much closer together than state centroids do --
# multiple refineries/plants can legitimately cluster within a single
# industrial estate -- so anchors use a tighter separation than the
# state-centroid fallback.
MIN_ANCHOR_SEPARATION_KM = 60.0

# Below this many discovered anchors for a country, anchor discovery is
# treated as having failed or found too little to be worth trusting (e.g. a
# quota block cut discovery short) -- fall back to state centroids rather
# than fan out across a handful of anchors and miss most of the country.
MIN_ANCHORS_TO_TRUST = 5


# Hard cap on how many cities a single state's adaptive drill-down ever
# searches. Only triggered when the state-level query proves (via Google's
# own nextPageToken) that more results exist than it pulled — this bounds
# the worst-case extra cost of that follow-up, since a large state can have
# hundreds of listed cities.
MAX_DRILLDOWN_CITIES_PER_STATE = 10


def _select_spread_out(candidates: list[dict], cap: int, min_separation_km: float) -> list[dict]:
    """Greedily pick up to `cap` candidates (in the given priority order),
    skipping any that fall within `min_separation_km` of an already-picked
    one, so the cap isn't wasted on overlapping locationBias circles when
    several high-priority candidates happen to sit close together. Entries
    without coordinates can't be placed on a circle or measured for
    distance, so they're dropped first. Far-flung entries are never treated
    as distance outliers to drop — only closeness disqualifies a candidate,
    never distance from the rest of the set — so legitimate far-flung places
    (e.g. a country's overseas territories) are never incorrectly excluded."""
    usable = [c for c in candidates if c.get("lat") is not None and c.get("lng") is not None]
    selected: list[dict] = []
    for candidate in usable:
        if len(selected) >= cap:
            break
        too_close = any(
            haversine_km(candidate["lat"], candidate["lng"], s["lat"], s["lng"]) < min_separation_km
            for s in selected
        )
        if not too_close:
            selected.append(candidate)
    return selected


def _ranked_fanout_states(country_code: str) -> list[dict]:
    """States to fan out across, capped at MAX_FANOUT_LOCATIONS and ranked by
    number of known cities in that state — a free, zero-new-data proxy for
    how much real search area/density a state has — before the overlap-aware
    selection in _select_spread_out. A country with zero usable states
    naturally falls through to the no-fan-out fallback in run_region_search."""
    states = list_states(country_code) if country_code else []
    states = sorted(states, key=lambda s: len(list_cities(country_code, s["code"])), reverse=True)
    return _select_spread_out(states, MAX_FANOUT_LOCATIONS, MIN_FANOUT_SEPARATION_KM)


async def _fanout_locations(country: str, country_code: str, username: str | None) -> list[dict]:
    """Locations to fan out across for a country-level search, each carrying
    its own state name/code so downstream skip-log and drill-down lookups
    keep working. Prefers real industrial-asset coordinates (discovered via
    Google -- see industrial_anchors.py) over state centroids, since a
    state's geometric centre is frequently hundreds of km from where its
    actual industry sits (verified: every major hub checked across India,
    the US, and Saudi Arabia fell outside every centroid circle). Falls back
    to state centroids if discovery found too little to trust."""
    states = list_states(country_code) if country_code else []
    if not states:
        return []

    anchors = await get_fanout_anchors(country, country_code, states, username=username)
    if len(anchors) < MIN_ANCHORS_TO_TRUST:
        fallback_states = _ranked_fanout_states(country_code)
        return [{"name": s["name"], "state": s["name"], "state_code": s["code"], "lat": s["lat"], "lng": s["lng"]}
                for s in fallback_states]

    # One candidate circle per state: that state's own most locally-clustered
    # anchor. Ranking all anchors globally by nearby-anchor count instead
    # would let a single sprawling metro area crowd out every other state's
    # slot -- verified this happening: a flat global ranking gave 6 smaller
    # states 2 circles each while Gujarat (home to the Jamnagar refinery
    # complex and the Dahej/Vadodara petrochemical belt) got zero, because
    # metro sprawl matches many loosely-related generic seed hits (small
    # captive power plants, cement depots) within one radius, out-scoring a
    # concentrated but more isolated major industrial cluster. Restricting
    # the density count to each state's own anchors, then picking each
    # state's single best cluster, guarantees every state competes for a
    # slot on equal footing.
    # Within a state, prefer a cluster matched by a higher-priority (more
    # unambiguous) seed keyword over raw nearby-anchor density -- verified
    # live that density alone still favors a city's generic "steel plant"/
    # "chemical plant" trading-company matches over a genuinely major but
    # more isolated single-site facility, even after crowding between states
    # is fixed. Density remains the tiebreaker within the same seed tier.
    by_state: dict[str, list[dict]] = {}
    for anchor in anchors:
        by_state.setdefault(anchor["state"], []).append(anchor)

    def _rank_key(a: dict) -> tuple:
        return (SEED_PRIORITY.get(a.get("seed"), len(SEED_PRIORITY)), -a["_density"])

    candidates = []
    for state_anchors in by_state.values():
        for anchor in state_anchors:
            anchor["_density"] = sum(
                1 for other in state_anchors
                if other is not anchor and haversine_km(anchor["lat"], anchor["lng"], other["lat"], other["lng"]) <= LOCATION_BIAS_RADIUS_METERS / 1000
            )
        candidates.append(min(state_anchors, key=_rank_key))

    candidates.sort(key=_rank_key)
    return _select_spread_out(candidates, MAX_FANOUT_LOCATIONS, MIN_ANCHOR_SEPARATION_KM)


def _drilldown_cities(country_code: str, state_code: str) -> list[dict]:
    """Cities to sweep within one state whose state-level query proved
    under-covered. City entries carry no population/size field, so unlike
    states there's no density proxy to sort by first — cities are taken in
    the order geo_data.json lists them (typically rough population order
    from the underlying GeoNames seed data, but not guaranteed) before the
    same overlap-aware selection used for states."""
    cities = list_cities(country_code, state_code)
    return _select_spread_out(cities, MAX_DRILLDOWN_CITIES_PER_STATE, MIN_FANOUT_SEPARATION_KM)


def _location_bias_circle(state: dict) -> dict | None:
    lat, lng = state.get("lat"), state.get("lng")
    if lat is None or lng is None:
        return None
    return {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": LOCATION_BIAS_RADIUS_METERS}}


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
    if "fertilizer" in joined or "grain_elevator" in joined:
        return "Fertilizer/Agriculture"
    if "power_plant" in joined:
        return "Power"
    if "steel" in joined:
        return "Steel"
    if "wind_turbine" in joined:
        return "Wind energy"
    if "structural_bolting" in joined:
        return "Heavy civil/Infrastructure"
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
    center_lat: float | None = None,
    center_lng: float | None = None,
    radius_km: float | None = None,
) -> ObjectId:
    db = get_db()
    country, country_code = normalize_country(country, country_code)

    # A country-level search (no state/city chosen) auto-fans across a
    # bounded set of that country's states, each searched with a real
    # locationBias circle (a genuine 50km-radius geographic search) instead
    # of one broad "{keyword} in {country}" text query — Google's Text
    # Search returns a stable, relevance-ranked top-N list for a single
    # broad query, so re-running it just resurfaces the same prominent
    # nationwide businesses. A manual state/city search is unaffected
    # (single location, unchanged text-query behavior). A user-drawn custom
    # circle (center_lat/center_lng/radius_km all provided) takes priority
    # over both: it's a deliberate, exact request, so it skips the location
    # skip-log (no natural "state" identity for an arbitrary point) and the
    # adaptive drill-down (no state code to look up cities under) entirely.
    state_by_name: dict[str, dict] = {}
    if center_lat is not None and center_lng is not None and radius_km is not None:
        custom_bias = {"circle": {"center": {"latitude": center_lat, "longitude": center_lng}, "radius": radius_km * 1000}}
        locations = [(None, None, custom_bias)]
        fan_out = False
    elif state or city:
        locations = [(state, city, None)]
        fan_out = False
    else:
        locations_data = await _fanout_locations(country, country_code, username=created_by) if country_code else []
        state_by_name = {a["state"]: {"code": a["state_code"], "name": a["state"]} for a in locations_data}
        # `city` carries the anchor's own name (or the state name itself in
        # the centroid fallback) so multiple anchors sharing one state get
        # distinct skip-log identities -- see the is_recently_searched call
        # below.
        locations = [(a["state"], a["name"], _location_bias_circle(a)) for a in locations_data] or [(None, None, None)]
        fan_out = len(locations) > 1

    keywords_total = len(keywords) * len(locations)
    await db.searches.update_one({"_id": search_id}, {"$set": {"keywords_total": keywords_total}})

    seen_place_ids: set[str] = set()
    quota_limited = False
    google_rate_limited = False
    cancelled = False
    total_results = 0
    total_place_details_calls = 0
    llm_fallback_calls = 0

    async def _cancel_requested() -> bool:
        # Cooperative cancellation for the manual Stop button: cheap enough
        # to check between every (location, keyword) pair given everything
        # else in this loop already round-trips to Mongo just as often.
        doc = await db.searches.find_one({"_id": search_id}, {"cancel_requested": 1})
        return bool(doc and doc.get("cancel_requested"))

    try:
        for loc_state, loc_city, loc_bias in locations:
            if quota_limited or google_rate_limited or cancelled:
                break
            for keyword in keywords:
                if quota_limited or google_rate_limited or cancelled:
                    break
                if await _cancel_requested():
                    cancelled = True
                    break
                keyword_results = 0
                keyword_place_details_calls = 0

                # Fan-out (and manual searches too, for the same benefit) skip
                # a (state, keyword) pair that was already fully searched
                # recently — no wasted API calls re-asking a question we
                # already answered. `city` disambiguates multiple anchors
                # that share the same parent state (see _fanout_locations) --
                # without it, a second anchor in an already-completed state
                # would look identical to the first and be wrongly skipped.
                if fan_out and await is_recently_searched(country_code, loc_state, keyword, city=loc_city):
                    await db.searches.update_one(
                        {"_id": search_id},
                        {"$inc": {"keywords_completed": 1}, "$set": {"updated_at": datetime.utcnow()}},
                    )
                    continue

                try:
                    places, text_search_calls, has_more = await text_search_places(
                        keyword,
                        country,
                        loc_state,
                        loc_city,
                        max_results,
                        country_code=country_code,
                        industries=industries,
                        username=created_by,
                        # A real locationBias circle already targets the
                        # search geographically, so the query text must stay
                        # bare (no "{keyword} in {location}" phrasing) --
                        # Google silently ignores locationBias if textQuery
                        # already names a place. This is keyed on whether a
                        # circle is actually present, not on fan_out, so a
                        # user-drawn custom-area circle gets the same
                        # correct behavior as a fan-out state circle.
                        single_variant=bool(loc_bias),
                        location_bias=loc_bias,
                    )
                    keyword_place_details_calls += text_search_calls
                    total_place_details_calls += text_search_calls

                    # Adaptive drill-down: the state-level circle proved
                    # under-covered (Google had more results than we pulled).
                    # Sweep a bounded, overlap-aware set of that state's
                    # cities instead of accepting the gap — but only ever one
                    # level deep (state -> city), never recursive.
                    state_info = state_by_name.get(loc_state) if fan_out else None
                    if fan_out and has_more and state_info:
                        for drill_city in _drilldown_cities(country_code, state_info["code"]):
                            if await _cancel_requested():
                                cancelled = True
                                break
                            if await is_recently_searched(country_code, loc_state, keyword, city=drill_city["name"]):
                                continue
                            drill_bias = _location_bias_circle(drill_city)
                            drill_places, drill_calls, _drill_has_more = await text_search_places(
                                keyword,
                                country,
                                loc_state,
                                drill_city["name"],
                                max_results,
                                country_code=country_code,
                                industries=industries,
                                username=created_by,
                                single_variant=True,
                                location_bias=drill_bias,
                            )
                            places = places + drill_places
                            keyword_place_details_calls += drill_calls
                            total_place_details_calls += drill_calls
                            await mark_searched(country_code, loc_state, keyword, exhausted=True, city=drill_city["name"])

                    # A cancellation mid-drill-down leaves this (state,
                    # keyword) pair incomplete, not exhausted — it should
                    # stay eligible for an immediate retry, same as a
                    # quota/rate-limit interruption.
                    if fan_out and not cancelled:
                        await mark_searched(country_code, loc_state, keyword, exhausted=True, city=loc_city)
                except QuotaBlockedError:
                    quota_limited = True
                    if fan_out:
                        await mark_searched(country_code, loc_state, keyword, exhausted=False, city=loc_city)
                    await log_error(search_id=search_id, stage="skipped_quota_blocked", place_id=None, error_message=f"Monthly quota limit reached before keyword '{keyword}'.")
                    continue
                except GoogleRateLimitedError:
                    google_rate_limited = True
                    if fan_out:
                        await mark_searched(country_code, loc_state, keyword, exhausted=False, city=loc_city)
                    await log_error(search_id=search_id, stage="skipped_google_rate_limited", place_id=None, error_message=f"Google Places Text Search rate-limited keyword '{keyword}'.")
                    continue
                except Exception as e:
                    await log_error(search_id=search_id, stage="text_search", place_id=None, error_message=f"Failed keyword '{keyword}': {str(e)}")
                    continue

                for pid, text_details in places:
                    if pid in seen_place_ids:
                        continue
                    seen_place_ids.add(pid)

                    # A search can legitimately run for a long time (a full
                    # state fan-out crawls and scores every new business it
                    # finds) — an unexpected exception on ONE business (a DB
                    # blip, an unusual API response shape) must not discard
                    # everything already found and abort the whole run.
                    # QuotaBlockedError/GoogleRateLimitedError still stop the
                    # search via their own inline `break` below; this outer
                    # handler is a safety net for everything else.
                    try:
                        existing = await get_known_business(pid)
                        if existing and existing.get("crawl_version") == CRAWL_VERSION:
                            # Already crawled, scored, and (if eligible) LLM-reviewed
                            # under the current pipeline version — refresh last_seen
                            # for bookkeeping, but don't re-add it as a "result" of
                            # THIS search. A search's results/export should reflect
                            # genuinely new discoveries, not businesses already sitting
                            # in the database from an earlier run.
                            await update_last_seen(existing["_id"], country=country, country_code=country_code)
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
                        try:
                            crawl_score = await asyncio.wait_for(crawl_business_website(details), timeout=CRAWL_TIMEOUT_SECONDS)
                        except asyncio.TimeoutError:
                            await log_error(search_id=search_id, stage="crawl_timeout", place_id=pid, error_message=f"Crawling {details.website} exceeded {CRAWL_TIMEOUT_SECONDS}s, skipped.")
                            crawl_score = CrawlScore(status="failed", score=0, tier="unknown", reason=f"Crawl timed out after {CRAWL_TIMEOUT_SECONDS}s.", pages_checked=0)
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
                    except (QuotaBlockedError, GoogleRateLimitedError):
                        raise
                    except Exception as e:
                        await log_error(search_id=search_id, stage="business_processing", place_id=pid, error_message=str(e))
                        continue

                await db.searches.update_one(
                    {"_id": search_id},
                    {
                        "$inc": {"keywords_completed": 1, "total_results": keyword_results, "place_details_calls_used": keyword_place_details_calls},
                        "$set": {"updated_at": datetime.utcnow()},
                    },
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

    update_fields = {
        "status": final_status,
        "completed_at": datetime.utcnow(),
        "total_results": total_results,
        "place_details_calls_used": total_place_details_calls,
    }
    if cancelled:
        update_fields["failure_reason"] = "Manually stopped by user before completion. Results found so far are saved."

    await db.searches.update_one({"_id": search_id}, {"$set": update_fields})

    return search_id
