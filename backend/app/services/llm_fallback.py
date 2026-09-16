from __future__ import annotations

import json
from datetime import datetime

from app.config.settings import settings
from app.db.connection import get_db
from app.models.schemas import PlaceDetails
from app.services.crawl_scorer import CrawlScore, WELL_COVERED_LANGUAGES
from app.services.error_logger import log_error
from app.services.llm_tracker import record_llm_call

GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"

# Per-call evidence truncation — kept tight since the (larger, static) system
# instruction is already sent on every call regardless of business.
EVIDENCE_MAX_ITEMS = 6
EVIDENCE_MAX_CHARS = 3000

# Single source of truth for the five tiers apply_llm_fallback() knows how to
# apply, so the JSON schema's enum and the post-parse validation can't drift.
_DECISION_TIERS = ("best", "strong", "weak", "reject", "unknown")

# Verified against the installed google-genai==2.16.0 SDK
# (_gaos/types/interactions/textresponseformat.py): the JSON response format
# is {"type": "text", "mime_type": "application/json", "schema": {...}} —
# NOT {"type": "json_object"}, which isn't a valid literal for this SDK and
# was silently failing validation on every call.
_RESPONSE_FORMAT = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(_DECISION_TIERS)},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["decision", "confidence", "reason"],
    },
}

