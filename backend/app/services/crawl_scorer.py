from __future__ import annotations

import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from app.config.crawl_concepts import (
    BUSINESS_ROLE_PHRASES,
    BUSINESS_ROLE_WEIGHTS,
    CONCEPT_PHRASES,
    CONCEPT_WEIGHTS,
    CORE_CONCEPTS,
    NEGATIVE_CONCEPT_PHRASES,
    NEGATIVE_CONCEPT_WEIGHTS,
)
from app.models.schemas import PlaceDetails
from app.services.error_logger import log_error

# v4: fixed a bug where the search keyword itself (details.source_query) was
# fed into concept/role matching, trivially "matching" any concept whose
# phrase list overlapped the keyword (e.g. every "shutdown contractor" result
# got free credit for the shutdown_turnaround concept) regardless of actual
# site content. Bumped so every previously-scored business gets re-crawled
# and re-scored under the corrected logic instead of trusting stale scores.
# v5: removed the generic "chemical_plant" concept (too broad/inaccurate as a
# Tritorc target on its own), added "grain_elevator" (fertilizer/agri
# processing infrastructure — the machinery those plants actually need
# serviced, not mobile farm-equipment repair) and "structural_bolting"
# (bridges/heavy civil steel erection — high-strength structural bolting,
# distinct from residential/civil "construction").
# v6: fixed llm_fallback._should_request_llm() missing most weak-tier and
# role-positive-but-concept-empty reject-tier businesses for LLM review
# (confirmed against a real search: 81% of results never got reviewed).
# v7: added a core-vs-context concept split (best/strong now require >=1 core
# concept, not context concepts alone -- confirmed live that a context-only
# combo could otherwise reach score=100/tier=best with zero real bolting
# evidence); expanded the taxonomy (joint integrity, torque services, hot
# bolting, line stopping, LNG, shipyard, mining, cement, nuclear, FPSO);
# fixed "epc" matching inside unrelated Spanish/Portuguese words via bare
# substring search; tightened "shutdown"/"turnaround" and the
# supplier_distributor role phrases to reduce false positives; raised the
# negative-outweigh reject threshold so a single incidental negative word
# can't override strong positive evidence on its own. Bumped so every
# previously-scored business gets re-evaluated under the corrected logic.
# v8: expanded _detect_language() from 5 to all 87 languages lingua
# supports -- previously a site in any language other than en/es/fr/pt/de
# was force-classified as whichever of those 5 looked closest, since the
# detector was never given any other option. Businesses in a language
# without real CONCEPT_PHRASES coverage now force an LLM review instead of
# trusting a rule-engine score computed from the wrong language's phrase
# list (see WELL_COVERED_LANGUAGES, used in llm_fallback._should_request_llm).
CRAWL_VERSION = "tritorc-crawl-v8"
SCORING_VERSION = "role-concept-score-v1"

# Languages with real phrase-list coverage in CONCEPT_PHRASES/
# NEGATIVE_CONCEPT_PHRASES/BUSINESS_ROLE_PHRASES. Derived from the taxonomy
# itself rather than hardcoded so it can't silently drift out of sync as
# languages are added.
WELL_COVERED_LANGUAGES = frozenset(CONCEPT_PHRASES.keys())
MAX_PAGES_PER_SITE = 10
MAX_TEXT_CHARS_PER_PAGE = 12000
MAX_EVIDENCE_ITEMS = 8
CRAWLER_NAVIGATION_TIMEOUT_SECONDS = 10

PREFERRED_URL_TERMS = (
    "industries", "industry", "oil", "gas", "refinery",
    "petrochemical", "chemical", "pipeline", "turnaround", "shutdown",
    "maintenance", "machining", "bolting", "flange", "heat-exchanger",
    "heat_exchanger", "hydrotest", "hot-tap", "hot_tap", "about",
    "integrity", "tensioning", "joint", "calibration", "rental",
)

