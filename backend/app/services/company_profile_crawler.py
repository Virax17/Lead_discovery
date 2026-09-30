from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from app.config.crawl_concepts import (
    CONCEPT_PHRASES,
    CONCEPT_WEIGHTS,
    NEGATIVE_CONCEPT_PHRASES,
    NEGATIVE_CONCEPT_WEIGHTS,
)
from app.config.industry_terms import industry_type_from_concepts
from app.models.schemas import PlaceDetails
from app.services.crawl_scorer import (
    MAX_TEXT_CHARS_PER_PAGE,
    _classify_business_role,
    _clean_text,
    _detect_language,
    _find_concepts,
    _link_priority,
    _normalize_url,
    _same_site,
    _tier_from_score_and_role,
)
from app.services.error_logger import log_error

# v1: first version of the URL-to-company-profile enrichment crawler. Separate
# from crawl_scorer's CRAWL_VERSION/tritorc-crawl-vN -- that pipeline scores
# Google-Places-sourced leads; this one extracts personalization-ready company
# facts for an external email-generation engine from a bare URL.
CRAWL_VERSION = "company-profile-v1"

MAX_PAGES = 8
NAVIGATION_TIMEOUT_SECONDS = 10

# Maps the 6-way business_role taxonomy (crawl_scorer._classify_business_role)
# to Tritorc's simpler buying-signal taxonomy from the customer-profile memory
# (EPC contractor / end-user plant operator / distributor / irrelevant),
# fixing the old MasterBusiness.customer_type field, which was dead code
# (hardcoded "Unknown", never actually computed).
CUSTOMER_TYPE_FROM_ROLE = {
    "end_user_operator": "end_user_operator",
    "industrial_service_contractor": "service_contractor",
    "epc_contractor": "epc_contractor",
    "supplier_distributor": "distributor",
    "competitor_manufacturer": "irrelevant",
    "generic_local_service": "irrelevant",
    "unknown": "unknown",
}

NEWS_PAGE_TERMS = ("news", "press", "media", "blog", "updates", "insights", "articles")
NEWS_PAGE_PRIORITY_BONUS = 60
ABOUT_PAGE_TERMS = ("about", "about-us", "who-we-are", "company", "profile")
MAX_RECENT_ACTIVITY_ITEMS = 5

EMAIL_HREF_RE = re.compile(r"^mailto:([^?]+)", re.IGNORECASE)
PHONE_HREF_RE = re.compile(r"^tel:([^?]+)", re.IGNORECASE)

SOCIAL_DOMAINS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
}

# _detect_language() only needs a PlaceDetails for its source_query_language/
# country_code fallback (used when lingua can't detect anything at all) --
# neither applies to a bare-URL enrichment call, so an empty stub is enough
# rather than duplicating the whole language-detection function.
_LANGUAGE_DETECT_STUB = PlaceDetails(name="", address="")


@dataclass
class ProfilePage:
    url: str
    title: str = ""
    text: str = ""
    meta_description: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    social_links: dict[str, str] = field(default_factory=dict)
    headlines: list[dict] = field(default_factory=list)


def _profile_link_priority(url: str) -> int:
    score = _link_priority(url)
    lower = url.lower()
    if any(term in lower for term in NEWS_PAGE_TERMS):
        score += NEWS_PAGE_PRIORITY_BONUS
    return score


# "Share this article" widget links (facebook.com/sharer/sharer.php,
# twitter.com/intent/tweet, linkedin.com/shareArticle, etc.) match the same
# social domains as a company's own profile page but point at Hytorc's own
# blog post, not their profile -- confirmed live via a real crawl of a blog
# page. Filtered on path rather than domain since the share-widget path
# differs per platform.
SHARE_WIDGET_PATH_MARKERS = ("sharer", "share", "intent", "dialog")


def _social_platform(absolute_href: str) -> str | None:
    parsed = urlparse(absolute_href)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    platform = SOCIAL_DOMAINS.get(netloc)
    if not platform:
        return None
    path_lower = parsed.path.lower()
    if any(marker in path_lower for marker in SHARE_WIDGET_PATH_MARKERS):
        return None
    return platform


