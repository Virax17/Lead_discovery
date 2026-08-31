import httpx

from app.services.error_logger import log_error

# English + French domain terms for Tritorc's actual product/customer space
# (controlled bolting, flange management, pipeline integrity) — used as a free
# first pass to distinguish a real bolting/machining company from a name/
# keyword coincidence. "bride" (not "bridage", which means throttling/
# restriction in French) is the correct French word for "flange". Bare
# "tension" is intentionally excluded — in French it commonly means
# electrical voltage, which would false-positive on electricians/utilities.
DOMAIN_TERMS = [
    # English
    "torque", "torquing", "tensioner", "tensioning", "flange", "bolting",
    "bolt", "bolted joint", "bolt tensioner", "hydraulic", "hydraulic wrench",
    "fastener", "gasket", "turnaround", "shutdown maintenance",
    "pipeline integrity", "flange management", "tube expander", "hot tapping",
    "onsite machining",
    "pipeline", "pipelines",
    # French
    "serrage", "boulonnage", "boulon", "bride", "usinage", "hydraulique",
    "tension de boulons", "mise en tension", "arrêt technique",
    "intégrité des pipelines", "expandeur de tubes", "étanchéité",
    "canalisation",
]

_TIMEOUT = httpx.Timeout(6.0, connect=4.0)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadDiscoveryBot/1.0)"}
_MAX_TEXT_CHARS = 20000
# If more than this fraction of the decoded text is the Unicode replacement
# character, the declared/guessed charset was wrong (common on older French/
# European sites that claim UTF-8 but actually serve Windows-1252) — re-decode
# the raw bytes as cp1252 instead of trusting the mangled UTF-8 decode.
_REPLACEMENT_CHAR_RATIO_THRESHOLD = 0.002


def _decode_with_fallback(content: bytes, guessed_encoding: str | None) -> str:
    text = content.decode(guessed_encoding or "utf-8", errors="replace")
    if text and (text.count("�") / len(text)) > _REPLACEMENT_CHAR_RATIO_THRESHOLD:
        try:
            return content.decode("cp1252", errors="replace")
        except Exception:
            pass
    return text


async def scan_website(url: str | None) -> dict:
    """Best-effort homepage scan for Tritorc-relevant domain terms. Never raises."""
    if not url:
        return {"checked": False, "matched_terms": [], "raw_text": ""}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = _decode_with_fallback(response.content, response.encoding)
    except Exception as e:
        await log_error(search_id=None, stage="website_scan", place_id=None, error_message=f"{url}: {str(e)}")
        return {"checked": False, "matched_terms": [], "raw_text": ""}

    lower_text = text.lower()
    matched = [term for term in DOMAIN_TERMS if term in lower_text]
    return {"checked": True, "matched_terms": matched, "raw_text": text[:_MAX_TEXT_CHARS]}


def summarize_signal(website: str | None, scan_result: dict) -> str:
    if not website:
        return "no website"
    if not scan_result["checked"]:
        return "unreachable"
    if scan_result["matched_terms"]:
        return "matched: " + ", ".join(scan_result["matched_terms"])
    return "no match"
