"""Mongo persistence + cache for Company Enrichment.

Collection `company_enrichments` -- one document per company, keyed by
`cache_key` (normalized domain when a website is known, else "name:<name_key>").
It stores the extracted fields AND the crawled page text, so:

  * re-enriching a known company/domain costs no crawl and no LLM call, and
  * Lead Discovery's Google-Places/map pipeline can reuse the crawled pages
    (`get_cached_pages`) or look a company up by domain / name / place_id
    (`find_enrichment`) instead of crawling the same site again.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.config.settings import settings
from app.db.connection import get_db
from app.services.company_cache import normalize_domain
from app.services.crawl_scorer import SCORING_VERSION
from app.services.seller_profiles import DEFAULT_PROFILE, get_profile
from app.services.enrichment_engine import (
    EMPTY_RESULT,
    FREE_EMAIL_DOMAINS,
    enrich_company,
    score_pages,
    normalize_if_url,
    resolve_from_email,
)

COLLECTION = "company_enrichments"
# v2: 8-page crawl (contact/about first), contacts + HQ extraction, fit scoring.
ENRICHMENT_CRAWL_VERSION = "enrichment-crawl-v2"
# Bump when the LLM verdict rules change: stored companies are re-judged from
# their saved pages (no re-crawl) the next time they are enriched.
ENRICHMENT_LLM_VERSION = "verdict-v3"  # v2 added the A/B/C turnover class; v3 tolerant basis parsing

_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|plc|corp|corporation|co|company|gmbh|ag|sa|sdn|bhd|pvt|pte|llp|bv|nv|oy|ab|as|spa|srl|se|kg|nv|pty)\b"
)


def name_key(name: str | None) -> str | None:
    """Normalized company name used for name-based lookups (case/accents/
    punctuation/legal-suffix insensitive). Names in non-Latin scripts keep their own
    (case-folded) letters, so they still get a key instead of silently losing it."""
    if not name:
        return None
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _LEGAL_SUFFIXES.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s:
        return s
    u = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", name).casefold())
    return re.sub(r"\s+", " ", u).strip()[:120] or None


def _is_fresh(doc: dict) -> bool:
    ts = doc.get("last_crawled_at")
    if not ts or doc.get("crawl_status") != "ok":
        return False
    # an older crawl format lacks contacts/HQ -- recrawl once to upgrade it
    if doc.get("crawl_version") != ENRICHMENT_CRAWL_VERSION:
        return False
    return ts > datetime.utcnow() - timedelta(days=settings.enrichment_cache_max_age_days)


def serialize(doc: dict, include_pages: bool = False) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    pages = doc.pop("crawled_pages", [])
    doc["pages_crawled"] = len(pages)
    if include_pages:
        doc["crawled_pages"] = pages
    return doc


FIT_KEYS = (
    "crawl_score", "crawl_tier", "business_role", "business_role_reason", "customer_type", "crawl_reason",
    "positive_concepts", "negative_concepts", "crawl_evidence", "crawl_evidence_urls", "detected_language",
    "scoring_version",
)
PROFILE_SLOT_KEYS = (
    "company_category", "is_competitor", "llm_decision", "llm_decision_reason",
    "override_decision", "override_note", "override_by", "override_at",
)


def apply_profile(doc: dict, profile_id: str) -> dict:
    """One company, seen through one seller's eyes. The crawl and company facts are
    shared; the verdict, reason, "why it fits" list, competitor flag, keyword score and
    the user's own override are that seller's. Tritorc's live at the top level (as they
    always have); every other seller's live under `profiles.<id>`."""
    profile = get_profile(profile_id)
    d = dict(doc)
    d["profile"] = profile.id
    d["profile_name"] = profile.name
    if profile.id == DEFAULT_PROFILE:
        d["fit_products"] = d.get("tritorc_relevance") or []
        d["judged_for_profile"] = bool(d.get("llm_version"))
        d.pop("profiles", None)
        return d
    if not d.get("id"):  # unsaved result: already in this seller's shape
        d["fit_products"] = d.get("fit_products") or d.get(profile.fit_key) or []
        d["judged_for_profile"] = bool(d.get("llm_decision"))
        return d
    slot = (d.get("profiles") or {}).get(profile.id) or {}
    for k in PROFILE_SLOT_KEYS:
        d[k] = slot.get(k)
    d["is_competitor"] = bool(slot.get("is_competitor"))
    d["fit_products"] = slot.get("fit_products") or []
    d["tritorc_relevance"] = d["fit_products"]  # legacy key the list and export still read
    fit = slot.get("fit") or {}
    for k in FIT_KEYS:  # this seller's keyword score replaces Tritorc's
        d[k] = fit.get(k)
    d["llm_version"] = slot.get("llm_version")
    d["judged_for_profile"] = bool(slot.get("llm_version"))
    d.pop("profiles", None)
    return d


