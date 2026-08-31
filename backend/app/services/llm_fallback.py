from __future__ import annotations

import json
from datetime import datetime

from app.config.settings import settings
from app.db.connection import get_db
from app.models.schemas import PlaceDetails
from app.services.crawl_scorer import CrawlScore
from app.services.error_logger import log_error
from app.services.llm_tracker import record_llm_call

GEMINI_FALLBACK_MODEL = "gemini-2.5-flash-lite"

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if not settings.gemini_api_key:
        return None
    if _gemini_client is None:
        from google import genai

        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


def _current_month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")


async def _monthly_llm_calls() -> int:
    db = get_db()
    doc = await db.llm_usage_monthly.find_one({"_id": _current_month_str()}) or {}
    providers = doc.get("providers", {})
    return sum(int(provider.get("calls", 0)) for provider in providers.values())


def _should_request_llm(score: CrawlScore) -> bool:
    if not settings.llm_fallback_enabled:
        return False
    if score.tier in {"best", "strong", "reject"} and not (score.positive_concepts and score.negative_concepts):
        return False
    return settings.llm_fallback_min_score <= score.score <= settings.llm_fallback_max_score


def _build_prompt(details: PlaceDetails, score: CrawlScore) -> str:
    evidence = "\n".join((score.evidence_original or score.evidence)[:6]) or "(no crawler evidence)"
    return f"""You are a strict lead-quality fallback reviewer for Tritorc.

Tritorc sells and services controlled bolting, onsite machining, flange work, hot tapping, pipeline/process integrity, hydrotesting, leak sealing, and heat-exchanger retubing.

Decide if this business is likely a real buyer/user of those products/services. Prefer clients such as refineries, petrochemical/chemical/fertilizer plants, pipeline operators, power/steel/wind operators, industrial EPC firms, and shutdown/turnaround maintenance contractors. Reject retail, residential construction, restaurants, schools, real estate, generic suppliers/distributors, and competitors that mainly sell the same tool categories.

Return JSON only:
{{"decision":"best|strong|weak|reject|unknown","confidence":0.0,"reason":"one short sentence"}}

Business: {details.name}
Address: {details.address}
Website: {details.website or "none"}
Search query: {details.source_query or "unknown"}
Detected language: {score.detected_language}
Rule score/tier: {score.score}/{score.tier}
Positive concepts: {", ".join(score.positive_concepts) or "none"}
Negative concepts: {", ".join(score.negative_concepts) or "none"}
Evidence:
{evidence[:3000]}
"""


async def llm_fallback_payload(
    details: PlaceDetails,
    score: CrawlScore,
    calls_used_in_search: int = 0,
) -> dict:
    if not settings.llm_fallback_enabled:
        return {"llm_fallback_status": "not_requested"}

    if calls_used_in_search >= settings.llm_fallback_max_calls_per_search:
        return {"llm_fallback_status": "skipped_search_cap"}

    if not _should_request_llm(score):
        return {"llm_fallback_status": "not_requested"}

    if await _monthly_llm_calls() >= settings.llm_fallback_max_calls_per_month:
        return {"llm_fallback_status": "skipped_monthly_cap"}

    client = _get_gemini_client()
    if client is None:
        return {"llm_fallback_status": "unavailable", "llm_fallback_provider": "gemini"}

    try:
        interaction = client.interactions.create(
            model=GEMINI_FALLBACK_MODEL,
            input=_build_prompt(details, score),
            response_format={"type": "json_object"},
        )
        data = json.loads(interaction.output_text)
        await record_llm_call("gemini", success=True)
        decision = str(data.get("decision", "unknown")).lower()
        if decision not in {"best", "strong", "weak", "reject", "unknown"}:
            decision = "unknown"
        confidence = float(data.get("confidence", 0.0) or 0.0)
        return {
            "llm_fallback_status": "completed",
            "llm_fallback_provider": "gemini",
            "llm_fallback_model": GEMINI_FALLBACK_MODEL,
            "llm_fallback_decision": decision,
            "llm_fallback_confidence": max(0.0, min(1.0, confidence)),
            "llm_fallback_reason": str(data.get("reason", ""))[:500],
            "llm_fallback_checked_at": datetime.utcnow(),
        }
    except Exception as exc:
        message = str(exc)
        await record_llm_call("gemini", success=False, error_message=message)
        await log_error(search_id=None, stage="llm_fallback", place_id=None, error_message=message)
        return {
            "llm_fallback_status": "failed",
            "llm_fallback_provider": "gemini",
            "llm_fallback_model": GEMINI_FALLBACK_MODEL,
            "llm_fallback_reason": message[:500],
            "llm_fallback_checked_at": datetime.utcnow(),
        }


def apply_llm_fallback(score: CrawlScore, payload: dict) -> CrawlScore:
    if payload.get("llm_fallback_status") != "completed":
        return score

    decision = payload.get("llm_fallback_decision")
    confidence = float(payload.get("llm_fallback_confidence") or 0.0)
    if confidence < 0.7 or decision not in {"best", "strong", "weak", "reject", "unknown"}:
        return score

    score.tier = decision
    if decision == "best":
        score.score = max(score.score, 85)
    elif decision == "strong":
        score.score = max(70, min(score.score, 84))
    elif decision == "weak":
        score.score = max(40, min(score.score, 69))
    elif decision == "reject":
        score.score = min(score.score, 20)

    reason = payload.get("llm_fallback_reason")
    if reason:
        score.reason = f"{score.reason} LLM fallback: {reason}"
    return score
