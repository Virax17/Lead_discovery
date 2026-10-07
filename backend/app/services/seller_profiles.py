"""Seller profiles: who we are judging a lead FOR.

Enrichment asks the model "should <seller> pursue this company?". Everything
that differs per seller lives here: what they sell, who buys it, which brands
compete with them, and the accept / review / reject rules. The website crawl is
shared, so one company can be accepted for one seller and rejected for another.

To add a seller: add a SellerProfile to PROFILES, and (optionally) a rule-based
scorer in services/<seller>_scorer.py wired up in enrichment_engine.score_for_profile.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_PROFILE = "tritorc"

_OFFERINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "tritorc_offerings.json"
)
with open(_OFFERINGS_PATH, encoding="utf-8") as _f:
    TRITORC_OFFERINGS = json.load(_f)

# category-level summary (not marketing copy) to keep the grounding payload small
# enough to stay well under Groq's per-minute token limits across back-to-back calls.
TRITORC_CATALOG = json.dumps(
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

# From ozat-tools.com (OZAT 2000 UG, Germany): impact sockets 1/4"-3-1/2" drive, wrenches,
# bolting accessories, bearing-nut and railway sockets; custom sockets for OEMs; sold via
# authorized distributors; used in oil & gas, energy, mining, construction, rail, marine, auto.
OZAT_CATALOG = json.dumps(
    {
        "products": [
            {
                "name": "Impact Sockets",
                "examples": ["1/4 to 3-1/2 inch square drive", "4/6/8/12-point, deep, spline, Torx, inhex drivers", "universal and loss-of-vibration sockets"],
                "uses": ["drilling rigs, wellheads, pipeline flanges, refinery maintenance", "wind turbines, thermal and hydro plants", "mining and construction equipment"],
            },
            {
                "name": "Impact Socket Sets",
                "examples": ["professional sets of popular sizes"],
                "uses": ["power", "mining", "oil & gas"],
            },
            {
                "name": "Impact and Striking Wrenches",
                "examples": ["striking and slogging wrenches", "offset ring, open, ratchet, crowfoot wrenches"],
                "uses": ["flange bolting", "structural assembly", "tight or heavy-duty spaces"],
            },
            {
                "name": "Bolting Accessories",
                "examples": ["adapters", "extension bars", "universal joints", "lug nut sockets", "torsion bars", "tubular handles", "retaining pins and rings"],
                "uses": ["complex and confined bolting jobs", "heavy-vehicle wheel service"],
            },
            {
                "name": "Bearing Nut Sockets",
                "examples": ["GU type", "KM type"],
                "uses": ["heavy-duty bearing lock nuts in machinery and vehicles"],
            },
            {
                "name": "Railway Sockets",
                "examples": ["track fastening and maintenance sockets"],
                "uses": ["railway track and rolling-stock maintenance"],
            },
            {
                "name": "Custom Solutions",
                "examples": ["custom sockets designed to a customer's requirements"],
                "uses": ["OEMs"],
            },
        ],
        "services": [
            "Custom socket engineering for OEMs",
            "Authorized distributor programme",
            "ISO and DIN compliant designs",
        ],
    },
    ensure_ascii=False,
    separators=(",", ":"),
)


@dataclass(frozen=True)
class SellerProfile:
    id: str
    name: str
    own_tokens: tuple[str, ...]   # the seller's own name/domain: never a lead for itself
    intro: str                    # who the seller is; "{company_name}" is filled in
    fit_key: str                  # JSON key of the "why it fits" list
    fit_example: str
    competitor_brands: str
    competitor_rule: str
    distributor_rule: str
    decision_rules: str
    catalog: str


TRITORC = SellerProfile(
    id="tritorc",
    name="Tritorc",
    own_tokens=("tritorc",),
    intro=(
        "You are a B2B sales-intelligence analyst for Tritorc, a maker of hydraulic torque wrenches, bolt tensioners, "
        "flange management and on-site machining tools, and a provider of controlled-bolting and related field services. "
        'Profile the company "{company_name}" so Tritorc\'s sales team can decide whether it is a customer, a channel '
        "partner, or a competitor."
    ),
    fit_key="tritorc_relevance",
    fit_example="Hydraulic Torque Wrenches (e.g. TSL Series) — relevant for flange bolting during the refinery turnarounds mentioned on their site",
    competitor_brands=(
        "HYTORC, Enerpac, Hydratight, Atlas Copco, Hi-Force, RAD Torque, ITH, Riverhawk, "
        "TorcUP, Norbar, SPX FLOW Power Team, Wren Hydraulic, Equalizer International"
    ),
    competitor_rule=(
        '"competitor" if the company manufactures, brands, rents or sells the same tool categories Tritorc sells '
        "(hydraulic torque wrenches, bolt tensioners, flange management or on-site machining tools). "
        "Known competitor brands: {brands}. A service contractor that merely USES such tools is NOT a competitor."
    ),
    distributor_rule='"distributor" if it resells/distributes industrial tools or equipment made by others.',
    decision_rules=(
        "Judge what the company itself OPERATES or is PAID TO DO, from the source text.\n"
        "  Tritorc makes controlled-bolting tools (hydraulic torque wrenches, bolt tensioners), on-site machining (flange facing, pipe cutting/beveling), tube tools (expanders, cleaners, removal), hydraulic cylinders and pumps, pipe accessories, and runs field services (bolting, retubing, hot tapping, leak sealing, hydro-testing, calibration, rentals). Its real customers: pipeline operators, refineries and petrochemical plants, fertilizer/chemical plants, power and wind operators and their maintenance contractors, steel mills, shutdown/turnaround contractors, and industrial EPC/construction contractors. A good lead OWNS or OPERATES that kind of infrastructure, or is PAID by an owner to build, bolt, machine, test or maintain it.\n"
        '  "accept" = such an operator; OR an EPC, general/design-build contractor, industrial-service contractor or OEM that builds or maintains industrial, plant, utility, water/wastewater, power or pipeline assets. A diversified contractor that lists many building types is not a restaurant or a shop: if industrial or plant work is a real part of what it does, accept.\n'
        '  "review" = a distributor or rental house for industrial tools (a possible channel partner: note any competing brands), a company where the relevant work is only incidental, or evidence too thin to judge.\n'
        '  "reject" = a competitor (makes, brands or rents the same tool categories), or a company with no industrial plant or piping work (retail, offices, software, real estate, hospitality, healthcare, schools, residential trades). Reject needs positive evidence of one of these. A thin, blocked or empty source is NOT a reason to reject: answer "review" and say the evidence was missing.\n'
        "  Three traps to avoid: (1) Client lists, past-project portfolios and sector lists (restaurants, retail, schools, hotels, roofing) do not describe what the company is; ignore them unless that is its own core work. (2) A company paid to do bolting, machining, testing or turnaround work at other companies' plants is a contractor lead even if it also supplies tools; one whose own product is the tools (makes, brands, rents, resells them) is a competitor or distributor. (3) The automated keyword scorer hint, when shown, is a blunt keyword match: never copy its reject when the text shows real industrial work, and never accept just because it scored high."
    ),
    catalog=TRITORC_CATALOG,
)

OZAT = SellerProfile(
    id="ozat",
    name="Ozat",
    own_tokens=("ozat",),
    intro=(
        "You are a B2B sales-intelligence analyst for Ozat (OZAT 2000 UG, Germany), a manufacturer of heavy-duty impact "
        "sockets (1/4 to 3-1/2 inch square drive), impact and striking wrenches, bolting accessories, bearing-nut sockets "
        "and railway sockets, with custom solutions for OEMs, sold through authorized distributors. "
        'Profile the company "{company_name}" so Ozat\'s sales team can decide whether it is an end customer, an OEM, '
        "a distribution partner, or a competitor."
    ),
    fit_key="ozat_relevance",
    fit_example="Impact Sockets (3-1/2 inch drive, 6-point) — for the rig and wellhead bolting this operator describes",
    competitor_brands=(
        "Gedore, Stahlwille, Hazet, Facom, Snap-on, Proto, Williams, Grey Pneumatic, Sunex, "
        "Wright Tool, KS Tools, Heyco, Ingersoll Rand"
    ),
    competitor_rule=(
        '"competitor" if the company manufactures or brands impact sockets, impact/striking wrenches or similar heavy-duty '
        "bolting hand tools (the products Ozat makes). Known competitor brands: {brands}. A company that merely buys, "
        "uses or resells such tools is NOT a competitor."
    ),
    distributor_rule=(
        '"distributor" if it resells/distributes industrial tools, fasteners or MRO supplies made by others '
        "(a possible Ozat distribution partner)."
    ),
    decision_rules=(
        "Judge what the company itself OPERATES, MAINTAINS, MANUFACTURES or RESELLS, from the source text.\n"
        "  Ozat's tools are used by technicians doing heavy bolting: oil & gas (rigs, wellheads, pipelines, refineries), power and energy (wind turbines, thermal, hydro, nuclear), mining and quarrying, construction and heavy equipment, railway track and rolling stock, marine and shipyards, structural steel, process plants, and heavy-vehicle automotive maintenance and production. Ozat sells through authorized distributors and supplies OEMs with standard and custom sockets.\n"
        '  "accept" = (a) a distributor, wholesaler, rental house or MRO/industrial-supplies reseller that sells tools or fasteners to industry (a distribution partner, which is Ozat\'s main route to market); (b) an OEM or manufacturer of heavy machinery, vehicles, rail equipment, wind turbines or similar products that is assembled with large bolts (a supply or custom-socket customer); or (c) an operator or maintenance/service contractor with heavy mechanical work in one of the sectors above (fleet and equipment maintenance, plant shutdowns, wind-farm service, mining equipment upkeep, rail maintenance).\n'
        '  "review" = a company where heavy bolting work is only incidental, a small general workshop or garage, or evidence too thin to judge.\n'
        '  "reject" = a competitor (makes or brands the same tool categories), or a company with no mechanical bolting need (retail, offices, software, hospitality, healthcare, schools, residential trades, pure consultancies). Reject needs positive evidence of one of these. A thin, blocked or empty source is NOT a reason to reject: answer "review" and say the evidence was missing.\n'
        "  Three traps to avoid: (1) Client lists, project portfolios and sector lists do not describe what the company is; ignore them unless that is its own core work. (2) A company that makes or brands impact sockets or wrenches itself is a competitor even if it also distributes other brands; a pure reseller of many brands is a distribution partner, not a competitor; a company that merely uses the tools is a customer. (3) The automated keyword scorer hint, when shown, is a blunt keyword match: never copy its reject when the text shows real mechanical or industrial work, and never accept just because it scored high."
    ),
    catalog=OZAT_CATALOG,
)

PROFILES: dict[str, SellerProfile] = {p.id: p for p in (TRITORC, OZAT)}


def get_profile(profile_id: str | None) -> SellerProfile:
    return PROFILES.get((profile_id or DEFAULT_PROFILE).lower(), TRITORC)


def valid_profile_id(profile_id: str | None) -> str | None:
    """The canonical id, or None if unknown (callers turn that into a 400)."""
    pid = (profile_id or DEFAULT_PROFILE).lower()
    return pid if pid in PROFILES else None
