from datetime import datetime, timedelta

from app.db.connection import get_db
from app.services.places_client import GoogleRateLimitedError, QuotaBlockedError, text_search_places

# Bump when the seed list or discovery method changes in a way that would
# change results — invalidates cached anchors so they get rediscovered.
ANCHOR_VERSION = "v3-name-filtered"

ANCHOR_CACHE_MAX_AGE_DAYS = 180

# Real industrial asset types, not contractor/service phrasing. A query like
# "oil refinery in Gujarat" returns the actual plants -- their coordinates are
# where the real industrial activity is, unlike a state's geometric centroid.
# These plants are also themselves leads (end-user plant operators).
#
# Listed in priority order (index = tier, lower is better), not just for
# reference -- ranking within a state uses this order. Verified live: a raw
# "how many matching anchors nearby" density count favors urban sprawl over
# concentrated heavy industry, because a single-site refinery or fertilizer
# complex has fewer OTHER things immediately next to it than a city center
# does, where many small businesses loosely match ambiguous terms like
# "steel plant" (steel traders) or "chemical plant" (chemical distributors).
# The first few seeds name large, singular, unambiguous facility types --
# a false-positive match on "oil refinery" or "LNG terminal" is rare -- while
# the later seeds are broader terms more prone to matching small unrelated
# businesses that merely mention the word.
ASSET_SEED_KEYWORDS = [
    "oil refinery",
    "petrochemical plant",
    "LNG terminal",
    "fertilizer plant",
    "shipyard",
    "steel plant",
    "power plant",
    "cement plant",
    "port terminal",
    "chemical plant",
]

SEED_PRIORITY = {seed: i for i, seed in enumerate(ASSET_SEED_KEYWORDS)}

# One page per seed keyword is enough -- we want the coordinates of asset
# clusters, not an exhaustive list, and this bounds discovery cost per state.
ANCHORS_PER_SEED_PAGE_SIZE = 20

# Filters out name-coincidence false positives: a business that makes,
# sells, or services equipment FOR the asset type, rather than being one.
# Verified live: "oil refinery" matched "Chempro Technovation - Edible Oil
# Refinery Equipments" (a maker of edible-oil processing machinery) which
# then outranked Gujarat's actual petroleum refineries for the state's one
# fan-out slot.
NAME_FALSE_POSITIVE_MARKERS = [
    "equipment", "equipments", "machinery", "spares", "spare parts",
    "supplier", "suppliers", "manufacturer of", "manufacturers of",
    "consultant", "consultants", "consultancy", "trading co", "traders",
]


def _looks_like_false_positive(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in NAME_FALSE_POSITIVE_MARKERS)


def _anchor_doc_id(country_code: str, state_code: str) -> str:
    return f"{ANCHOR_VERSION}|{country_code.upper()}|{state_code.upper()}"


async def _discover_state_anchors(country: str, country_code: str, state: dict, username: str | None) -> tuple[list[dict], bool]:
    """Runs the asset-seed queries for one state and returns deduped anchors
    with real coordinates, plus whether every seed query actually ran. No
    locationBias is used here -- the whole point is to let Google tell us
    where the industry actually is, not constrain the search to a guess we
    already know is wrong."""
    seen_place_ids: set[str] = set()
    anchors: list[dict] = []
    completed = True
    for seed in ASSET_SEED_KEYWORDS:
        try:
            results, _calls_used, _has_more = await text_search_places(
                seed, country, state["name"], None, ANCHORS_PER_SEED_PAGE_SIZE,
                country_code=country_code, single_variant=True, username=username,
            )
        except (QuotaBlockedError, GoogleRateLimitedError):
            # Quota/rate-limit cut discovery short -- this state's result is
            # incomplete, not "genuinely has no industry". Must not be cached
            # as if it were a real answer (see get_fanout_anchors).
            completed = False
            break
        for place_id, details in results:
            if place_id in seen_place_ids:
                continue
            if details.lat is None or details.lng is None:
                continue
            if _looks_like_false_positive(details.name):
                continue
            seen_place_ids.add(place_id)
            anchors.append({"name": details.name, "lat": details.lat, "lng": details.lng, "place_id": place_id, "seed": seed})
    return anchors, completed


async def get_fanout_anchors(country: str, country_code: str, states: list[dict], username: str | None = None) -> list[dict]:
    """Real-world industrial asset coordinates to fan out across, one entry
    per discovered anchor with its parent state attached. Cached per state in
    Mongo so the (expensive, one-time) discovery queries only run once per
    state per ANCHOR_VERSION within ANCHOR_CACHE_MAX_AGE_DAYS."""
    db = get_db()
    all_anchors: list[dict] = []
    cutoff = datetime.utcnow() - timedelta(days=ANCHOR_CACHE_MAX_AGE_DAYS)

    for state in states:
        doc_id = _anchor_doc_id(country_code, state["code"])
        cached = await db.industrial_anchors.find_one({"_id": doc_id})
        if cached and cached.get("discovered_at", datetime.min) > cutoff:
            anchors = cached.get("anchors", [])
        else:
            anchors, completed = await _discover_state_anchors(country, country_code, state, username)
            # Only cache a genuine answer. A quota/rate-limit cutoff is not
            # "this state has no industry" -- caching it would freeze that
            # wrong conclusion in place for ANCHOR_CACHE_MAX_AGE_DAYS and the
            # next search would never retry it.
            if completed:
                await db.industrial_anchors.update_one(
                    {"_id": doc_id},
                    {"$set": {
                        "country_code": country_code.upper(),
                        "state_code": state["code"],
                        "state_name": state["name"],
                        "anchors": anchors,
                        "discovered_at": datetime.utcnow(),
                    }},
                    upsert=True,
                )
        for anchor in anchors:
            all_anchors.append({**anchor, "state": state["name"], "state_code": state["code"]})

    return all_anchors