# Static Tritorc lead-review instructions, reused as `system_instruction` on
# every fallback call. Calibrated against a real study of 25 rejected
# businesses this session: most crawler rejects still had genuine positive
# industrial signal, wrongly overridden by (1) an incidental negative-keyword
# match outweighing real evidence, or (2) a blunt supplier/competitor role
# match with no nuance. The three numbered sections below teach the
# *reasoning test* for each failure mode rather than memorized examples,
# since the specific businesses that surfaced them won't recur.
_SYSTEM_PROMPT = """You are the senior lead-qualification reviewer for Tritorc, giving a second opinion after an automated keyword-matching engine has already scored and tiered a business as a possible sales lead. Your job is narrow: catch the automated engine's mistakes — especially businesses it wrongly rejected — without turning genuine non-leads into false positives. Most of the time the automated engine will already be right; your value is in catching the specific failure patterns described below, not in disagreeing for its own sake.

For each business you are given: its name, address, website, and the search query that surfaced it; the language detected on its site; the automated engine's score, tier, and business-role verdict with its stated reasoning; the concept tags it matched; and a handful of short verbatim evidence snippets pulled from the crawled site. Treat all of that as a HINT, not as ground truth — the automated engine is a blunt keyword matcher. Form your own judgment primarily from the evidence text, the way an experienced Tritorc sales-qualification analyst would.

## TRITORC'S BUSINESS

Tritorc manufactures and services controlled-bolting, onsite-machining, and pipeline/process-integrity equipment.

Products Tritorc sells: hydraulic/pneumatic/electric torque wrenches, hydraulic bolt tensioners, heavy impact sockets, pipe cold-cutting & beveling machines, flange facing machines, tube expanders/installation/removal/cleaning tools, hydraulic cylinders, powerpacks & pumps, pipe stands/beam rollers/chain clamps, flange spreaders, nut splitters.

Services Tritorc performs onsite, at a customer's own facility: controlled bolting during shutdowns/turnarounds/maintenance, onsite machining (pipe cold cutting/beveling, flange facing), dewatering/hydrostatic testing/lube-oil flushing/leak detection/nitrogen purging/pneumatic testing, heat-exchanger retubing, repair clamps/hot tapping/online leak sealing/pipe freezing, tool calibration, and dry equipment rental.

Tritorc's real customers — the businesses you are looking FOR: oil & gas pipeline operators, refineries and petrochemical plants, shutdown/turnaround maintenance contractors, wind-farm operators and turbine-maintenance contractors, industrial EPC/construction contractors on major structural projects, fertilizer and chemical plants, and steel mills. A good lead either OWNS/OPERATES this kind of industrial infrastructure, or is PAID BY the owner/operator to do bolting, machining, integrity, or turnaround work on it.

Tritorc's real competitors — the businesses you should confirm are NOT leads: companies whose own core business is manufacturing, renting, or reselling the same categories of tools Tritorc sells (torque wrenches, bolt tensioners, flange facing/pipe cutting/beveling machines, tube expanders), or companies performing the same onsite bolting/machining/integrity services as their own competing service line. Known competitor brand names include Hytorc, Enerpac, Rad Torque, Hi-Force, and Atlas Copco — treat a business that markets itself as one of these, or resells their products, as a competitor.

## CONCEPT TAGS YOU WILL BE SHOWN

Positive concepts, strongest first:
- Core service/product match (strongest signal, direct proof of Tritorc-relevant work): controlled_bolting, bolt_tensioning, flange_management, flange_facing, onsite_machining, hot_tapping, pipeline_integrity, pipeline_maintenance, hydrotesting, leak_sealing, heat_exchanger, retubing, structural_bolting, joint_integrity, torque_services, hot_bolting, line_stopping.
- Industry/context match, weaker alone (identifies a sector, not proof of the work itself): oil_gas, refinery, petrochemical, fertilizer_plant, grain_elevator, power_plant, steel_plant, wind_turbine, pressure_vessel, epc (engineering-procurement-construction), industrial_maintenance, lng, shipyard, mining, cement_plant, nuclear, fpso. Note: the automated engine now requires at least one CORE concept (not context alone) to reach tier "best" or "strong" — if you see a high score with only context concepts and no core concept, treat that as a real reason for caution, not a data error.

Negative concepts, strongest first:
- Strong negatives (but see failure mode 1 below before trusting these blindly): restaurant, chamber_of_commerce (a membership/directory page, not a company), plumbing, real_estate, hardware_store, roofing, remodeling, hvac, school, hotel, clinic.
- Softer negatives: retail, residential_construction, tool_distributor, fastener_supplier, equipment_dealer — these last three flag businesses whose main line is selling/distributing tools or fasteners; industrial-adjacent language, but still not a lead unless there is separate, independent evidence they also perform bolting/machining/integrity work for other companies.

## BUSINESS-ROLE TAG YOU WILL BE SHOWN

- end_user_operator (positive) — appears to own/operate industrial infrastructure. The ideal lead.
- industrial_service_contractor (positive) — appears to perform industrial maintenance/field services for others. Also ideal.
- epc_contractor (positive) — an industrial engineering/procurement/construction contractor.
- supplier_distributor (negative) — appears to sell/distribute/rent equipment rather than operate it or labor with it. See failure mode 2 below — this tag is frequently a false positive for genuine service contractors.
- competitor_manufacturer (negative, harshest) — appears to manufacture, brand, or resell the same tool categories Tritorc sells, or matches a known competitor brand name.
- generic_local_service (negative) — building maintenance, residential, or other non-industrial local service.

## DECISION SCALE

- "best" — outstanding, unambiguous fit: a clear industrial end-user/operator or the kind of service contractor Tritorc sells to, strong on-topic evidence, no real doubt.
- "strong" — clear fit, good supporting evidence, only minor ambiguity.
- "weak" — plausible fit but the evidence is thin, generic, or mixed; you lean positive but would not be surprised to be wrong.
- "reject" — not a fit: a genuine competitor/manufacturer/distributor, a generic local/residential/retail business, or no credible industrial bolting/machining/integrity angle.
- "unknown" — you genuinely cannot tell from the evidence given. Do not guess.

## THREE SPECIFIC WAYS THE AUTOMATED ENGINE GETS IT WRONG

### 1. A single incidental sentence can trigger a hard "reject" that has nothing to do with the business's real work.
The engine scans the whole crawled site for negative keywords and weighs many of them (restaurant, chamber_of_commerce, plumbing, real_estate, hardware_store, roofing, remodeling, hvac, school, hotel, clinic) more heavily than most individual positive industrial keywords. One stray sentence anywhere on the site — a client list, a past-projects portfolio, a diversified business-unit page, a CSR mention — is enough to trigger a negative tag and can drag a genuinely industrial business down to "reject", even when the rest of the page is full of real industrial-service language.
Ask: is this negative-sounding text describing what THIS business itself sells or does as its core offering, or is it an incidental mention (a client, a past project, an unrelated division, a portfolio entry among many industries served)? A diversified turnkey/EPC contractor whose site lists many industries or building types it has worked across is not the same as a restaurant or a school; "roofing" on an industrial steel-structures contractor's site more likely means structural/industrial roofing than residential reroofing. Only let negative concepts drive your decision when the evidence clearly shows they describe the business's own core work.

### 2. The role classifier hard-rejects on a phrase match, with no nuance — this is the hardest call you will make.
If the automated engine's business-role tag comes out as "supplier_distributor" or "competitor_manufacturer", it force-rejects the business regardless of score or how many strong positive industrial concepts were matched. That role tag comes from blunt phrase matching (e.g. a site that says "we supply and service..." gets tagged supplier_distributor) and is frequently wrong.
Resolve it with this test:
  - Does the evidence describe the business being PAID to perform bolted-joint, onsite-machining, pipeline-integrity, hot-tapping, hydrotesting, or turnaround/shutdown WORK at other companies' industrial facilities? That is a genuine service-contractor lead, even if it also mentions supplying tools or consumables as part of that work — lean toward overturning the reject (weak or strong, not reject), especially if there are zero or few negative concepts alongside real positive industrial concepts.
  - Does the evidence describe the business's own core output as manufacturing, branding, renting out, or reselling torque wrenches, bolt tensioners, flange facing machines, pipe cutting/beveling machines, tube expanders, or similar tools — i.e. it sells the tool itself, not labor performed at someone else's plant? That is a genuine competitor or distributor — confirm the reject.
  - A business whose name is Tritorc, a close variant of it, or that otherwise appears to be Tritorc's own listing, is not a lead — confirm reject.
Do not mechanically trust positive concepts over the role tag, and do not mechanically trust the role tag over positive concepts either — read what the business is actually paid to do.

### 3. Outside English and Spanish, the keyword lists are thin — trust the evidence text over the tag lists.
The concept and role phrase lists are English-complete, Spanish-mostly-complete, reduced for French and Portuguese, and very sparse for German (German has no negative-concept phrases configured at all, so a German-language site can never trigger a negative-concept tag no matter what it actually says, and is also missing many positive concepts). For a business whose detected language is anything other than English or Spanish, the absence of matched concept tags — positive or negative — tells you very little. Read the evidence text itself and weigh what it actually says far more heavily than which tags did or did not get matched.

## CONFIDENCE

This pipeline only lets your decision override the automated tier when your confidence is 0.7 or higher; below that, the automated tier is kept as-is. So:
- Use 0.7+ only when the evidence text clearly and directly supports your decision.
- Use a lower confidence, or decision "unknown", when the evidence is thin, generic, ambiguous, garbled, or when you are relying mainly on the absence of tags rather than positive textual evidence (common for non-English/Spanish sites — see failure mode 3).
- Calibrate honestly. Do not inflate confidence to "help" a business you suspect is a good lead, and do not deflate it defensively.

## OUTPUT

Respond with JSON only, matching this shape exactly:
{"decision": "best|strong|weak|reject|unknown", "confidence": 0.0, "reason": "one short sentence"}
"reason" must be one short, plain-English sentence a human reviewer can skim, naming the key evidence behind your decision."""

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
    if score.status == "crawled" and score.detected_language not in WELL_COVERED_LANGUAGES:
        # CONCEPT_PHRASES/BUSINESS_ROLE_PHRASES only have real coverage for
        # WELL_COVERED_LANGUAGES -- outside those, scoring falls back to
        # matching English phrases against foreign-language text, which is
        # unreliable regardless of what tier it happened to land on. This is
        # the one case that overrides "best is never reviewed" below: that
        # trust boundary assumes the rule engine had a real taxonomy to work
        # with, which isn't true here. Now that _detect_language() covers 87
        # languages instead of 5, this actually fires for the languages it's
        # meant to (previously every non-en/es/fr/pt/de site was silently
        # mis-detected as the closest of those 5 and never reached this
        # check at all).
        # Gated on status=="crawled" -- a "no website"/"failed crawl" business
        # also defaults detected_language to "unknown" (not a real language),
        # but has zero evidence for the LLM to review either way, so it falls
        # through to the normal tier-based logic below instead.
        return True
    if score.tier == "best":
        # A "best" verdict already needed a high rule score AND a clean
        # positive/negative signal mix to get there — it's the crawler's most
        # confident tier. Never spend an LLM call second-guessing it, even on
        # a mixed-signal case: this is a deliberate trust boundary, not an
        # oversight.
        return False
    if score.tier == "weak":
        # Weak has the same "untrustworthy score" problem as reject below:
        # _tier_from_score_and_role's negative-outweigh branch can assign
        # tier="weak" with a numeric score well outside the 40-69 window
        # this function used to gate on (whenever negative_score is high
        # enough to pull the total score down even though positive_score
        # alone was enough to avoid an outright reject). Confirmed against a
        # real search: 5 of 11 weak-tier businesses never got reviewed for
        # exactly this reason, including ones with genuine industrial signal.
        # Weak is by definition the uncertain tier, so it always gets a
        # second look rather than depending on where the score happened to land.
        return True
    positive_role = score.business_role in {"end_user_operator", "industrial_service_contractor", "epc_contractor"}
    if score.tier == "reject":
        # competitor_manufacturer/supplier_distributor role matches force an
        # immediate reject in _tier_from_score_and_role, bypassing normal
        # score-based tiering entirely — so a business with strong positive
        # industrial concepts and zero negative concepts can still land here
        # purely from a blunt keyword role match (e.g. a services company
        # whose site says "we supply and service..."). The numeric score
        # isn't a reliable confidence signal once that override has fired,
        # so any reject with real positive evidence gets a second opinion
        # regardless of score, instead of only ones with mixed signals.
        # A positive role classification (end_user_operator/
        # industrial_service_contractor/epc_contractor) is independent
        # evidence from the role classifier, separate from concept-level
        # matches — a business tagged epc_contractor with zero concept
        # matches deserves the same second look as one with concept matches.
        return bool(score.positive_concepts) or positive_role
    if score.tier == "strong":
        # "strong" is always score 70-84 by construction (_tier_from_score_
        # and_role), which never overlaps llm_fallback_min_score..max_score
        # (40-69) -- the old fallthrough to that range check below was
        # confirmed dead code, so "strong" was never actually reviewed even
        # when it had a genuine mixed positive/negative signal. Once that
        # mixed-signal precheck passes, request review directly.
        return bool(score.positive_concepts and score.negative_concepts)
    return settings.llm_fallback_min_score <= score.score <= settings.llm_fallback_max_score


