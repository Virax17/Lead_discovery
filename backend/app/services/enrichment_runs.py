"""Enrichment sessions: one document per "Enrich" press, so the page can show what was searched, when, and what came out.

A run only stores a light line per company (what was typed, which stored record it resolved to, the verdict at the time).
The full company data stays in `company_enrichments`; opening a run reloads those records, so verdicts, overrides and
retries made later are reflected.
"""
from datetime import datetime, timedelta

from bson import ObjectId
from bson.errors import InvalidId

from app.db.connection import get_db
from app.services.enrichment_store import COLLECTION, apply_profile

RUNS = "enrichment_runs"
STALE_AFTER = timedelta(hours=2)  # a run still "running" this long after it started was cut off (e.g. server restart)


def _oid(value) -> ObjectId | None:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


async def start_run(username: str, profile_id: str, profile_name: str, names: list[str], force_refresh: bool) -> ObjectId:
    res = await get_db()[RUNS].insert_one({
        "created_by": username,
        "profile": profile_id,
        "profile_name": profile_name,
        "started_at": datetime.utcnow(),
        "finished_at": None,
        "status": "running",
        "force_refresh": force_refresh,
        "names": names,
        "total": len(names),
        "items": [],
        "counts": {"accept": 0, "review": 0, "reject": 0, "not_judged": 0, "error": 0, "from_saved": 0},
    })
    return res.inserted_id


def _bucket(data: dict) -> str:
    if data.get("error"):
        return "error"
    decision = data.get("override_decision") or data.get("llm_decision")
    return decision if decision in ("accept", "review", "reject") else "not_judged"


async def add_item(run_id: ObjectId, name: str, data: dict) -> None:
    """Record one finished company on the run (what was typed, the stored record it matched, and the verdict)."""
    bucket = _bucket(data)
    item = {
        "input": name,
        "id": data.get("id"),
        "company_name": data.get("company_name"),
        "domain": data.get("domain"),
        "decision": None if bucket in ("error", "not_judged") else bucket,
        "crawl_tier": data.get("crawl_tier"),
        "cache_hit": bool(data.get("cache_hit")),
        "error": bool(data.get("error")),
        "error_message": data.get("error_message"),
    }
    inc = {f"counts.{bucket}": 1}
    if item["cache_hit"]:
        inc["counts.from_saved"] = 1
    await get_db()[RUNS].update_one({"_id": run_id}, {"$push": {"items": item}, "$inc": inc})


async def finish_run(run_id: ObjectId, status: str) -> None:
    await get_db()[RUNS].update_one(
        {"_id": run_id, "status": "running"}, {"$set": {"status": status, "finished_at": datetime.utcnow()}}
    )


async def _expire_stale() -> None:
    cutoff = datetime.utcnow() - STALE_AFTER
    await get_db()[RUNS].update_many(
        {"status": "running", "started_at": {"$lt": cutoff}}, {"$set": {"status": "stopped", "finished_at": cutoff}}
    )


def _public(doc: dict, include_items: bool = False) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    for k in ("started_at", "finished_at"):
        if isinstance(doc.get(k), datetime):
            doc[k] = doc[k].isoformat() + "Z"  # stored as UTC; the "Z" lets the browser show the viewer's local time
    items = doc.pop("items", [])
    doc["done"] = len(items)
    doc["preview"] = [i.get("company_name") or i.get("input") for i in items[:3]] or doc.get("names", [])[:3]
    if include_items:
        doc["items"] = items
    return doc


async def list_runs(username: str, is_admin: bool, page: int, page_size: int) -> dict:
    await _expire_stale()
    query = {} if is_admin else {"created_by": username}
    coll = get_db()[RUNS]
    total = await coll.count_documents(query)
    cursor = coll.find(query).sort("started_at", -1).skip((page - 1) * page_size).limit(page_size)
    items = [_public(d) async for d in cursor]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


async def get_run(run_id: str, username: str, is_admin: bool) -> dict | None:
    """The run plus its companies, reloaded from the store so they show today's verdicts (as that run's seller saw them)."""
    oid = _oid(run_id)
    if not oid:
        return None
    await _expire_stale()
    run = await get_db()[RUNS].find_one({"_id": oid})
    if not run or not (is_admin or run.get("created_by") == username):
        return None
    out = _public(run, include_items=True)
    ids = {_oid(i["id"]): i["id"] for i in out["items"] if i.get("id") and _oid(i["id"])}
    records: dict[str, dict] = {}
    if ids:
        async for rec in get_db()[COLLECTION].find({"_id": {"$in": list(ids)}}, {"crawled_pages": 0}):
            rec["id"] = str(rec.pop("_id"))
            records[rec["id"]] = rec
    profile = out.get("profile") or "tritorc"
    results = []
    for item in out["items"]:
        rec = records.get(item.get("id"))
        if rec:
            row = apply_profile(rec, profile)
            row["cache_hit"] = item["cache_hit"]
        else:
            # an error row, or a record that has since been deleted: show what was recorded
            row = {
                "company_name": item.get("company_name") or item["input"], "website": None, "domain": item.get("domain"),
                "key_operations": [], "projects_or_recent_activity": [], "tritorc_relevance": [],
                "cache_hit": False, "error": True,
                "error_message": item.get("error_message") or "This company is no longer stored. Run it again to see it.",
                "profile": profile, "profile_name": out.get("profile_name"),
            }
        row["input"] = item["input"]
        results.append(row)
    out["results"] = results
    return out
