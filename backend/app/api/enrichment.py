import io
import json
import re

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.auth import get_current_user
from app.db.connection import get_db
from app.services.enrichment_engine import get_groq_client, parse_companies_file
from app.services.export_engine import customer_type_label
from app.services.enrichment_store import COLLECTION, find_enrichment, get_or_enrich, link_place_id

router = APIRouter(prefix="/enrichment", tags=["enrichment"])

MAX_COMPANIES_PER_RUN = 200
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

EXPORT_COLUMNS = [
    "source", "company_name", "website", "address", "phone", "crawl_tier", "company_category",
    "industry", "customer_type", "projects_or_recent_activity", "tritorc_relevance", "is_competitor",
    "country", "employee_count", "business_description", "key_operations",
]
LIST_COLUMNS = {"key_operations", "projects_or_recent_activity", "tritorc_relevance"}
EXPORT_WIDTHS = [14, 22, 26, 36, 18, 12, 16, 20, 20, 40, 50, 12, 14, 12, 50, 40]


def _export_value(result: dict, col: str):
    if col == "source":
        return "Enrichment"
    if col == "address":
        return result.get("hq_address") or ", ".join(p for p in (result.get("hq_city"), result.get("country")) if p)
    if col == "phone":
        return "; ".join(result.get("contact_phones") or [])
    if col == "customer_type":
        return customer_type_label(result.get("business_role"))
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
    if len(names) > MAX_COMPANIES_PER_RUN:
        raise HTTPException(status_code=400, detail=f"Max {MAX_COMPANIES_PER_RUN} companies per run.")

    async def event_stream():
        try:
            client = get_groq_client()
        except RuntimeError as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        results = []
        total = len(names)
        yield _sse({"type": "start", "total": total})
        for idx, name in enumerate(names, start=1):
            yield _sse({"type": "progress", "index": idx, "total": total, "company": name, "status": "processing"})
            try:
                data = await get_or_enrich(client, name, current_user, force_refresh=force_refresh)
            except Exception as e:
                data = {
                    "company_name": name, "website": None, "country": None, "industry": None,
                    "company_category": None, "business_description": f"Enrichment failed: {e}",
                    "key_operations": [], "projects_or_recent_activity": [], "tritorc_relevance": [],
                    "cache_hit": False, "error": True,
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
    if not entry:
        raise HTTPException(status_code=400, detail="Provide website or company_name.")
    try:
        client = get_groq_client()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        data = await get_or_enrich(client, entry, current_user, force_refresh=bool(body.get("force_refresh")))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Enrichment failed: {e}")
    if body.get("place_id") and data.get("domain"):
        await link_place_id(data["domain"], body["place_id"])
    data["input"] = entry
    return data


@router.get("")
async def list_enrichments(
    q: str | None = None,
    category: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: str = Depends(get_current_user),
):
    """Stored enrichments, newest first (crawled page text omitted)."""
    flt: dict = {}
    if category:
        flt["company_category"] = category
    if q:

        rx = {"$regex": re.escape(q), "$options": "i"}
        flt["$or"] = [{"company_name": rx}, {"domain": rx}, {"industry": rx}, {"country": rx}]
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
        items.append(doc)
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
    ws.append([c.replace("_", " ").title() for c in EXPORT_COLUMNS])
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