def membership_filter(profile_id: str) -> dict:
    """Which stored companies belong to a seller's own list. Tritorc's list is everything enriched
    for Tritorc (including every record that predates sellers); another seller's list holds only
    companies that have been judged for that seller. The website crawl itself is shared, but a
    company only shows up in a seller's list, count and exports once it was enriched for them."""
    pid = get_profile(profile_id).id
    if pid == DEFAULT_PROFILE:
        return {"$or": [{"profile_ids": DEFAULT_PROFILE}, {"profile_ids": {"$exists": False}}]}
    return {"$or": [{"profile_ids": pid}, {f"profiles.{pid}.llm_version": {"$exists": True}}]}


def _membership_ids(existing: dict | None, profile_id: str) -> list[str]:
    """Seller lists a record should be in after `profile_id` touches it. A record from before sellers
    existed has no `profile_ids` and counts as Tritorc's; the first time another seller adds itself the
    field gets created, so Tritorc must be written in explicitly or the record would drop out of its list."""
    if existing is not None and "profile_ids" not in existing and profile_id != DEFAULT_PROFILE:
        return [DEFAULT_PROFILE, profile_id]
    return [profile_id]


def _is_url_or_email(entry: str) -> bool:
    return bool(resolve_from_email(entry) or normalize_if_url(entry))


def input_domain(entry: str) -> str | None:
    """Domain implied by the raw input line itself (URL or company email),
    without any network call. None for plain names / webmail addresses."""
    em = resolve_from_email(entry)
    if em:
        return None if em[3] else normalize_domain(em[0])
    url = normalize_if_url(entry)
    return normalize_domain(url) if url else None


async def find_enrichment(
    domain: str | None = None,
    name: str | None = None,
    place_id: str | None = None,
    include_pages: bool = False,
) -> dict | None:
    """Pure read -- never crawls. The lookup the map/Places pipeline uses."""
    coll = get_db()[COLLECTION]
    doc = None
    if place_id:
        doc = await coll.find_one({"place_ids": place_id})
    if not doc and domain:
        doc = await coll.find_one({"domain": normalize_domain(domain) or domain.lower()})
    if not doc and name:
        nkey = name_key(name)
        if nkey:
            doc = await coll.find_one({"name_keys": nkey})
    return serialize(doc, include_pages) if doc else None


async def get_cached_pages(domain: str) -> list[dict] | None:
    """Crawled page text for a domain if a fresh successful crawl exists, so
    callers can score/extract without fetching the site again."""
    doc = await get_db()[COLLECTION].find_one({"domain": normalize_domain(domain) or domain.lower()})
    if not doc or not doc.get("crawled_pages") or doc.get("crawl_status") != "ok":
        return None
    ts = doc.get("last_crawled_at")
    if not ts or ts < datetime.utcnow() - timedelta(days=settings.enrichment_cache_max_age_days):
        return None
    return doc["crawled_pages"]


ENRICHMENT_SUMMARY_FIELDS = (
    "company_name", "business_description", "country", "hq_city", "hq_address", "industry",
    "company_category", "is_competitor", "employee_count", "customer_type",
    "llm_decision", "llm_decision_reason", "override_decision", "override_note",
    "turnover_class", "turnover_basis", "annual_turnover",
    "tritorc_relevance", "projects_or_recent_activity", "key_operations",
    "contact_emails", "contact_phones", "social_links", "crawl_tier", "crawl_score", "business_role",
)


async def enrichment_summaries(db, docs: list[dict]) -> dict:
    """LLM-enriched profile for a page of businesses, keyed by domain. One
    query for the whole page; crawled page text is not loaded."""
    domains = {normalize_domain(d.get("website") or "") for d in docs}
    domains.discard(None)
    if not domains:
        return {}
    projection = {field: 1 for field in ENRICHMENT_SUMMARY_FIELDS}
    projection["domain"] = 1
    found = {}
    async for e in db[COLLECTION].find({"domain": {"$in": list(domains)}, **membership_filter(DEFAULT_PROFILE)}, projection):
        found[e["domain"]] = {k: e.get(k) for k in ENRICHMENT_SUMMARY_FIELDS}
    return found


async def link_place_id(domain: str, place_id: str) -> None:
    """For the Places/map pipeline: tie a master_businesses place_id to an
    enrichment so find_enrichment(place_id=...) works."""
    await get_db()[COLLECTION].update_one(
        {"domain": normalize_domain(domain) or domain.lower()}, {"$addToSet": {"place_ids": place_id}}
    )


