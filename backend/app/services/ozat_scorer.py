"""Rule-based keyword scorer for Ozat (heavy-duty impact sockets and wrenches).

Same output shape as enrichment_engine.score_pages (the Tritorc scorer), so the
UI can show either one. It is a blunt hint for the LLM, never the final call:
it counts which of Ozat's buyer signals appear on a company's site.
"""
from __future__ import annotations

import re

SCORING_VERSION = "ozat-score-v1"

# distribution partners are Ozat's main route to market, so unlike Tritorc's scorer they score POSITIVE
DISTRIBUTION = [
    "authorized distributor", "authorised distributor", "industrial supplies", "industrial supplier",
    "tool distributor", "tools distributor", "tool wholesaler", "wholesale tools", "mro", "industrial tools",
    "hardware and tools", "tools and fasteners", "fasteners and tools", "tool supplier", "supplier of tools",
]
BOLTING = ["bolting", "bolted", "torque", "tightening", "flange", "fastening", "lug nut", "wheel nut", "impact wrench", "socket"]
MAINTENANCE = ["maintenance", "shutdown", "turnaround", "overhaul", "field service", "mro", "heavy repair"]
OEM = ["oem", "original equipment manufacturer", "machine builder", "manufacturer of machines", "machinery manufacturer", "equipment manufacturer"]

INDUSTRIES = {
    "oil_gas": ["oil and gas", "oil & gas", "refinery", "refineries", "offshore", "pipeline", "drilling", "wellhead", "petrochemical"],
    "power_energy": ["power plant", "wind turbine", "wind farm", "wind energy", "hydropower", "hydroelectric", "thermal power", "nuclear", "power generation"],
    "mining": ["mining", "quarry", "quarries", "mine site", "mineral processing"],
    "construction_heavy": ["construction equipment", "heavy equipment", "earthmoving", "earth moving", "crane", "heavy machinery", "excavator"],
    "railway": ["railway", "railroad", "rolling stock", "track maintenance", "rail maintenance", "locomotive"],
    "marine": ["shipyard", "shipbuilding", "ship repair", "marine engineering", "offshore vessel"],
    "heavy_vehicles": ["truck", "trailer", "commercial vehicle", "heavy vehicle", "fleet maintenance", "bus fleet", "tractor", "agricultural machinery"],
    "steel_heavy_eng": ["steel plant", "steel mill", "heavy engineering", "fabrication", "structural steel", "foundry"],
    "process": ["chemical plant", "process industry", "fertilizer", "cement plant"],
}

NEGATIVE = [
    "restaurant", "hotel", "school", "real estate", "clinic", "salon", "bakery", "retail store", "boutique",
    "web design", "software development", "law firm", "travel agency", "wedding",
]

COMPETITOR_BRANDS = [
    "gedore", "stahlwille", "hazet", "facom", "snap-on", "snap on", "proto tools", "williams tools", "grey pneumatic",
    "sunex", "wright tool", "ks tools", "heyco", "ingersoll rand", "ingersoll-rand",
]
COMPETITOR_PHRASES = [
    "manufacturer of impact sockets", "impact socket manufacturer", "impact sockets manufacturer", "socket manufacturer",
    "manufacturer of sockets", "wrench manufacturer", "manufacturer of wrenches", "hand tools manufacturer",
    "manufacturer of hand tools", "forged tools manufacturer", "we manufacture sockets", "we manufacture wrenches",
]


def _snippet(text: str, needle: str, width: int = 110) -> str:
    i = text.lower().find(needle)
    if i < 0:
        return ""
    s = max(0, i - width // 2)
    return re.sub(r"\s+", " ", text[s:i + len(needle) + width // 2]).strip()


def _hits(low: str, terms: list[str]) -> list[str]:
    return [t for t in terms if re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low)]


def score_ozat(name: str | None, website: str | None, pages: list) -> dict:
    if not pages:
        return {}
    texts = [(p.get("url", ""), (p.get("title", "") + "\n" + p.get("text", ""))) for p in pages]
    blob = "\n".join(t for _, t in texts)
    low = blob.lower()

    comp_brands = _hits(low, COMPETITOR_BRANDS)
    comp_phrases = _hits(low, COMPETITOR_PHRASES)
    distribution = _hits(low, DISTRIBUTION)
    bolting = _hits(low, BOLTING)
    maintenance = _hits(low, MAINTENANCE)
    oem = _hits(low, OEM)
    industries = {k: v for k, v in ((k, _hits(low, terms)) for k, terms in INDUSTRIES.items()) if v}
    negatives = _hits(low, NEGATIVE)

    positive = [f"industry:{k}" for k in industries]
    if distribution: positive.append("tool_distribution")
    if bolting: positive.append("bolting_work")
    if maintenance: positive.append("heavy_maintenance")
    if oem: positive.append("oem_manufacturer")

    score = (
        min(4, len(industries)) * 12
        + (12 if bolting else 0)
        + (8 if maintenance else 0)
        + (14 if oem else 0)
        + (35 if distribution else 0)
        - 25 * min(2, len(negatives))
    )
    score = max(0, min(100, score))

    # a competitor is a company whose OWN product is these tools; a brand name alone in a reseller's catalog is not
    competitor = bool(comp_phrases) or (len(comp_brands) >= 1 and not distribution)
    if competitor:
        role, tier = "competitor_manufacturer", "reject"
        reason = f"Looks like a maker or brand of the same tools as Ozat ({', '.join((comp_phrases + comp_brands)[:3])})."
    else:
        if distribution and score >= 30:
            role = "supplier_distributor"
        elif negatives and not industries:
            role = "generic_local_service"
        elif industries or oem or maintenance:
            role = "end_user_operator"
        else:
            role = "unknown"
        tier = "best" if score >= 75 else "strong" if score >= 55 else "weak" if score >= 30 else "reject"
        bits = []
        if industries: bits.append("industries: " + ", ".join(industries))
        if distribution: bits.append("sells tools to industry (distribution partner)")
        if oem: bits.append("OEM / machine builder")
        if bolting: bits.append("bolting work")
        if negatives: bits.append("negative: " + ", ".join(negatives[:3]))
        reason = ("Matched " + "; ".join(bits) + ".") if bits else "No Ozat buyer signals found on the site."

    evidence, urls = [], []
    for term in (comp_phrases[:1] + distribution[:1] + (list(industries.values())[0][:1] if industries else []) + bolting[:1]):
        for url, text in texts:
            snip = _snippet(text, term)
            if snip:
                evidence.append(snip)
                urls.append(url)
                break
        if len(evidence) >= 4:
            break

    return {
        "crawl_score": score,
        "crawl_tier": tier,
        "business_role": role,
        "business_role_reason": reason,
        "customer_type": {"supplier_distributor": "distributor", "competitor_manufacturer": "irrelevant",
                          "generic_local_service": "irrelevant", "end_user_operator": "end_user_operator"}.get(role, "unknown"),
        "crawl_reason": reason,
        "positive_concepts": positive,
        "negative_concepts": negatives + [f"competitor:{b}" for b in comp_brands],
        "crawl_evidence": evidence,
        "crawl_evidence_urls": urls,
        "detected_language": None,
        "scoring_version": SCORING_VERSION,
    }