def _extract_page(soup, url: str) -> ProfilePage:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    meta_description = _clean_text(meta_tag.get("content", "")) if meta_tag and meta_tag.get("content") else ""
    text = _clean_text(soup.get_text(" ", strip=True))[:MAX_TEXT_CHARS_PER_PAGE]

    emails: list[str] = []
    phones: list[str] = []
    social_links: dict[str, str] = {}
    headlines: list[dict] = []
    is_news_page = any(term in url.lower() for term in NEWS_PAGE_TERMS) or any(term in title.lower() for term in NEWS_PAGE_TERMS)

    for link in soup.find_all("a", href=True):
        href = (link.get("href") or "").strip()
        if not href:
            continue

        email_match = EMAIL_HREF_RE.match(href)
        if email_match:
            email = email_match.group(1).strip().lower()
            if email and email not in emails:
                emails.append(email)
            continue

        phone_match = PHONE_HREF_RE.match(href)
        if phone_match:
            phone = phone_match.group(1).strip()
            if phone and phone not in phones:
                phones.append(phone)
            continue

        absolute_href = urljoin(url, href)
        platform = _social_platform(absolute_href)
        if platform and platform not in social_links:
            social_links[platform] = absolute_href
            continue

        if is_news_page and len(headlines) < MAX_RECENT_ACTIVITY_ITEMS:
            headline_text = _clean_text(link.get_text(" ", strip=True))
            if 20 <= len(headline_text) <= 200 and absolute_href.startswith(("http://", "https://")):
                headlines.append({"title": headline_text, "url": absolute_href, "snippet": None, "published_at": None})

    return ProfilePage(
        url=url,
        title=title,
        text=text,
        meta_description=meta_description,
        emails=emails,
        phones=phones,
        social_links=social_links,
        headlines=headlines,
    )


def _build_profile(canonical_url: str | None, pages: list[ProfilePage], status: str, error: str | None = None) -> dict:
    combined_text = "\n".join(page.text for page in pages)
    company_name: str | None = None
    meta_description: str | None = None
    about_summary: str | None = None
    contact_emails: list[str] = []
    contact_phones: list[str] = []
    social_links: dict[str, str] = {}
    recent_activity: list[dict] = []

    for page in pages:
        if page.title and not company_name:
            company_name = page.title
        if page.meta_description and not meta_description:
            meta_description = page.meta_description
        for email in page.emails:
            if email not in contact_emails:
                contact_emails.append(email)
        for phone in page.phones:
            if phone not in contact_phones:
                contact_phones.append(phone)
        for platform, href in page.social_links.items():
            social_links.setdefault(platform, href)
        for item in page.headlines:
            if len(recent_activity) < MAX_RECENT_ACTIVITY_ITEMS:
                recent_activity.append(item)

        if not about_summary:
            url_lower = page.url.lower()
            title_lower = page.title.lower()
            if any(term in url_lower or term in title_lower for term in ABOUT_PAGE_TERMS):
                about_summary = page.text[:600] or None

    if not about_summary and pages:
        about_summary = pages[0].text[:600] or None

    detected_language, _confidence = _detect_language(combined_text, _LANGUAGE_DETECT_STUB)
    scoring_language = detected_language if detected_language in CONCEPT_PHRASES else "en"
    positive_concepts, _positive_phrases = _find_concepts(combined_text, CONCEPT_PHRASES, scoring_language)
    negative_concepts, _negative_phrases = _find_concepts(combined_text, NEGATIVE_CONCEPT_PHRASES, scoring_language)
    business_role, business_role_score, _signals, _negative_signals, business_role_reason = _classify_business_role(
        combined_text, scoring_language, positive_concepts, negative_concepts,
    )

    positive_score = sum(CONCEPT_WEIGHTS[c] for c in positive_concepts)
    negative_score = sum(NEGATIVE_CONCEPT_WEIGHTS[c] for c in negative_concepts)
    score = max(0, min(100, positive_score + business_role_score - negative_score))
    relevance_tier = _tier_from_score_and_role(score, positive_score, negative_score, business_role, positive_concepts)

    return {
        "canonical_url": canonical_url,
        "company_name": company_name,
        "meta_description": meta_description,
        "about_summary": about_summary,
        "matched_domain_concepts": positive_concepts,
        "business_role": business_role,
        "business_role_reason": business_role_reason,
        "customer_type": CUSTOMER_TYPE_FROM_ROLE.get(business_role, "unknown"),
        "industry_type": industry_type_from_concepts(positive_concepts),
        "relevance_tier": relevance_tier,
        "contact_emails": contact_emails,
        "contact_phones": contact_phones,
        "social_links": social_links,
        "detected_language": detected_language if pages else None,
        "recent_activity": recent_activity,
        "crawl_status": status,
        "crawl_error": error,
        "pages_crawled": len(pages),
        "crawl_version": CRAWL_VERSION,
    }