async def _lookup_for_input(entry: str) -> dict | None:
    coll = get_db()[COLLECTION]
    domain = input_domain(entry)
    if domain:
        return await coll.find_one({"domain": domain})
    if _is_url_or_email(entry):
        return None  # webmail address: nothing reliable to key on
    nkey = name_key(entry)
    return await coll.find_one({"name_keys": nkey}) if nkey else None


def _oid(value) -> ObjectId | None:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


async def correct_match(client, input_text: str, website: str, wrong_id: str | None, username: str, profile: str = DEFAULT_PROFILE) -> dict:
    """The user says `input_text` was matched to the wrong company. Detach the
    typed name from the wrong record (so it can't match it again), enrich the
    website they gave, and attach the typed name to that record instead."""
    coll = get_db()[COLLECTION]
    nkey = name_key(input_text)
    wrong = _oid(wrong_id)
    if wrong:
        pull: dict = {"input_aliases": input_text}
        if nkey:
            pull["name_keys"] = nkey
        await coll.update_one({"_id": wrong}, {"$pull": pull})
    doc = await get_or_enrich(client, website, username, profile=profile)
    right = _oid(doc.get("id"))
    if right:
        add: dict = {"input_aliases": input_text}
        if nkey:
            add["name_keys"] = nkey
        await coll.update_one({"_id": right}, {"$addToSet": add})
    return doc


async def set_override(doc_id: str, decision: str | None, note: str | None, username: str, profile: str = DEFAULT_PROFILE) -> dict | None:
    """Record the user's own accept/review/reject call. It lives in separate
    fields, so re-enriching never overwrites it. decision=None clears it."""
    oid = _oid(doc_id)
    if not oid:
        return None
    coll = get_db()[COLLECTION]
    profile = get_profile(profile).id
    prefix = "" if profile == DEFAULT_PROFILE else f"profiles.{profile}."
    if decision in ("accept", "review", "reject"):
        update = {"$set": {
            f"{prefix}override_decision": decision,
            f"{prefix}override_note": (note or "").strip()[:300] or None,
            f"{prefix}override_by": username,
            f"{prefix}override_at": datetime.utcnow(),
        }}
    else:
        update = {"$unset": {f"{prefix}{k}": "" for k in ("override_decision", "override_note", "override_by", "override_at")}}
    res = await coll.update_one({"_id": oid}, update)
    if res.matched_count == 0:
        return None
    return apply_profile(serialize(await coll.find_one({"_id": oid})), profile)


_REJUDGE_SCALARS = (
    "country", "hq_city", "hq_address", "industry", "company_category", "business_description", "employee_count",
)


async def _rejudge(client, entry: str, cached: dict) -> dict | None:
    """Re-run only the LLM on the stored pages (no crawl) to add the verdict
    and any improved fields. An LLM failure propagates so the caller can tell the user."""
    loop = asyncio.get_running_loop()
    data, _pages, meta = await loop.run_in_executor(
        None, enrich_company, client, entry, cached["crawled_pages"], cached.get("website")
    )
    now = datetime.utcnow()
    update = {k: data[k] for k in _REJUDGE_SCALARS if data.get(k) not in (None, "")}
    update.update({k: data[k] for k in ("key_operations", "projects_or_recent_activity", "tritorc_relevance") if data.get(k)})
    update.update(
        {
            "is_competitor": bool(data.get("is_competitor")),
            "llm_decision": data.get("llm_decision"),
            "llm_decision_reason": data.get("llm_decision_reason"),
            "turnover_class": data.get("turnover_class"),
            "turnover_basis": data.get("turnover_basis"),
            "annual_turnover": data.get("annual_turnover"),
            "llm_version": ENRICHMENT_LLM_VERSION,
            "llm_model": meta.get("llm_model") or settings.groq_model,
            "llm_provider": meta.get("llm_provider"),
            "updated_at": now,
            **meta.get("fit", {}),
        }
    )
    coll = get_db()[COLLECTION]
    await coll.update_one(
        {"_id": cached["_id"]},
        {"$set": update, "$inc": {"hit_count": 1}, "$addToSet": {"profile_ids": DEFAULT_PROFILE}},
    )
    return await coll.find_one({"_id": cached["_id"]})


_GENERIC_SCALARS = ("country", "hq_city", "hq_address", "industry", "business_description", "employee_count")