# A dedicated "services"/"capabilities" page is the single highest-value page
# to crawl -- it's where a business states what it actually does, unlike a
# marketing-focused homepage or a history-focused "about" page. This bonus is
# large enough that a URL matching one of these terms is crawled ahead of
# everything else the page budget would otherwise spend on, rather than just
# nudged up alongside a dozen equally-weighted generic industry words.
# Includes es/pt/de variants -- confirmed live that "servicios" (a real
# Spanish services-page URL) doesn't contain the English substring "service",
# so an English-only list would silently miss it for every non-English site,
# which is most of this pipeline's actual crawl targets. Spanish "servicio(s)"
# and Portuguese "serviço(s)" differ by one letter and a diacritic, so a
# single term doesn't cover both; URL slugs also commonly drop diacritics
# (serviço -> "servico"), so both the accented and ASCII-transliterated
# Portuguese spellings are included.
SERVICE_PAGE_TERMS = (
    "services", "service", "capabilities", "what-we-do", "what_we_do",
    "servicio",  # es (servicio, servicios)
    "serviço",  # pt, accented URL slug (serviço, serviços)
    "servico",  # pt, ASCII-transliterated URL slug
    "leistung",  # de (Dienstleistungen, Leistungen)
    "prestation",  # fr (prestations de service)
)
SERVICE_PAGE_PRIORITY_BONUS = 100

NEGATIVE_GOOGLE_TYPES = {
    "school",
    "primary_school",
    "secondary_school",
    "university",
    "restaurant",
    "cafe",
    "food",
    "lodging",
    "real_estate_agency",
    "plumber",
    "roofing_contractor",
    "electrician",
    "car_repair",
    "store",
    "shopping_mall",
    "local_government_office",
}


@dataclass
class CrawledPage:
    url: str
    title: str = ""
    text: str = ""


