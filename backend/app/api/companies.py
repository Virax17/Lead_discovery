from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.models.schemas import CompanyEnrichRequest
from app.services.company_cache import get_company_profile, lookup_company_profile

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("/enrich")
async def enrich_company(payload: CompanyEnrichRequest, current_user: str = Depends(get_current_user)):
    """Get-or-crawl: returns the cached profile if fresh, otherwise crawls
    the URL, stores the result, and returns it. `cache_hit` tells you which."""
    profile = await get_company_profile(payload.url)
    if profile.get("domain") is None:
        raise HTTPException(status_code=400, detail=profile.get("crawl_error") or "Invalid URL.")
    return profile


@router.get("/{domain}")
async def get_company(domain: str, current_user: str = Depends(get_current_user)):
    """Pure cache/DB read -- never triggers a crawl."""
    profile = await lookup_company_profile(domain)
    if not profile:
        raise HTTPException(status_code=404, detail="No cached profile for this domain.")
    return profile
