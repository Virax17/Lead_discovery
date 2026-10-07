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

from app.config.settings import settings
from app.db.connection import get_db
from app.services.company_cache import normalize_domain
from app.services.crawl_scorer import SCORING_VERSION
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
    punctuation/legal-suffix insensitive)."""
    if not name:
        return None
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _LEGAL_SUFFIXES.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


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
    async for e in db[COLLECTION].find({"domain": {"$in": list(domains)}}, projection):
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


async def correct_match(client, input_text: str, website: str, wrong_id: str | None, username: str) -> dict:
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
    doc = await get_or_enrich(client, website, username)
    right = _oid(doc.get("id"))
    if right:
        add: dict = {"input_aliases": input_text}
        if nkey:
            add["name_keys"] = nkey
        await coll.update_one({"_id": right}, {"$addToSet": add})
    return doc


async def set_override(doc_id: str, decision: str | None, note: str | None, username: str) -> dict | None:
    """Record the user's own accept/review/reject call. It lives in separate
    fields, so re-enriching never overwrites it. decision=None clears it."""
    oid = _oid(doc_id)
    if not oid:
        return None
    coll = get_db()[COLLECTION]
    if decision in ("accept", "review", "reject"):
        update = {"$set": {
            "override_decision": decision,
            "override_note": (note or "").strip()[:300] or None,
            "override_by": username,
            "override_at": datetime.utcnow(),
        }}
    else:
        update = {"$unset": {"override_decision": "", "override_note": "", "override_by": "", "override_at": ""}}
    res = await coll.update_one({"_id": oid}, update)
    if res.matched_count == 0:
        return None
    return serialize(await coll.find_one({"_id": oid}))


_REJUDGE_SCALARS = (
    "country", "hq_city", "hq_address", "industry", "company_category", "business_description", "employee_count",
)


async def _rejudge(client, entry: str, cached: dict) -> dict | None:
    """Re-run only the LLM on the stored pages (no crawl) to add the verdict
    and any improved fields. Returns the updated document, or None if the LLM
    call fails (the caller then serves the cached record unchanged)."""
    loop = asyncio.get_running_loop()
    try:
        data, _pages, meta = await loop.run_in_executor(
            None, enrich_company, client, entry, cached["crawled_pages"], cached.get("website")
        )
    except Exception:
        return None
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
            "llm_model": settings.groq_model,
            "updated_at": now,
            **meta.get("fit", {}),
        }
    )
    coll = get_db()[COLLECTION]
    await coll.update_one({"_id": cached["_id"]}, {"$set": update, "$inc": {"hit_count": 1}})
    return await coll.find_one({"_id": cached["_id"]})


async def get_or_enrich(client, entry: str, username: str, force_refresh: bool = False) -> dict:
    """cache -> (crawl + LLM) -> store. Result carries `cache_hit`."""
    entry = entry.strip()
    cached = None if force_refresh else await _lookup_for_input(entry)
    if cached and _is_fresh(cached) and cached.get("crawled_pages") and cached.get("llm_version") != ENRICHMENT_LLM_VERSION:
        rejudged = await _rejudge(client, entry, cached)
        if rejudged:
            return {**serialize(rejudged), "cache_hit": True, "rejudged": True}
    if cached and _is_fresh(cached):
        update: dict = {"$inc": {"hit_count": 1}}
        if cached.get("scoring_version") != SCORING_VERSION and cached.get("crawled_pages"):
            # scorer changed since this was stored: re-score the saved pages (no crawl)
            fit = score_pages(cached.get("company_name"), cached.get("website"), cached["crawled_pages"])
            cached.update(fit)
            update["$set"] = fit
        await get_db()[COLLECTION].update_one({"_id": cached["_id"]}, update)
        return {**serialize(cached), "cache_hit": True}

    loop = asyncio.get_running_loop()
    data, pages, meta = await loop.run_in_executor(None, enrich_company, client, entry)
    return {**await _save(entry, username, data, pages, meta), "cache_hit": False}


async def _save(entry: str, username: str, data: dict, pages: list, meta: dict) -> dict:
    coll = get_db()[COLLECTION]
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
            "company_name", "website", "country", "hq_city", "hq_address", "industry", "company_category",
            "business_description", "employee_count", "llm_decision", "llm_decision_reason",
            "turnover_class", "turnover_basis", "annual_turnover",
        )},
        "is_competitor": bool(data.get("is_competitor")),
        "llm_version": ENRICHMENT_LLM_VERSION,
        "contact_emails": meta["contacts"]["emails"],
        "contact_phones": meta["contacts"]["phones"],
        "social_links": meta["contacts"]["social_links"],
        **meta.get("fit", {}),
        **{k: data.get(k) or [] for k in ("key_operations", "projects_or_recent_activity", "tritorc_relevance")},
        "domain": domain,
        "crawled_pages": pages,
        "crawl_status": meta["crawl_status"],
        "crawl_error": meta["crawl_error"],
        "crawl_version": ENRICHMENT_CRAWL_VERSION,
        "last_crawled_at": now,
        "llm_model": settings.groq_model,
        "enriched_at": now,
        "updated_at": now,
    }
    await coll.update_one(
        {"cache_key": key},
        {
            "$set": fields,
            "$addToSet": {
                "input_aliases": entry,
                "name_keys": {"$each": [k for k in (nkey, entry_key, domain_stem) if k]},
            },
            "$setOnInsert": {"created_by": username, "created_at": now, "hit_count": 0, "place_ids": []},
        },
        upsert=True,
    )
    return serialize(await coll.find_one({"cache_key": key}))
