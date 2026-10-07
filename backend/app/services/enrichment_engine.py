"""Ported from tritorc-ai/Company-Enrichment-Platform (server.py).

Synchronous crawl + Groq extraction for one company input (name, URL or
email). Callers run `enrich_company` in an executor. Persistence/caching lives
in enrichment_store.py.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import os
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import openpyxl
import requests
import urllib3
from bs4 import BeautifulSoup
from groq import APIStatusError, Groq

from app.config.settings import settings
from app.models.schemas import PlaceDetails
from app.services.company_profile_crawler import (
    CUSTOMER_TYPE_FROM_ROLE,
    EMAIL_HREF_RE,
    PHONE_HREF_RE,
    _social_platform,
)
from app.services.crawl_scorer import CrawledPage, score_crawl

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CompanyEnrichmentBot/1.0"

URL_LIKE_RE = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/.*)?$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[^\s@]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)$", re.IGNORECASE)

# consumer/webmail domains: an email at one of these tells us nothing about
# the sender's employer, so it must not be treated as a company website.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "aol.com", "gmx.com", "protonmail.com", "mail.com",
    "yandex.com", "qq.com", "163.com", "126.com",
}

_OFFERINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "tritorc_offerings.json")
with open(_OFFERINGS_PATH, encoding="utf-8") as f:
    TRITORC_OFFERINGS = json.load(f)

# category-level summary (not per-product) to keep the grounding payload small
# enough to stay well under Groq's per-minute token limits across back-to-back calls.
TRITORC_BLOCK = json.dumps(
    {
        "products": [
            {
                "name": c["category"],
                "examples": c.get("example_products", [])[:3],
                "uses": c.get("applications", [])[:5],
            }
            for c in TRITORC_OFFERINGS["product_categories"]
        ],
        "services": [s["name"] if isinstance(s, dict) else s for s in TRITORC_OFFERINGS["services"]],
    },
    ensure_ascii=False,
    separators=(",", ":"),
)

EMPTY_RESULT = {
    "company_name": None, "website": None, "country": None, "hq_city": None, "hq_address": None, "industry": None,
    "company_category": None, "is_competitor": False, "employee_count": None,
    "llm_decision": None, "llm_decision_reason": None,
    "turnover_class": None, "turnover_basis": None, "annual_turnover": None, "business_description": None,
    "key_operations": [], "projects_or_recent_activity": [], "tritorc_relevance": [],
}


def get_groq_client():
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set in backend/.env.")
    return Groq(api_key=settings.groq_api_key)


class UnsafeURLError(Exception):
    """The address is not a public website (private network, loopback, cloud metadata...)."""


def is_public_url(url: str) -> bool:
    """True only for http(s) URLs whose host resolves exclusively to public
    internet addresses. Stops the crawler from being pointed at the server's
    own network or the EC2 metadata service."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
        addrs = {i[4][0].split("%")[0] for i in infos}
        if not addrs:
            return False
        for a in addrs:
            ip = ipaddress.ip_address(a)
            if getattr(ip, "ipv4_mapped", None):
                ip = ip.ipv4_mapped
            if not ip.is_global:
                return False
        return True
    except (socket.gaierror, ValueError, UnicodeError, OSError):
        return False


_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _guarded_request(method: str, url: str, *, session=None, max_redirects: int = 5, **kwargs):
    """requests.get/head that re-checks every redirect hop, so a public site
    cannot bounce the crawler onto an internal address."""
    sender = session or requests
    for _ in range(max_redirects + 1):
        if not is_public_url(url):
            raise UnsafeURLError(url)
        resp = getattr(sender, method)(url, allow_redirects=False, **kwargs)
        location = resp.headers.get("location")
        if resp.status_code in _REDIRECT_CODES and location:
            url = urljoin(url, location)
            continue
        return resp
    raise requests.exceptions.TooManyRedirects(f"too many redirects for {url}")


def _probe_url(url: str, method: str = "head"):
    """Reachability check only (no data exchanged). Some real corporate sites
    ship an incomplete/misconfigured TLS certificate chain (verified case:
    bilfinger.com fails standard cert validation while resolving and serving
    fine over plain TLS) — retry once without strict verification rather than
    silently treating the whole company as having 'no website'."""
    name = "head" if method == "head" else "get"
    try:
        return _guarded_request(name, url, headers={"User-Agent": UA}, timeout=10)
    except requests.exceptions.SSLError:
        try:
            return _guarded_request(name, url, headers={"User-Agent": UA}, timeout=10, verify=False)
        except Exception:
            return None
    except Exception:
        return None