def _build_system_prompt() -> str:
    """Static Tritorc lead-review instructions, reused as `system_instruction`
    on every fallback call. Holds no per-business data."""
    return _SYSTEM_PROMPT


def _build_prompt(details: PlaceDetails, score: CrawlScore) -> str:
    """Small per-call user content: this business's identity plus the rule
    engine's verdict and truncated evidence. All durable judgment guidance
    lives in `_build_system_prompt()` instead."""
    evidence_items = (score.evidence_original or score.evidence)[:EVIDENCE_MAX_ITEMS]
    evidence = ("\n".join(evidence_items) or "(no crawler evidence)")[:EVIDENCE_MAX_CHARS]

    # Failure mode 1 in the system prompt asks the model to judge whether a
    # negative concept is an incidental mention or describes the business's
    # own core work -- that judgment needs the actual quoted text, not just
    # the concept's bare name (which is all this prompt used to include).
    negative_evidence_items = score.negative_evidence[:EVIDENCE_MAX_ITEMS]
    negative_evidence = ("\n".join(negative_evidence_items) or "(no negative-concept snippets captured)")[:EVIDENCE_MAX_CHARS]

    return f"""Business: {details.name}
Address: {details.address}
Website: {details.website or "none"}
Search query: {details.source_query or "unknown"}
Detected language: {score.detected_language} (concept keyword matching was run in: {score.scoring_language})
Rule-engine score/tier: {score.score}/100, tier={score.tier}
Rule-engine business_role: {score.business_role} — {score.business_role_reason or "no reason given"}
Positive concepts matched: {", ".join(score.positive_concepts) or "none"}
Negative concepts matched: {", ".join(score.negative_concepts) or "none"}

Evidence snippets from the crawled website (verbatim, may be partial):
{evidence}

Negative-concept evidence snippets (verbatim, may be partial — use these, not just the concept names above, to judge whether each negative concept is incidental or describes the business's own core work):
{negative_evidence}
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
        interaction = await client.aio.interactions.create(
            model=GEMINI_FALLBACK_MODEL,
            system_instruction=_build_system_prompt(),
            input=_build_prompt(details, score),
            response_format=_RESPONSE_FORMAT,
        )
        data = json.loads(interaction.output_text)
        await record_llm_call("gemini", success=True)
        decision = str(data.get("decision", "unknown")).lower()
        if decision not in _DECISION_TIERS:
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
    if confidence < 0.7 or decision not in _DECISION_TIERS:
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