@dataclass
class CrawlScore:
    status: str
    score: int
    tier: str
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    evidence_original: list[str] = field(default_factory=list)
    evidence_translated: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)
    negative_evidence: list[str] = field(default_factory=list)
    reason: str = ""
    pages_checked: int = 0
    detected_language: str = "unknown"
    language_confidence: float = 0.0
    scoring_language: str = "en"
    matched_concepts: list[str] = field(default_factory=list)
    positive_concepts: list[str] = field(default_factory=list)
    negative_concepts: list[str] = field(default_factory=list)
    business_role: str = "unknown"
    business_role_score: int = 0
    business_role_signals: list[str] = field(default_factory=list)
    business_role_negative_signals: list[str] = field(default_factory=list)
    business_role_reason: str = ""
    scoring_version: str = SCORING_VERSION


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        parsed = urlparse(f"https://{url.strip()}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urldefrag(parsed.geturl())[0]


def _same_site(url: str, root_netloc: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    root = root_netloc.lower()
    return netloc == root or netloc == f"www.{root}" or root == f"www.{netloc}"


def _link_priority(url: str) -> int:
    lower = url.lower()
    score = 0
    for term in PREFERRED_URL_TERMS:
        if term in lower:
            score += 10
    if any(term in lower for term in SERVICE_PAGE_TERMS):
        score += SERVICE_PAGE_PRIORITY_BONUS
    score -= min(lower.count("/") * 2, 20)
    return score


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_signals(text: str, signals: dict[str, int]) -> list[str]:
    lower = text.lower()
    found = []
    for phrase in signals:
        if phrase in lower:
            found.append(phrase)
    return found


def _detect_language(text: str, details: PlaceDetails) -> tuple[str, float]:
    sample = _clean_text(text)[:5000]
    if sample:
        try:
            from lingua import LanguageDetectorBuilder

            # Previously restricted to 5 languages (en/es/fr/pt/de) -- the
            # only ones with real CONCEPT_PHRASES/BUSINESS_ROLE_PHRASES
            # coverage. That meant a site in any of the other ~190 countries
            # this pipeline searches (Arabic, Italian, Chinese, Dutch,
            # Turkish, etc.) could never be correctly detected at all: lingua
            # would force-classify it as whichever of those 5 looked closest,
            # silently feeding the wrong language's phrase list downstream.
            # lingua supports 87 languages (confirmed) at negligible extra
            # cost (detector build is near-instant; detection is ~0.5s/page,
            # fine for a background crawl) -- detecting the TRUE language is
            # what lets _should_request_llm() force an LLM review for
            # languages the rule engine has no real taxonomy for, instead of
            # silently trusting a meaningless score.
            detector = LanguageDetectorBuilder.from_all_languages().build()
            confidence_values = list(detector.compute_language_confidence_values(sample))
            if confidence_values:
                best = confidence_values[0]
                iso_code = getattr(best.language, "iso_code_639_1", None)
                if iso_code:
                    return iso_code.name.lower(), float(best.value)
        except Exception:
            pass

    if details.source_query_language:
        return details.source_query_language, 0.35
    if details.country_code in {"ES", "MX", "AR", "CL", "CO", "PE"}:
        return "es", 0.25
    if details.country_code in {"FR", "BE"}:
        return "fr", 0.25
    if details.country_code in {"BR", "PT"}:
        return "pt", 0.25
    if details.country_code in {"DE", "AT"}:
        return "de", 0.25
    return "en", 0.25


def _language_candidates(language: str) -> list[str]:
    candidates = ["en"]
    if language != "en" and language in CONCEPT_PHRASES:
        candidates.insert(0, language)
    return candidates


def _find_concepts(text: str, phrase_map: dict[str, dict[str, list[str]]], language: str) -> tuple[list[str], dict[str, str]]:
    lower = text.lower()
    concepts: list[str] = []
    evidence_phrases: dict[str, str] = {}
    for candidate_language in _language_candidates(language):
        for concept, phrases in phrase_map.get(candidate_language, {}).items():
            for phrase in phrases:
                if phrase.lower() in lower:
                    if concept not in concepts:
                        concepts.append(concept)
                        evidence_phrases[concept] = phrase
                    break
    return concepts, evidence_phrases


def _classify_business_role(
    text: str,
    language: str,
    positive_concepts: list[str],
    negative_concepts: list[str],
) -> tuple[str, int, list[str], list[str], str]:
    roles, role_phrases = _find_concepts(text, BUSINESS_ROLE_PHRASES, language)
    positive_roles = [role for role in roles if BUSINESS_ROLE_WEIGHTS.get(role, 0) > 0]
    negative_roles = [role for role in roles if BUSINESS_ROLE_WEIGHTS.get(role, 0) < 0]
    score = sum(BUSINESS_ROLE_WEIGHTS.get(role, 0) for role in roles)
    role_signals = [role_phrases[role] for role in positive_roles]
    role_negative_signals = [role_phrases[role] for role in negative_roles]

    if "competitor_manufacturer" in roles:
        return (
            "competitor_manufacturer",
            score,
            role_signals,
            role_negative_signals,
            "Business appears to sell, rent, or manufacture the same tool/service category as Tritorc.",
        )
    if "supplier_distributor" in roles and not positive_roles:
        return (
            "supplier_distributor",
            score,
            role_signals,
            role_negative_signals,
            "Business appears to be a supplier/distributor rather than an end-user or service contractor.",
        )
    if "generic_local_service" in roles and not positive_roles:
        return (
            "generic_local_service",
            score,
            role_signals,
            role_negative_signals,
            "Business appears to provide generic local/building services, not Tritorc-fit industrial work.",
        )
    if "end_user_operator" in roles:
        return ("end_user_operator", score, role_signals, role_negative_signals, "Business appears to operate industrial assets.")
    if "industrial_service_contractor" in roles:
        return (
            "industrial_service_contractor",
            score,
            role_signals,
            role_negative_signals,
            "Business appears to perform industrial maintenance or field services.",
        )
    if "epc_contractor" in roles:
        return ("epc_contractor", score, role_signals, role_negative_signals, "Business appears to be an industrial EPC contractor.")
    if "supplier_distributor" in roles and positive_roles:
        return (
            "supplier_distributor",
            score,
            role_signals,
            role_negative_signals,
            "Supplier/distributor evidence is present without enough operator/contractor evidence.",
        )

    if positive_concepts and not negative_concepts:
        return (
            "unknown",
            score,
            role_signals,
            role_negative_signals,
            "Industrial concepts found, but buyer/operator/contractor role is not clear.",
        )
    return ("unknown", score, role_signals, role_negative_signals, "No clear business role evidence found.")


def _tier_from_score_and_role(score: int, positive_score: int, negative_score: int, role: str, positive_concepts: list[str]) -> str:
    if role in {"competitor_manufacturer", "generic_local_service"}:
        return "reject"
    if role == "supplier_distributor":
        return "reject"
    # Raised from 28: most negative weights are 24-35, so a single incidental
    # negative mention (a client-list entry, an unrelated past project) could
    # force a reject on its own even with strong positive evidence. No single
    # weight reaches 45, so this now requires at least two distinct negative
    # concepts -- matching "outweigh", not "one word".
    if negative_score >= 45 and positive_score < 40:
        return "reject"
    # Best/strong require at least one CORE concept (direct evidence of
    # bolting/machining/integrity work), not context concepts alone --
    # confirmed live that oil_gas + refinery + industrial_maintenance +
    # power_plant + a role phrase alone could otherwise reach score=100.
    has_core = any(concept in CORE_CONCEPTS for concept in positive_concepts)
    if role == "unknown":
        if has_core and score >= 85:
            return "best"
        if has_core and score >= 70:
            return "strong"
        if score >= 70:
            return "weak"
        return "weak" if positive_score >= 35 else "reject"
    if score >= 85:
        return "best" if has_core else "strong"
    if score >= 70:
        return "strong" if has_core else "weak"
    if score >= 40:
        return "weak"
    return "weak" if positive_score >= 30 else "reject"


def _evidence_for_phrase(pages: list[CrawledPage], concept: str, phrase: str) -> tuple[str, str] | None:
    pattern = re.compile(rf".{{0,90}}{re.escape(phrase)}.{{0,120}}", re.IGNORECASE)
    for page in pages:
        match = pattern.search(page.text)
        if match:
            return f"{concept}: {_clean_text(match.group(0))[:220]}", page.url
    return None


async def _httpx_fallback_crawl(root_url: str, root_netloc: str, max_pages: int) -> list[CrawledPage]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadDiscoveryBot/1.0)"}
    timeout = httpx.Timeout(10.0, connect=5.0)
    pages: list[CrawledPage] = []
    seen: set[str] = set()
    queue: list[str] = [root_url]

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception:
                continue

            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                continue

            soup = BeautifulSoup(response.text, "lxml")
            for tag in soup(["script", "style", "noscript", "svg"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            text = _clean_text(soup.get_text(" ", strip=True))[:MAX_TEXT_CHARS_PER_PAGE]
            if text:
                pages.append(CrawledPage(url=str(response.url), title=title, text=text))

            candidates = []
            for link in soup.find_all("a", href=True):
                href = link.get("href")
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                next_url = urldefrag(urljoin(str(response.url), href))[0]
                parsed = urlparse(next_url)
                if parsed.scheme not in {"http", "https"} or not _same_site(next_url, root_netloc):
                    continue
                if any(next_url.lower().endswith(ext) for ext in (".jpg", ".png", ".gif", ".zip", ".mp4", ".css", ".js")):
                    continue
                if next_url not in seen:
                    candidates.append(next_url)
            queue.extend(sorted(candidates, key=_link_priority, reverse=True)[: max_pages - len(pages)])

    return pages


def score_crawl(details: PlaceDetails, pages: list[CrawledPage]) -> CrawlScore:
    google_types = set(details.google_types or [])
    google_primary = details.google_primary_type
    negative_types = sorted((google_types | {google_primary or ""}) & NEGATIVE_GOOGLE_TYPES)
    if negative_types:
        label = ", ".join(negative_types)
        return CrawlScore(
            status="skipped",
            score=0,
            tier="reject",
            negative_signals=[f"google_type:{item}" for item in negative_types],
            negative_concepts=[f"google_type:{item}" for item in negative_types],
            reason=f"Google category indicates non-industrial business: {label}.",
            pages_checked=0,
        )

    if not details.website:
        return CrawlScore(
            status="skipped",
            score=0,
            tier="unknown",
            reason="No website available to verify industrial fit.",
            pages_checked=0,
        )

    if not pages:
        return CrawlScore(
            status="failed",
            score=0,
            tier="unknown",
            reason="Website could not be crawled or no usable page text was found.",
            pages_checked=0,
        )

    # `details.source_query` is the literal search keyword used to find this
    # business (e.g. "shutdown contractor in Alberta, Canada") — it must NOT
    # feed concept/role matching, since every business found by a keyword
    # search would then trivially "match" that keyword's own concept purely
    # because it was searched for, regardless of what the site actually says
    # (confirmed: this was silently crediting every "shutdown contractor"
    # result with the shutdown_turnaround concept, since that concept's own
    # phrase list contains "shutdown" — explaining crawl_evidence coming back
    # empty for concept matches that never actually appeared on the site).
    # It's kept only for language detection below, where a bad guess merely
    # falls back to English rather than fabricating scoring evidence.
    language_hint = "\n".join([details.name, details.address, details.source_query or ""])
    combined = "\n".join([details.name, details.address] + [p.text for p in pages])
    detected_language, language_confidence = _detect_language(language_hint + "\n" + combined, details)
    scoring_language = detected_language if detected_language in CONCEPT_PHRASES else "en"
    positive_concepts, positive_phrases = _find_concepts(combined, CONCEPT_PHRASES, scoring_language)
    negative_concepts, negative_phrases = _find_concepts(combined, NEGATIVE_CONCEPT_PHRASES, scoring_language)
    business_role, business_role_score, role_signals, role_negative_signals, role_reason = _classify_business_role(
        combined,
        scoring_language,
        positive_concepts,
        negative_concepts,
    )

    positive_score = sum(CONCEPT_WEIGHTS[item] for item in positive_concepts)
    negative_score = sum(NEGATIVE_CONCEPT_WEIGHTS[item] for item in negative_concepts)
    score = max(0, min(100, positive_score + business_role_score - negative_score))

    if positive_concepts:
        concept_counts = Counter(positive_concepts)
        score += min(10, max(0, len(positive_concepts) - 2) * 3)
        if concept_counts.get("pipeline_integrity") or concept_counts.get("controlled_bolting"):
            score += 8
        score = min(100, score)

    tier = _tier_from_score_and_role(score, positive_score, negative_score, business_role, positive_concepts)

    evidence = []
    evidence_urls = []
    for concept in positive_concepts[:MAX_EVIDENCE_ITEMS]:
        item = _evidence_for_phrase(pages, concept, positive_phrases[concept])
        if item:
            snippet, url = item
            evidence.append(snippet)
            evidence_urls.append(url)

    # Quoted, not just named -- the LLM prompt's failure-mode-1 guidance asks
    # it to judge whether a negative mention is incidental or describes the
    # business's own core work, which requires the actual text, not just the
    # concept's bare name.
    negative_evidence = []
    for concept in negative_concepts[:MAX_EVIDENCE_ITEMS]:
        item = _evidence_for_phrase(pages, concept, negative_phrases[concept])
        if item:
            snippet, _url = item
            negative_evidence.append(snippet)

    if business_role in {"competitor_manufacturer", "supplier_distributor", "generic_local_service"}:
        reason = f"{role_reason} Industrial concepts: {', '.join(positive_concepts[:5]) or 'none'}."
    elif tier == "reject" and negative_concepts:
        reason = f"Negative fit concepts outweigh industrial evidence: {', '.join(negative_concepts[:4])}."
    elif positive_concepts:
        reason = f"{role_reason} Found industrial concepts: {', '.join(positive_concepts[:5])}."
    else:
        reason = "No meaningful Tritorc-fit industrial evidence found in crawled pages."

    return CrawlScore(
        status="crawled",
        score=score,
        tier=tier,
        positive_signals=[positive_phrases[concept] for concept in positive_concepts],
        negative_signals=[negative_phrases[concept] for concept in negative_concepts],
        evidence=evidence,
        evidence_original=evidence,
        evidence_urls=evidence_urls,
        negative_evidence=negative_evidence,
        reason=reason,
        pages_checked=len(pages),
        detected_language=detected_language,
        language_confidence=language_confidence,
        scoring_language=scoring_language,
        matched_concepts=positive_concepts + negative_concepts,
        positive_concepts=positive_concepts,
        negative_concepts=negative_concepts,
        business_role=business_role,
        business_role_score=business_role_score,
        business_role_signals=role_signals,
        business_role_negative_signals=role_negative_signals,
        business_role_reason=role_reason,
    )


async def crawl_business_website(details: PlaceDetails, max_pages: int = MAX_PAGES_PER_SITE) -> CrawlScore:
    root_url = _normalize_url(details.website)
    if not root_url:
        return score_crawl(details, [])

    root_netloc = urlparse(root_url).netloc
    crawled: list[CrawledPage] = []
    queued: set[str] = {root_url}
    os.environ.setdefault(
        "CRAWLEE_STORAGE_DIR",
        os.path.join(tempfile.gettempdir(), "lead_discovery_crawlee_storage"),
    )

    try:
        from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
    except Exception as exc:
        await log_error(search_id=None, stage="crawler_import", place_id=None, error_message=str(exc))
        return CrawlScore(
            status="failed",
            score=0,
            tier="unknown",
            reason="Crawlee is not installed or could not be imported.",
            pages_checked=0,
        )

    crawler = BeautifulSoupCrawler(
        max_requests_per_crawl=max_pages,
        max_crawl_depth=2,
        max_request_retries=1,
        max_session_rotations=0,
        retry_on_blocked=False,
        navigation_timeout=timedelta(seconds=CRAWLER_NAVIGATION_TIMEOUT_SECONDS),
        request_handler_timeout=timedelta(seconds=20),
        configure_logging=False,
    )

    @crawler.router.default_handler
    async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
        soup = context.soup
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = _clean_text(soup.get_text(" ", strip=True))[:MAX_TEXT_CHARS_PER_PAGE]
        if text:
            crawled.append(CrawledPage(url=context.request.url, title=title, text=text))

        candidates: list[str] = []
        for link in soup.find_all("a", href=True):
            href = link.get("href")
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            next_url = urldefrag(urljoin(context.request.url, href))[0]
            parsed = urlparse(next_url)
            if parsed.scheme not in {"http", "https"} or not _same_site(next_url, root_netloc):
                continue
            if any(next_url.lower().endswith(ext) for ext in (".jpg", ".png", ".gif", ".zip", ".mp4", ".css", ".js")):
                continue
            if next_url not in queued:
                candidates.append(next_url)

        for next_url in sorted(candidates, key=_link_priority, reverse=True):
            if len(queued) >= max_pages:
                break
            queued.add(next_url)
            await crawler.add_requests([next_url])

    try:
        await crawler.run([root_url])
    except Exception as exc:
        await log_error(search_id=None, stage="crawler", place_id=None, error_message=f"{root_url}: {str(exc)}")

    if not crawled:
        crawled = await _httpx_fallback_crawl(root_url, root_netloc, max_pages)

    result = score_crawl(details, crawled[:max_pages])
    if result.status == "crawled":
        result.reason = f"{result.reason} Crawled {result.pages_checked} page(s)."
    return result


def crawl_score_payload(score: CrawlScore) -> dict:
    return {
        "crawl_status": score.status,
        "crawl_score": score.score,
        "crawl_tier": score.tier,
        "crawl_pages_checked": score.pages_checked,
        "crawl_positive_signals": score.positive_signals,
        "crawl_negative_signals": score.negative_signals,
        "crawl_evidence": score.evidence,
        "crawl_evidence_original": score.evidence_original or score.evidence,
        "crawl_evidence_translated": score.evidence_translated,
        "crawl_evidence_urls": score.evidence_urls,
        "crawl_negative_evidence": score.negative_evidence,
        "crawl_reason": score.reason,
        "crawl_checked_at": datetime.utcnow(),
        "crawl_version": CRAWL_VERSION,
        "detected_language": score.detected_language,
        "language_confidence": score.language_confidence,
        "scoring_language": score.scoring_language,
        "matched_concepts": score.matched_concepts,
        "positive_concepts": score.positive_concepts,
        "negative_concepts": score.negative_concepts,
        "business_role": score.business_role,
        "business_role_score": score.business_role_score,
        "business_role_signals": score.business_role_signals,
        "business_role_negative_signals": score.business_role_negative_signals,
        "business_role_reason": score.business_role_reason,
        "scoring_version": score.scoring_version,
        "translation_status": "not_requested",
        "llm_fallback_status": "not_requested",
    }