async def _httpx_fallback_crawl(root_url: str, root_netloc: str, max_pages: int) -> list[ProfilePage]:
    """Same fallback role as crawl_scorer._httpx_fallback_crawl -- confirmed
    live that Crawlee's Rust-based HTTP client (impit) can fail a TLS
    handshake ("PeerMisbehaved: SelectedUnusableCipherSuiteForVersion")
    against a real site (hi-force.com) that a plain httpx/system-TLS request
    to the same URL handles fine, so this must exist here too or those sites
    are wrongly reported unreachable."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []

    headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadDiscoveryBot/1.0)"}
    timeout = httpx.Timeout(10.0, connect=5.0)
    pages: list[ProfilePage] = []
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
            page = _extract_page(soup, str(response.url))
            if page.text:
                pages.append(page)

            candidates: list[str] = []
            for link in soup.find_all("a", href=True):
                href = link.get("href")
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                next_url = urldefrag(urljoin(str(response.url), href))[0]
                parsed = urlparse(next_url)
                if parsed.scheme not in {"http", "https"} or not _same_site(next_url, root_netloc):
                    continue
                if any(next_url.lower().endswith(ext) for ext in (".jpg", ".png", ".gif", ".zip", ".mp4", ".css", ".js", ".pdf")):
                    continue
                if next_url not in seen:
                    candidates.append(next_url)
            queue.extend(sorted(candidates, key=_profile_link_priority, reverse=True)[: max_pages - len(pages)])

    return pages


async def crawl_company_profile(url: str, max_pages: int = MAX_PAGES) -> dict:
    """Best-effort URL -> company-profile crawl. Never raises -- errors are
    reflected in the returned `crawl_status`/`crawl_error` fields."""
    root_url = _normalize_url(url)
    if not root_url:
        return _build_profile(None, [], status="invalid_url", error="URL could not be parsed.")

    root_netloc = urlparse(root_url).netloc
    pages: list[ProfilePage] = []
    queued: set[str] = {root_url}
    os.environ.setdefault(
        "CRAWLEE_STORAGE_DIR",
        os.path.join(tempfile.gettempdir(), "lead_discovery_crawlee_storage"),
    )

    try:
        from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
    except Exception as exc:
        await log_error(search_id=None, stage="company_profile_crawler_import", place_id=None, error_message=str(exc))
        return _build_profile(root_url, [], status="failed", error="Crawlee is not installed or could not be imported.")

    crawler = BeautifulSoupCrawler(
        max_requests_per_crawl=max_pages,
        max_crawl_depth=2,
        max_request_retries=1,
        max_session_rotations=0,
        retry_on_blocked=False,
        navigation_timeout=timedelta(seconds=NAVIGATION_TIMEOUT_SECONDS),
        request_handler_timeout=timedelta(seconds=20),
        configure_logging=False,
    )

    @crawler.router.default_handler
    async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
        page = _extract_page(context.soup, context.request.url)
        if page.text:
            pages.append(page)

        candidates: list[str] = []
        for link in context.soup.find_all("a", href=True):
            href = link.get("href")
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            next_url = urldefrag(urljoin(context.request.url, href))[0]
            parsed = urlparse(next_url)
            if parsed.scheme not in {"http", "https"} or not _same_site(next_url, root_netloc):
                continue
            if any(next_url.lower().endswith(ext) for ext in (".jpg", ".png", ".gif", ".zip", ".mp4", ".css", ".js", ".pdf")):
                continue
            if next_url not in queued:
                candidates.append(next_url)

        for next_url in sorted(candidates, key=_profile_link_priority, reverse=True):
            if len(queued) >= max_pages:
                break
            queued.add(next_url)
            await crawler.add_requests([next_url])

    try:
        await crawler.run([root_url])
    except Exception as exc:
        await log_error(search_id=None, stage="company_profile_crawler", place_id=None, error_message=f"{root_url}: {str(exc)}")

    if not pages:
        pages = await _httpx_fallback_crawl(root_url, root_netloc, max_pages)

    if not pages:
        return _build_profile(root_url, [], status="unreachable", error="Website could not be crawled or returned no usable content.")

    return _build_profile(root_url, pages[:max_pages], status="ok")
