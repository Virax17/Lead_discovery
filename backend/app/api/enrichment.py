import io
import json
import logging
import re

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.auth import get_current_user
from app.db.connection import get_db
from app.services.enrichment_engine import (
    classify_error,
    get_groq_client,
    is_public_url,
    normalize_if_url,
    parse_companies_file,
)
from app.services.export_engine import customer_type_label
from app.services.seller_profiles import DEFAULT_PROFILE, PROFILES, get_profile, valid_profile_id
from app.services.enrichment_store import (
    COLLECTION,
    apply_profile,
    membership_filter,
    correct_match,
    find_enrichment,
    get_or_enrich,
    link_place_id,
    set_override,
)

router = APIRouter(prefix="/enrichment", tags=["enrichment"])
log = logging.getLogger("enrichment")


def _profile_of(value) -> str:
    """The seller profile a request is for (default Tritorc); 400 if unknown."""
    pid = valid_profile_id(value)
    if not pid:
        raise HTTPException(status_code=400, detail="Unknown seller. Choose one of: " + ", ".join(PROFILES))
    return pid


@router.get("/profiles")
async def list_profiles(current_user: str = Depends(get_current_user)):
    """The sellers enrichment can judge leads for (drives the Tritorc | Ozat toggle)."""
    return {"default": DEFAULT_PROFILE, "profiles": [{"id": p.id, "name": p.name} for p in PROFILES.values()]}

MAX_COMPANIES_PER_RUN = 200
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

EXPORT_COLUMNS = [
    "source", "company_name", "website", "address", "phone", "crawl_tier", "crawl_score", "llm_decision",
    "override_decision", "industry", "customer_type", "turnover_class", "annual_turnover",
    "projects_or_recent_activity", "tritorc_relevance",
    "is_competitor", "country", "employee_count", "business_description", "key_operations",
]
LIST_COLUMNS = {"key_operations", "projects_or_recent_activity", "tritorc_relevance"}
EXPORT_WIDTHS = [14, 22, 26, 36, 18, 12, 11, 14, 24, 20, 20, 12, 20, 40, 50, 12, 14, 12, 50, 40]
EXPORT_HEADERS = {
    "llm_decision": "LLM Decision", "crawl_score": "Crawl Score", "crawl_tier": "Crawl Tier",
    "override_decision": "Your Decision", "turnover_class": "Turnover Class (A/B/C)",
    "annual_turnover": "Annual Turnover (as stated)", "tritorc_relevance": "Why It Fits",
}


def _export_value(result: dict, col: str):
    if col == "source":
        return "Enrichment"
    if col == "address":
        return result.get("hq_address") or ", ".join(p for p in (result.get("hq_city"), result.get("country")) if p)
    if col == "phone":
        return "; ".join(result.get("contact_phones") or [])
    if col == "customer_type":
        return customer_type_label(result.get("business_role"), result.get("company_category"))
    if col == "llm_decision":
        return (result.get("llm_decision") or "").capitalize()
    if col == "override_decision":
        d = (result.get("override_decision") or "").capitalize()
        return f"{d}: {result['override_note']}" if d and result.get("override_note") else d
    if col == "is_competitor":
        own = "tritorc" in f"{result.get('website') or ''} {result.get('company_name') or ''}".lower()
        return "Yes" if not own and (result.get("is_competitor") or result.get("business_role") == "competitor_manufacturer") else "No"
    return result.get(col)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.post("/parse-file")
async def parse_file(file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB).")
    try:
        names = parse_companies_file(file.filename or "", content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse {file.filename}: {e}")
    return {"companies": names}


@router.post("/enrich")
async def enrich(request: Request, current_user: str = Depends(get_current_user)):
    """Server-Sent Events stream: start -> (progress, result)* -> complete.
    Known companies are served from `company_enrichments` without crawling or
    calling the LLM unless `force_refresh` is true."""
    body = await request.json()
    names = [n.strip() for n in body.get("companies", []) if isinstance(n, str) and n.strip()]
    # preserve order, drop exact duplicates in the same run
    names = list(dict.fromkeys(names))
    force_refresh = bool(body.get("force_refresh"))
    profile = _profile_of(body.get("profile"))
    if len(names) > MAX_COMPANIES_PER_RUN:
        raise HTTPException(status_code=400, detail=f"Max {MAX_COMPANIES_PER_RUN} companies per run.")

    async def event_stream():
        try:
            client = get_groq_client()
        except RuntimeError as e:
            log.error("enrichment not configured: %s", e)
            yield _sse({"type": "error", "message": classify_error(e)[1]})
            return

        results = []
        total = len(names)
        yield _sse({"type": "start", "total": total})
        for idx, name in enumerate(names, start=1):
            yield _sse({"type": "progress", "index": idx, "total": total, "company": name, "status": "processing"})
            try:
                data = await get_or_enrich(client, name, current_user, force_refresh=force_refresh, profile=profile)
            except Exception as e:
                log.exception("enrichment failed for %r", name)
                code, message = classify_error(e)
                data = {
                    "company_name": name, "website": None, "country": None, "industry": None,
                    "company_category": None, "business_description": None,
                    "key_operations": [], "projects_or_recent_activity": [], "tritorc_relevance": [],
                    "cache_hit": False, "error": True, "error_code": code, "error_message": message,
                    "profile": profile, "profile_name": get_profile(profile).name,
                }
            data["input"] = name
            results.append(data)
            yield _sse({
                "type": "progress", "index": idx, "total": total, "company": name,
                "status": "done", "cache_hit": bool(data.get("cache_hit")),
            })
        yield _sse({"type": "complete", "results": results})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/enrich-single")
async def enrich_single(request: Request, current_user: str = Depends(get_current_user)):
    """Non-streaming enrich of one company (the per-row Enrich button). Served
    from the stored crawl when one exists; links the Places id when given."""
    body = await request.json()
    entry = (body.get("website") or body.get("company_name") or "").strip()
    profile = _profile_of(body.get("profile"))
    if not entry:
        raise HTTPException(status_code=400, detail="Provide website or company_name.")
    try:
        client = get_groq_client()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=classify_error(e)[1])
    try:
        data = await get_or_enrich(client, entry, current_user, force_refresh=bool(body.get("force_refresh")), profile=profile)
    except Exception as e:
        log.exception("enrich-single failed for %r", entry)
        raise HTTPException(status_code=502, detail=classify_error(e)[1])
    if body.get("place_id") and data.get("domain"):
        await link_place_id(data["domain"], body["place_id"])
    data["input"] = (body.get("company_name") or entry).strip()
    return data