SOCIAL_AND_AGGREGATOR_HOSTS = {
    "linkedin.com", "www.linkedin.com", "en.wikipedia.org", "wikipedia.org",
    "x.com", "twitter.com", "facebook.com", "www.facebook.com",
    "instagram.com", "youtube.com", "www.youtube.com",
    "finance.yahoo.com", "www.crunchbase.com", "crunchbase.com",
    "www.bloomberg.com", "bloomberg.com", "www.glassdoor.com", "glassdoor.com",
    "indeed.com", "www.indeed.com",
}


def search_serper(company_name: str):
    """Live Google search via serper.dev. Returns the first organic result
    whose domain isn't a social/aggregator site, or None if unavailable/no match."""
    api_key = settings.serper_api_key
    if not api_key:
        return None
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f"{company_name} official website", "num": 8},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        for item in data.get("organic", []):
            link = item.get("link")
            if not link:
                continue
            host = urlparse(link).netloc.lower()
            if host in SOCIAL_AND_AGGREGATOR_HOSTS or "jobs." in host:
                continue
            parsed = urlparse(link)
            return f"{parsed.scheme}://{parsed.netloc}"
        return None
    except Exception:
        return None


def find_official_site(client, company_name: str):
    """Resolve a likely official website. Primary path is a live Google search
    via serper.dev (when SERPER_API_KEY is set), taking the first non-social,
    non-aggregator organic result. Falls back to asking the LLM for its
    best-known domain and verifying that guess actually loads before trusting
    it, if no search key is configured or the search finds nothing usable.
    (Live scraping of DuckDuckGo/Bing HTML was tried first and found
    unreliable — both returned bot-detection junk/decoy results inconsistently
    for automated queries.)
    """
    searched = search_serper(company_name)
    if searched:
        r = _probe_url(searched, method="get")
        if r is not None and r.status_code < 400:
            return str(r.url).rstrip("/")

    try:
        completion = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": "You return only valid JSON."},
                {"role": "user", "content": (
                    f'What is the primary official corporate website domain for the company "{company_name}"? '
                    'Respond with a JSON object: {"domain": "example.com"} using only the bare domain '
                    '(no scheme, no path). If you are not confident you know the real domain, '
                    'respond with {"domain": null}.'
                )},
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
            reasoning_effort="low",
        )
        raw = completion.choices[0].message.content
        data = json.loads(raw)
        domain = data.get("domain")
        if not domain:
            return None
        domain = domain.strip().lower()
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
        if not URL_LIKE_RE.match(domain):
            return None
        # try the bare domain, then www.-prefixed (some sites 404 on bare apex
        # and only serve from www., e.g. bilfinger.com vs www.bilfinger.com)
        candidates = [f"https://{domain}"]
        if not domain.startswith("www."):
            candidates.append(f"https://www.{domain}")

        for candidate in candidates:
            r = _probe_url(candidate)
            if r is not None and r.status_code >= 400:
                r = _probe_url(candidate, method="get")
            if r is not None and r.status_code < 400:
                return str(r.url).rstrip("/")
        return None
    except Exception:
        return None


# Ordered by value: contact/about pages carry HQ address + contact details,
# the rest carry what the company actually does (fit evidence).
CANDIDATE_PATH_KEYWORDS = [
    "contact", "about", "company", "who-we-are", "locations", "offices",
    "services", "solutions", "industries", "capabilities", "products",
    "projects", "portfolio", "news", "media", "press",
]
MAX_PAGES = 8
# Groq's on-demand tier caps a request at 8,000 tokens/min including max_tokens;
# the Tritorc catalog alone is ~10k chars, so site text must stay modest.
# On a 413 the text budget is stepped down and the call retried.
PROMPT_TEXT_BUDGET = 8000
PROMPT_TEXT_BUDGET_STEPS = (8000, 5000, 3000)
PAGE_TEXT_CHARS = 6000
EMAIL_TEXT_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


# Pages that never describe what the company does (and often bury the crawl in
# near-duplicate forms), plus the max number of contact-type pages to keep.
SKIP_PATH_TERMS = ("investor", "career", "job", "faq", "privacy", "cookie", "legal", "imprint", "login", "form")
CONTACT_PATH_TERMS = ("contact", "locations", "offices")
MAX_CONTACT_PAGES = 2