def _profile_slot(data: dict, meta: dict) -> dict:
    """What one seller's judgement of a company looks like when stored."""
    return {
        "company_category": data.get("company_category"),
        "is_competitor": bool(data.get("is_competitor")),
        "llm_decision": data.get("llm_decision"),
        "llm_decision_reason": data.get("llm_decision_reason"),
        "fit_products": data.get("fit_products") or [],
        "fit": meta.get("fit", {}),
        "llm_version": ENRICHMENT_LLM_VERSION,
        "llm_model": meta.get("llm_model") or settings.groq_model,
        "llm_provider": meta.get("llm_provider"),
        "judged_at": datetime.utcnow(),
    }


async def _judge_profile(client, entry: str, cached: dict, profile_id: str) -> dict | None:
    """Judge a stored company for another seller (e.g. Ozat) from its saved pages:
    no crawl, one LLM call. Existing facts and the user's override are kept."""
    loop = asyncio.get_running_loop()
    data, _pages, meta = await loop.run_in_executor(
        None, enrich_company, client, entry, cached["crawled_pages"], cached.get("website"), profile_id
    )
    update = {f"profiles.{profile_id}.{k}": v for k, v in _profile_slot(data, meta).items()}
    for k in _GENERIC_SCALARS:  # only fill company facts the first run left empty
        if cached.get(k) in (None, "") and data.get(k) not in (None, ""):
            update[k] = data[k]
    for k in ("key_operations", "projects_or_recent_activity"):
        if not cached.get(k) and data.get(k):
            update[k] = data[k]
    if not cached.get("turnover_class") and data.get("turnover_class"):
        update.update({k: data.get(k) for k in ("turnover_class", "turnover_basis", "annual_turnover")})
    update["updated_at"] = datetime.utcnow()
    coll = get_db()[COLLECTION]
    await coll.update_one(
        {"_id": cached["_id"]},
        {"$set": update, "$inc": {"hit_count": 1}, "$addToSet": {"profile_ids": {"$each": _membership_ids(cached, profile_id)}}},
    )
    return await coll.find_one({"_id": cached["_id"]})


_COMPANY_LOCKS: dict[str, list] = {}  # key -> [lock, number of requests using it]


async def get_or_enrich(client, entry: str, username: str, force_refresh: bool = False, profile: str = DEFAULT_PROFILE) -> dict:
    """One request per company at a time: if the same company is requested again while it is being crawled
    (two tabs, two sellers, a repeated name), the second waits and then finds the saved result instead of crawling again."""
    entry = entry.strip()
    key = input_domain(entry) or name_key(entry) or entry.lower()
    slot = _COMPANY_LOCKS.setdefault(key, [asyncio.Lock(), 0])
    slot[1] += 1
    try:
        async with slot[0]:
            return await _get_or_enrich(client, entry, username, force_refresh, profile)
    finally:
        slot[1] -= 1
        if slot[1] <= 0:
            _COMPANY_LOCKS.pop(key, None)


async def _get_or_enrich(client, entry: str, username: str, force_refresh: bool = False, profile: str = DEFAULT_PROFILE) -> dict:
    """cache -> (crawl + LLM) -> store, seen as `profile` (the seller we are judging for).
    The crawl is shared by every profile, so judging a known company for a second
    seller costs one LLM call and no crawl. Result carries `cache_hit`."""
    profile = get_profile(profile).id
    entry = entry.strip()
    cached = None if force_refresh else await _lookup_for_input(entry)
    fresh = bool(cached) and _is_fresh(cached)

    if fresh and cached.get("crawled_pages"):
        if profile == DEFAULT_PROFILE:
            needs_judging = cached.get("llm_version") != ENRICHMENT_LLM_VERSION
            judged = await _rejudge(client, entry, cached) if needs_judging else None
        else:
            slot = (cached.get("profiles") or {}).get(profile) or {}
            needs_judging = slot.get("llm_version") != ENRICHMENT_LLM_VERSION
            judged = await _judge_profile(client, entry, cached, profile) if needs_judging else None
        if judged:
            return {**apply_profile(serialize(judged), profile), "cache_hit": True, "rejudged": True}

    if fresh:
        update: dict = {"$inc": {"hit_count": 1}}
        if cached.get("scoring_version") != SCORING_VERSION and cached.get("crawled_pages"):
            # scorer changed since this was stored: re-score the saved pages (no crawl)
            fit = score_pages(cached.get("company_name"), cached.get("website"), cached["crawled_pages"])
            cached.update(fit)
            update["$set"] = fit
        await get_db()[COLLECTION].update_one({"_id": cached["_id"]}, update)
        return {**apply_profile(serialize(cached), profile), "cache_hit": True}

    loop = asyncio.get_running_loop()
    data, pages, meta = await loop.run_in_executor(None, enrich_company, client, entry, None, None, profile)
    saved = await _save(entry, username, data, pages, meta, profile)
    return {**apply_profile(saved, profile), "cache_hit": False}