@router.post("/correct")
async def correct(request: Request, current_user: str = Depends(get_current_user)):
    """'Wrong company?': the user supplies the right website for a typed name."""
    body = await request.json()
    typed = (body.get("input") or "").strip()
    profile = _profile_of(body.get("profile"))
    site = normalize_if_url((body.get("website") or "").strip())
    if not typed:
        raise HTTPException(status_code=400, detail="Missing the original company name.")
    if not site:
        raise HTTPException(status_code=400, detail="That doesn't look like a website address. Try something like example.com.")
    if not is_public_url(site):
        raise HTTPException(status_code=400, detail="That address isn't a public website, so it can't be used.")
    try:
        client = get_groq_client()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=classify_error(e)[1])
    try:
        data = await correct_match(client, typed, site, body.get("wrong_id"), current_user, profile=profile)
    except Exception as e:
        log.exception("correct failed for %r -> %r", typed, site)
        raise HTTPException(status_code=502, detail=classify_error(e)[1])
    data["input"] = typed
    return data


@router.post("/override")
async def override(request: Request, current_user: str = Depends(get_current_user)):
    """Save (or clear) the user's own accept/review/reject call on a stored company."""
    body = await request.json()
    decision = body.get("decision")
    profile = _profile_of(body.get("profile"))
    if decision not in (None, "", "accept", "review", "reject"):
        raise HTTPException(status_code=400, detail="Decision must be accept, review or reject.")
    doc = await set_override(body.get("id"), decision or None, body.get("note"), current_user, profile=profile)
    if not doc:
        raise HTTPException(status_code=404, detail="That company is no longer stored. Enrich it again first.")
    return doc


@router.get("")
async def list_enrichments(
    q: str | None = None,
    category: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    profile: str | None = None,
    current_user: str = Depends(get_current_user),
):
    """Stored enrichments, newest first (crawled page text omitted), seen as `profile`."""
    profile = _profile_of(profile)
    conds: list[dict] = [membership_filter(profile)]  # each seller's list holds only companies enriched for them
    if category:
        conds.append({"company_category" if profile == DEFAULT_PROFILE else f"profiles.{profile}.company_category": category})
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        conds.append({"$or": [{"company_name": rx}, {"domain": rx}, {"industry": rx}, {"country": rx}]})
    flt: dict = {"$and": conds}
    coll = get_db()[COLLECTION]
    total = await coll.count_documents(flt)
    pipeline = [
        {"$match": flt},
        {"$sort": {"updated_at": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {"$addFields": {"pages_crawled": {"$size": {"$ifNull": ["$crawled_pages", []]}}}},
        {"$project": {"crawled_pages": 0}},
    ]
    items = []
    async for doc in coll.aggregate(pipeline):
        doc["id"] = str(doc.pop("_id"))
        items.append(apply_profile(doc, profile))
    return {"total": total, "items": items}


@router.get("/lookup")
async def lookup(
    domain: str | None = None,
    name: str | None = None,
    place_id: str | None = None,
    include_pages: bool = False,
    current_user: str = Depends(get_current_user),
):
    """Cache-only read by domain, company name or Places place_id. Never crawls."""
    if not (domain or name or place_id):
        raise HTTPException(status_code=400, detail="Provide domain, name or place_id.")
    doc = await find_enrichment(domain=domain, name=name, place_id=place_id, include_pages=include_pages)
    if not doc:
        raise HTTPException(status_code=404, detail="No stored enrichment for this company.")
    return doc


@router.post("/export-xlsx")
async def export_xlsx(request: Request, current_user: str = Depends(get_current_user)):
    body = await request.json()
    results = body.get("results", [])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Company Enrichment"
    ws.append([EXPORT_HEADERS.get(c) or c.replace("_", " ").title() for c in EXPORT_COLUMNS])
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    for result in results:
        row = []
        for col in EXPORT_COLUMNS:
            val = _export_value(result, col)
            if col in LIST_COLUMNS:
                row.append("; ".join(val) if isinstance(val, list) else (val or ""))
            else:
                row.append(val if val is not None else "")
        ws.append(row)
    for i, w in enumerate(EXPORT_WIDTHS, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=company_enrichment.xlsx"},
    )