def _path_priority(path: str) -> int:
    path = path.lower()
    if any(t in path for t in SKIP_PATH_TERMS):
        return 0
    for i, kw in enumerate(CANDIDATE_PATH_KEYWORDS):
        if kw in path:
            return len(CANDIDATE_PATH_KEYWORDS) - i
    return 0


def _extract_contacts(soup, page_url: str, text: str, contacts: dict) -> None:
    """Emails/phones/social profile links from one page into `contacts`."""
    emails, phones, socials = contacts["emails"], contacts["phones"], contacts["social_links"]
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        m = EMAIL_HREF_RE.match(href)
        if m:
            e = m.group(1).strip().lower()
            if e and e not in emails:
                emails.append(e)
            continue
        m = PHONE_HREF_RE.match(href)
        if m:
            ph = m.group(1).strip()
            if ph and ph not in phones:
                phones.append(ph)
            continue
        platform = _social_platform(urljoin(page_url, href))
        if platform and platform not in socials:
            socials[platform] = urljoin(page_url, href)
    for e in EMAIL_TEXT_RE.findall(text):
        e = e.lower().rstrip(".")
        if not e.endswith(_IMAGE_SUFFIXES) and e not in emails:
            emails.append(e)
    del emails[10:]
    del phones[6:]


def crawl_company_site(base_url: str, max_pages: int = MAX_PAGES, timeout: int = 15):
    """Light crawl: homepage + the most valuable internal pages (contact/about
    first). Returns (pages, error, contacts) where pages are
    [{"url","title","text"}] and contacts is {emails, phones, social_links}."""
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    visited = set()
    pages_text = []
    contacts = {"emails": [], "phones": [], "social_links": {}}

    def clean(soup):
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\n{2,}", "\n", soup.get_text("\n", strip=True))

    def session_get(url):
        # some real sites ship an incomplete TLS cert chain; retry once
        # without strict verification rather than dropping the whole crawl.
        try:
            return _guarded_request("get", url, session=session, timeout=timeout)
        except requests.exceptions.SSLError:
            return _guarded_request("get", url, session=session, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            # verified case: some hosts time out on a direct HTTPS connection
            # but work fine when reached via their own http->https redirect
            # (e.g. sceptre.com.my). Retry over plain http as a last resort.
            if url.startswith("https://"):
                return _guarded_request("get", "http://" + url[len("https://"):], session=session, timeout=timeout)
            raise

    def add_page(url, soup):
        # contacts must be read before clean() strips tags from the soup
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = clean(soup)
        _extract_contacts(soup, url, text, contacts)
        pages_text.append({"url": url, "title": title, "text": text[:PAGE_TEXT_CHARS]})
        visited.add(url.rstrip("/"))

    try:
        r = session_get(base_url)
    except UnsafeURLError:
        return [], "blocked: that address is not a public website", contacts
    except Exception as e:
        return [], f"error fetching homepage: {e}", contacts

    if r.status_code != 200:
        return [], f"homepage returned status {r.status_code}", contacts

    home = BeautifulSoup(r.text, "lxml")
    base_netloc = urlparse(base_url).netloc
    candidates = {}
    for a in home.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base_netloc:
            continue
        pri = _path_priority(parsed.path)
        if pri:
            norm = full.split("#")[0].rstrip("/")
            candidates[norm] = max(candidates.get(norm, 0), pri)
    add_page(base_url, home)

    ranked = sorted((u for u in candidates if u not in visited), key=lambda u: -candidates[u])
    chosen, contact_pages = [], 0
    for url in ranked:
        is_contact = any(t in urlparse(url).path.lower() for t in CONTACT_PATH_TERMS)
        if is_contact:
            if contact_pages >= MAX_CONTACT_PAGES:
                continue
            contact_pages += 1
        chosen.append(url)
        if len(chosen) >= max_pages - 1:
            break
    for url in chosen:
        try:
            rr = session_get(url)
            time.sleep(0.5)
            if rr.status_code == 200:
                add_page(url, BeautifulSoup(rr.text, "lxml"))
        except Exception:
            continue

    return pages_text, None, contacts


ENRICHMENT_SCHEMA_HINT = """{
  "company_name": "",
  "website": "",
  "country": "",
  "hq_city": "",
  "hq_address": "",
  "industry": "",
  "company_category": "",
  "is_competitor": false,
  "employee_count": null,
  "llm_decision": "",
  "llm_decision_reason": "",
  "turnover_class": "",
  "turnover_basis": "",
  "annual_turnover": "",
  "business_description": "",
  "key_operations": [],
  "projects_or_recent_activity": [],
  "tritorc_relevance": []
}"""

# A/B/C size class by annual turnover (US$ equivalent). Change here to re-band; bump
# ENRICHMENT_LLM_VERSION in enrichment_store.py so stored companies are re-judged.
TURNOVER_BANDS = (
    "Bands: A = US$100 million or more a year (large enterprise), "
    "B = US$10 million to under US$100 million (mid-size), C = under US$10 million (small)."
)

COMPETITOR_BRANDS = (
    "HYTORC, Enerpac, Hydratight, Atlas Copco, Hi-Force, RAD Torque, ITH, Riverhawk, "
    "TorcUP, Norbar, SPX FLOW Power Team, Wren Hydraulic, Equalizer International"
)

def scorer_hint_block(fit: dict | None) -> str:
    """The rule-based scorer's verdict, shown to the model as a hint only
    (Lead Discovery's LLM reviewer gets the same context)."""
    if not fit or not fit.get("crawl_tier"):
        return ""
    pos = ", ".join(fit.get("positive_concepts") or []) or "none"
    neg = ", ".join(fit.get("negative_concepts") or []) or "none"
    return (
        "\nAUTOMATED KEYWORD SCORER (HINT ONLY, often wrong, see trap 3): "
        f"tier={fit.get('crawl_tier')}, score={fit.get('crawl_score')}/100, role={fit.get('business_role')}; "
        f"positive concepts: {pos}; negative concepts: {neg}; reason: {fit.get('crawl_reason') or 'n/a'}\n"
    )


def build_prompt(company_name, website, crawled_pages, no_site_found, extra_note=None, text_budget=None, scorer_hint=None):
    text_budget = text_budget or PROMPT_TEXT_BUDGET
    if no_site_found:
        source_block = extra_note or (
            "NO WEBSITE COULD BE FOUND OR CRAWLED. You may use general knowledge if you are confident about this company, "
            "but you MUST set every field you are not confident about to null or [], and set \"business_description\" "
            "to include a note that no live website source was available."
        )
    else:
        # split the budget evenly so a long homepage can't crowd out the
        # contact (HQ) and service pages that come after it
        per_page = max(800, text_budget // max(1, len(crawled_pages)))
        joined = "\n\n---PAGE BREAK---\n\n".join(
            f"URL: {p['url']}\n{p['text'][:per_page]}" for p in crawled_pages
        )
        source_block = f"WEBSITE CONTENT (scraped just now):\n{joined}"

    return f"""You are a B2B sales-intelligence analyst for Tritorc, a maker of hydraulic torque wrenches, bolt tensioners, flange management and on-site machining tools, and a provider of controlled-bolting and related field services. Profile the company "{company_name}" so Tritorc's sales team can decide whether it is a customer, a channel partner, or a competitor. Use ONLY the source material given below (website text if provided). Never invent facts; if something is unknown, use null or an empty list.

{source_block}
{scorer_hint_block(scorer_hint)}
TASK: Return a single JSON object with EXACTLY this shape (no extra keys, no markdown fences, no commentary):
{ENRICHMENT_SCHEMA_HINT}

Field rules:
- "company_name": the company's proper name.
- "website": the root URL used as source, or null if none.
- "country": the country of the company's headquarters. Check contact/about/footer text for "headquarters", "head office", "registered office" or "corporate office"; if several offices are listed, prefer the one carrying one of those labels, otherwise the first address on the contact page. Use the full English country name. null only if truly not stated.
- "hq_city": the headquarters city, or null.
- "hq_address": the headquarters street address exactly as written in the source, including postal/zip code when present, or null.
- "industry": the company's primary industry, as specific as the source allows (e.g. "LNG Terminal Operations" rather than "Energy"). Typical values: "Oil & Gas", "Refining", "Petrochemical", "Power Generation", "Nuclear", "Wind Energy", "Steel Manufacturing", "Cement", "Pulp & Paper", "Mining", "Shipbuilding", "Water/Wastewater", "Aerospace", "Construction", "Industrial Maintenance".
- "company_category": MUST be exactly one of "competitor", "distributor", "ECP", "end_user". Decide in this order:
  1. "competitor" if the company manufactures, brands, rents or sells the same tool categories Tritorc sells (hydraulic torque wrenches, bolt tensioners, flange management or on-site machining tools). Known competitor brands: {COMPETITOR_BRANDS}. A service contractor that merely USES such tools is NOT a competitor.
  2. "distributor" if it resells/distributes industrial tools or equipment made by others.
  3. "ECP" if it is an engineering/construction/procurement contractor or field-service contractor delivering projects for others.
  4. "end_user" for every other private company or government/public-sector organization that would use industrial tools/services in its own operations.
- "is_competitor": true when "company_category" is "competitor", otherwise false.
- "employee_count": approximate headcount as an integer if the source states it (e.g. "over 5,000 employees" -> 5000), otherwise null.
- "annual_turnover": the company's annual revenue/turnover exactly as the source states it (e.g. "US$12 billion", "INR 450 crore"), or null if the source does not state one.
- "turnover_class": the company's size by annual turnover, exactly one of "A", "B", "C", or null. {TURNOVER_BANDS} Decide in this order: (1) if "annual_turnover" is stated, convert it to US dollars and use the bands; (2) else if the source states headcount, estimate: 1,000 or more employees -> "A", 100 to 999 -> "B", under 100 -> "C"; (3) else if it is clearly a large listed or multinational group you know well, "A"; (4) otherwise null. Never guess a class for a small or unknown company.
- "turnover_basis": how "turnover_class" was decided, exactly one of "stated" (rule 1), "estimated from headcount" (rule 2), "well-known company" (rule 3), or null when "turnover_class" is null.
- "llm_decision": your sales verdict on whether Tritorc should pursue this company, exactly one of "accept", "review", "reject". Judge what the company itself OPERATES or is PAID TO DO, from the source text.
  Tritorc makes controlled-bolting tools (hydraulic torque wrenches, bolt tensioners), on-site machining (flange facing, pipe cutting/beveling), tube tools (expanders, cleaners, removal), hydraulic cylinders and pumps, pipe accessories, and runs field services (bolting, retubing, hot tapping, leak sealing, hydro-testing, calibration, rentals). Its real customers: pipeline operators, refineries and petrochemical plants, fertilizer/chemical plants, power and wind operators and their maintenance contractors, steel mills, shutdown/turnaround contractors, and industrial EPC/construction contractors. A good lead OWNS or OPERATES that kind of infrastructure, or is PAID by an owner to build, bolt, machine, test or maintain it.
  "accept" = such an operator; OR an EPC, general/design-build contractor, industrial-service contractor or OEM that builds or maintains industrial, plant, utility, water/wastewater, power or pipeline assets. A diversified contractor that lists many building types is not a restaurant or a shop: if industrial or plant work is a real part of what it does, accept.
  "review" = a distributor or rental house for industrial tools (a possible channel partner: note any competing brands), a company where the relevant work is only incidental, or evidence too thin to judge.
  "reject" = a competitor (makes, brands or rents the same tool categories), or a company with no industrial plant or piping work (retail, offices, software, real estate, hospitality, healthcare, schools, residential trades). Reject needs positive evidence of one of these. A thin, blocked or empty source is NOT a reason to reject: answer "review" and say the evidence was missing.
  Three traps to avoid: (1) Client lists, past-project portfolios and sector lists (restaurants, retail, schools, hotels, roofing) do not describe what the company is; ignore them unless that is its own core work. (2) A company paid to do bolting, machining, testing or turnaround work at other companies' plants is a contractor lead even if it also supplies tools; one whose own product is the tools (makes, brands, rents, resells them) is a competitor or distributor. (3) The automated keyword scorer hint, when shown, is a blunt keyword match: never copy its reject when the text shows real industrial work, and never accept just because it scored high.
- "llm_decision_reason": one short plain sentence naming the evidence behind "llm_decision".
- "business_description": 2-4 factual sentences describing what the company does, grounded in the source text.
- "key_operations": up to 8 concrete operational activities/business lines taken from the source. Prefer specific ones ("turbine maintenance", "pipeline construction") over generic ones ("consulting", "engineering").
- "projects_or_recent_activity": at most 5 of the most notable or recent named projects, plants, contracts, expansions or news items from the source. Each as "Project/contract (client if named, scope or value if stated) (year)". Newest first. Empty list if none.
- "tritorc_relevance": list of short strings, each naming a SPECIFIC Tritorc product category, example product, or service from the catalog below AND why it's relevant to this company's operations (e.g. "Hydraulic Torque Wrenches (e.g. TSL Series) — relevant for flange bolting during the refinery turnarounds mentioned on their site"). Only reference items that actually appear in the catalog below. If nothing in the source material suggests a real need, return an empty list rather than forcing a match.

TRITORC PRODUCT & SERVICE CATALOG (only reference items from this list in tritorc_relevance):
{TRITORC_BLOCK}

Return ONLY the JSON object."""


def normalize_if_url(entry: str):
    """If the input line is already a URL/domain, return a normalized https:// URL. Else None."""
    candidate = entry.strip()
    if " " in candidate:
        return None
    if not URL_LIKE_RE.match(candidate):
        return None
    if not candidate.startswith("http://") and not candidate.startswith("https://"):
        candidate = "https://" + candidate
    return candidate


def call_groq_with_retry(client, prompt: str, max_retries: int = 4):
    from groq import APIStatusError

    last_err = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=settings.groq_model,
                messages=[
                    {"role": "system", "content": "You return only valid JSON. Never wrap it in markdown code fences."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=1200,
                response_format={"type": "json_object"},
                reasoning_effort="low",
            )
        except APIStatusError as e:
            last_err = e
            if e.status_code == 429:
                wait_s = 5.0
                try:
                    body = e.response.json()
                    msg = body.get("error", {}).get("message", "")
                    m = re.search(r"try again in ([\d.]+)s", msg)
                    if m:
                        wait_s = float(m.group(1)) + 0.5
                except Exception:
                    pass
                time.sleep(min(wait_s, 30))
                continue
            if e.status_code == 400 and "json_validate_failed" in str(e):
                # transient generation glitch (malformed/truncated JSON); retry immediately
                continue
            raise
    raise last_err


def resolve_from_email(email: str):
    """If the input is an email address, derive the company's website from its
    domain. Returns (website, display_name, domain, is_free_email_domain)."""
    m = EMAIL_RE.match(email.strip())
    if not m:
        return None
    domain = m.group(1).lower()
    if domain in FREE_EMAIL_DOMAINS:
        return (None, email.strip(), domain, True)
    return (f"https://{domain}", domain, domain, False)



NAME_KEY_CANDIDATES = ["company_name", "company", "name", "companies", "email", "email_address"]
HEADER_NAME_CANDIDATES = ("company_name", "company name", "company", "name", "email", "email address")


def _extract_names_from_json(data):
    if isinstance(data, list):
        names = []
        for item in data:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for k in NAME_KEY_CANDIDATES:
                    if item.get(k):
                        names.append(str(item[k]))
                        break
        return names
    if isinstance(data, dict):
        for k in NAME_KEY_CANDIDATES:
            if isinstance(data.get(k), list):
                return _extract_names_from_json(data[k])
        return []
    return []


def _pick_name_column(header_row):
    """Given a header row, find the column index most likely to hold company
    names. Falls back to the first column if nothing matches."""
    if not header_row:
        return 0
    lowered = [str(h or "").strip().lower() for h in header_row]
    for candidate in ["company_name", "company name", "company", "name", "organization", "organisation", "email", "email address"]:
        if candidate in lowered:
            return lowered.index(candidate)
    return 0


def parse_companies_file(filename: str, content: bytes):
    """Extract a flat list of company names from an uploaded .txt/.csv/.xlsx/.json file."""
    ext = os.path.splitext(filename.lower())[1]

    if ext == ".json":
        data = json.loads(content.decode("utf-8"))
        return [n.strip() for n in _extract_names_from_json(data) if str(n).strip()]

    if ext == ".csv":
        text = content.decode("utf-8-sig", errors="ignore")
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []
        col = _pick_name_column(rows[0])
        looks_like_header = _pick_name_column(rows[0]) != 0 or any(
            str(h or "").strip().lower() in HEADER_NAME_CANDIDATES
            for h in rows[0]
        )
        data_rows = rows[1:] if looks_like_header else rows
        return [r[col].strip() for r in data_rows if len(r) > col and r[col].strip()]

    if ext in (".xlsx", ".xlsm"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            return []
        col = _pick_name_column(rows[0])
        looks_like_header = any(
            str(h or "").strip().lower() in HEADER_NAME_CANDIDATES
            for h in rows[0]
        )
        data_rows = rows[1:] if looks_like_header else rows
        return [str(r[col]).strip() for r in data_rows if len(r) > col and r[col] and str(r[col]).strip()]

    # .txt and anything else: treat as plain text, one name per line (or comma-separated)
    text = content.decode("utf-8", errors="ignore")
    parts = re.split(r"[\r\n,]+", text)
    return [p.strip() for p in parts if p.strip()]


def score_pages(name: str | None, website: str | None, pages: list) -> dict:
    """Run Lead Discovery's own fit scorer (crawl_scorer.score_crawl) over
    already-crawled pages -- no network. Same tier/role/evidence as a Places
    lead, so Enrichment and Search results are directly comparable."""
    if not pages:
        return {}
    result = score_crawl(
        PlaceDetails(name=name or "", address="", website=website),
        [CrawledPage(url=p["url"], title=p.get("title", ""), text=p.get("text", "")) for p in pages],
    )
    return {
        "crawl_score": result.score,
        "crawl_tier": result.tier,
        "business_role": result.business_role,
        "business_role_reason": result.business_role_reason,
        "customer_type": CUSTOMER_TYPE_FROM_ROLE.get(result.business_role, "unknown"),
        "crawl_reason": result.reason,
        "positive_concepts": result.positive_concepts,
        "negative_concepts": result.negative_concepts,
        "crawl_evidence": result.evidence,
        "crawl_evidence_urls": result.evidence_urls,
        "detected_language": result.detected_language,
        "scoring_version": result.scoring_version,
    }


def enrich_company(client, company_input: str, pages: list | None = None, website: str | None = None):
    """Resolve -> crawl -> Groq extraction for one input line.

    If `pages`/`website` are supplied (cache reuse), the crawl is skipped and
    only the LLM step reruns. Returns (data, pages, meta) where meta carries
    the crawl outcome for storage.
    """
    email_match = resolve_from_email(company_input)
    direct_url = normalize_if_url(company_input)
    is_free_email = False
    email_domain = None
    err = None
    contacts = {"emails": [], "phones": [], "social_links": {}}

    if website:
        display_name = company_input
    elif email_match:
        website, display_name, email_domain, is_free_email = email_match
        if is_free_email:
            # a personal/webmail address carries no employer signal; don't
            # guess a company from it.
            website = None
    elif direct_url:
        website = direct_url
        display_name = urlparse(direct_url).netloc
    else:
        website = find_official_site(client, company_input)
        display_name = company_input

    if pages is None:
        pages, err, contacts = (
            ([], "no website found", contacts) if not website else crawl_company_site(website)
        )
        if not pages and website:
            # direct URL might have a trailing path or a different scheme; retry with bare origin
            parsed = urlparse(website)
            fallback = f"{parsed.scheme}://{parsed.netloc}"
            if fallback != website:
                pages, err, contacts = crawl_company_site(fallback)
                if pages:
                    website = fallback
    no_site_found = not pages
    extra_note = (
        f'The input "{company_input}" is a personal/webmail email address (domain "{email_domain}" is a consumer '
        "email provider, not a company domain). It carries NO reliable signal about the sender's employer. "
        "Set every field to null or [] except business_description, which must state that the employer could not be "
        "determined from a personal email domain."
        if is_free_email else None
    )

    scorer_hint = score_pages(display_name, website, pages) if pages else None
    completion = None
    for budget in PROMPT_TEXT_BUDGET_STEPS:
        prompt = build_prompt(display_name, website, pages, no_site_found, extra_note=extra_note, text_budget=budget, scorer_hint=scorer_hint)
        try:
            completion = call_groq_with_retry(client, prompt)
            break
        except APIStatusError as e:
            if e.status_code != 413 or budget == PROMPT_TEXT_BUDGET_STEPS[-1]:
                raise
    raw = completion.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0)) if match else {**EMPTY_RESULT, "company_name": display_name, "website": website}

    data.setdefault("company_name", display_name)
    if not data.get("website"):
        data["website"] = website
    fit = score_pages(data.get("company_name") or display_name, data.get("website") or website, pages)
    meta = {
        "crawl_status": "ok" if pages else "no_content",
        "crawl_error": None if pages else err,
        "contacts": contacts,
        "fit": fit,
    }
    reconcile_competitor(data, fit, has_source=bool(pages))
    return data, pages, meta


VALID_CATEGORIES = {"competitor", "distributor", "ECP", "end_user"}
def _turnover_basis(raw, stated: str | None, employees) -> str:
    """Normalize how a turnover class was decided. Tolerates the model's wording
    ("estimated from headcount (150 employees)") and infers it from the data when
    missing, so a valid class is never dropped over a label."""
    text = str(raw or "").strip().lower()
    if "stat" in text:
        return "stated"
    if "head" in text or "employ" in text:
        return "estimated from headcount"
    if "known" in text or "well" in text:
        return "well-known company"
    if stated:
        return "stated"
    if employees:
        return "estimated from headcount"
    return "well-known company"


def classify_error(exc: Exception) -> tuple[str, str]:
    """(code, plain-language message) for a failed enrichment, so a casual
    user never sees a raw exception."""
    if isinstance(exc, UnsafeURLError):
        return "blocked_url", "That address isn't a public website, so it was skipped."
    if isinstance(exc, RuntimeError) and "GROQ_API_KEY" in str(exc):
        return "not_configured", "The AI service isn't set up on the server. Ask an admin to add the API key."
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return "rate_limited", "The AI service is busy right now. Wait a minute, then press Retry."
        if exc.status_code == 413:
            return "too_large", "This company's pages were too long for the AI to read. Press Retry."
        if exc.status_code in (401, 403):
            return "not_configured", "The AI service rejected the server's key. Ask an admin to check it."
        return "ai_error", "The AI service had a problem. Press Retry in a moment."
    name = type(exc).__name__
    if name in {"APIConnectionError", "APITimeoutError", "Timeout", "ReadTimeout", "ConnectTimeout", "ConnectionError"}:
        return "ai_unreachable", "Couldn't reach a service we depend on. Check your connection and press Retry."
    return "unknown", "Something went wrong with this company. Press Retry; if it keeps happening, tell an admin."


def reconcile_competitor(data: dict, fit: dict | None, has_source: bool = True) -> None:
    """Keep company_category / is_competitor consistent and let either the LLM
    or the rule-based scorer mark a competitor (HYTORC, Enerpac, ...)."""
    cat = data.get("company_category")
    if cat not in VALID_CATEGORIES:
        cat = {"ecp": "ECP", "end user": "end_user", "enduser": "end_user"}.get(str(cat or "").strip().lower(), cat if cat in VALID_CATEGORIES else None)
    scorer_says = (fit or {}).get("business_role") == "competitor_manufacturer"
    own = "tritorc" in f"{data.get('website') or ''} {data.get('company_name') or ''}".lower()
    if own:
        data["is_competitor"] = False
        cat = None if cat == "competitor" else cat
    elif scorer_says or data.get("is_competitor") is True or cat == "competitor":
        cat = "competitor"
        data["is_competitor"] = True
    else:
        data["is_competitor"] = False
    data["company_category"] = cat
    decision = str(data.get("llm_decision") or "").strip().lower()
    if decision not in {"accept", "review", "reject"}:
        decision = None
    if data["is_competitor"]:
        decision = "reject"
        if not data.get("llm_decision_reason"):
            data["llm_decision_reason"] = "Competitor: sells the same tool categories as Tritorc."
    if own:
        decision = None
    if not has_source and decision in ("accept", "reject") and not data["is_competitor"]:
        # no website text was read, so this is a guess from general knowledge: never a confident call
        data["llm_decision_reason"] = "No website could be read, so this is not confirmed. " + (data.get("llm_decision_reason") or "")
        decision = "review"
    data["llm_decision"] = decision
    data["llm_decision_reason"] = (data.get("llm_decision_reason") or None) if decision else None
    tclass = str(data.get("turnover_class") or "").strip().upper()
    stated = str(data.get("annual_turnover") or "").strip()[:80] or None
    if tclass not in {"A", "B", "C"} or own:
        tclass, tbasis = None, None
    else:
        tbasis = _turnover_basis(data.get("turnover_basis"), stated, data.get("employee_count"))
    data["turnover_class"] = tclass
    data["turnover_basis"] = tbasis
    data["annual_turnover"] = stated
    emp = data.get("employee_count")
    if isinstance(emp, str):
        digits = re.sub(r"[^\d]", "", emp)
        emp = int(digits) if digits else None
    data["employee_count"] = emp if isinstance(emp, int) and emp > 0 else None