async def _save(entry: str, username: str, data: dict, pages: list, meta: dict, profile_id: str = DEFAULT_PROFILE) -> dict:
    coll = get_db()[COLLECTION]
    profile_id = get_profile(profile_id).id
    is_default = profile_id == DEFAULT_PROFILE
    now = datetime.utcnow()
    domain = normalize_domain(data.get("website") or "")
    if domain in FREE_EMAIL_DOMAINS:
        domain = None
    nkey = name_key(data.get("company_name"))
    entry_key = None if _is_url_or_email(entry) else name_key(entry)
    # the domain's first label ("bilfinger" for bilfinger.com) doubles as a
    # name key so bare-brand lookups from the map pipeline still hit.
    domain_stem = name_key(domain.split(".")[0]) if domain else None
    key = domain or (f"name:{nkey or entry_key}" if (nkey or entry_key) else None)
    if not key:
        # nothing stable to key on (e.g. webmail address, no company found)
        return {**EMPTY_RESULT, **data, "id": None, "domain": None, "pages_crawled": 0}

    fields = {
        **{k: data.get(k) for k in (
            "company_name", "website", "country", "hq_city", "hq_address", "industry",
            "business_description", "employee_count",
            "turnover_class", "turnover_basis", "annual_turnover",
        )},
        "contact_emails": meta["contacts"]["emails"],
        "contact_phones": meta["contacts"]["phones"],
        "social_links": meta["contacts"]["social_links"],
        # company-level crawl_* fields are always the Tritorc scorer's; other sellers' scores live in their slot
        **(meta.get("fit", {}) if is_default else meta.get("fit_default", {})),
        **{k: data.get(k) or [] for k in ("key_operations", "projects_or_recent_activity")},
        "domain": domain,
        "crawled_pages": pages,
        "crawl_status": meta["crawl_status"],
        "crawl_error": meta["crawl_error"],
        "crawl_version": ENRICHMENT_CRAWL_VERSION,
        "last_crawled_at": now,
        "llm_model": meta.get("llm_model") or settings.groq_model,
        "llm_provider": meta.get("llm_provider"),
        "enriched_at": now,
        "updated_at": now,
    }
    existing = await coll.find_one({"cache_key": key}, {"profile_ids": 1, "llm_version": 1, "profiles": 1})
    on_insert = {"created_by": username, "created_at": now, "hit_count": 0, "place_ids": []}
    if is_default:
        fields.update({
            "company_category": data.get("company_category"),
            "is_competitor": bool(data.get("is_competitor")),
            "llm_decision": data.get("llm_decision"),
            "llm_decision_reason": data.get("llm_decision_reason"),
            "llm_version": ENRICHMENT_LLM_VERSION,
            "tritorc_relevance": data.get("tritorc_relevance") or [],
        })
    else:
        # another seller's judgement goes in its own slot; Tritorc's top-level judgement is left untouched
        fields.update({f"profiles.{profile_id}.{k}": v for k, v in _profile_slot(data, meta).items()})
        on_insert.update({
            "company_category": None, "is_competitor": False, "llm_decision": None,
            "llm_decision_reason": None, "llm_version": None, "tritorc_relevance": [],
        })
    # this crawl replaced the shared facts, so every OTHER seller's earlier verdict was based on the old crawl:
    # mark it stale and it is re-judged from the new pages (no re-crawl) the next time that company is opened
    if existing:
        if not is_default and existing.get("llm_version"):
            fields["llm_version"] = "stale"
        for other_id, slot_doc in (existing.get("profiles") or {}).items():
            if other_id != profile_id and isinstance(slot_doc, dict) and slot_doc.get("llm_version"):
                fields[f"profiles.{other_id}.llm_version"] = "stale"
    update = {
        "$set": fields,
        "$addToSet": {
            "input_aliases": entry,
            "name_keys": {"$each": [k for k in (nkey, entry_key, domain_stem) if k]},
            "profile_ids": {"$each": _membership_ids(existing, profile_id)},
        },
        "$setOnInsert": on_insert,
    }
    try:
        await coll.update_one({"cache_key": key}, update, upsert=True)
    except DuplicateKeyError:
        # another request inserted the same company between our read and write: the document exists now, so just update it
        await coll.update_one({"cache_key": key}, update, upsert=True)
    return serialize(await coll.find_one({"cache_key": key}))
