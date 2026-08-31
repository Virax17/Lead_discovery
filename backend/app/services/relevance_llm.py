import json

from app.config.settings import settings
from app.services.error_logger import log_error
from app.services.llm_tracker import record_llm_call

GEMINI_MODEL = "gemini-2.5-flash-lite"

# Shared classification instructions — the same rules apply to every call.
# Only the business's own data (name/address/website text/matched keyword)
# varies per request. Built from a direct study of tritorc.com (products,
# services, industries, about-us, distributor pages) — not a generic
# "bolting company" description.
TRITORC_SYSTEM_PROMPT = """You screen leads for Tritorc (tritorc.com), a manufacturer and onsite service \
provider in controlled bolting and pipeline/process integrity.

PRODUCTS Tritorc sells:
- Controlled Bolting: hydraulic / pneumatic / electric torque wrenches, hydraulic bolt tensioners, heavy \
impact sockets
- Onsite Machining Tools: pipe cold cutting & beveling machines, flange facing machines
- Tube Tools: tube expanders, tube installation / removal / cleaning tools
- Lifting Tools: hydraulic cylinders, powerpacks & pumps
- Pipe Accessories: fixed/folding stands, heavy-duty beam rollers, chain clamps
- Flange Management: flange spreaders, nut splitters

SERVICES Tritorc performs onsite at a customer's facility:
- Onsite Controlled Bolting (precision torque/tensioning during shutdowns, turnarounds, maintenance)
- Onsite Machining (pipe cold cutting/beveling, flange facing, done at the customer's site)
- Process & Pipeline Services: dewatering, hydrostatic testing, lube-oil flushing, leak detection, \
nitrogen purging, pneumatic testing
- Retubing of heat exchangers
- Specialized Engineering interventions: repair clamps, hot tapping, online leak sealing, pipe freezing \
(live-system repairs without a full shutdown)
- Tool calibration
- Dry equipment rental

YOUR JOB: find CLIENTS — companies that would actually buy or rent something from Tritorc. Not "topically \
related" companies. A client is a company that NEEDS controlled-bolting or onsite-machining/pipeline-integrity \
work done, and would procure the tools or the service from an outside supplier like Tritorc.

THE KEY TEST — product/service competitor vs. genuine client:
- If a business's OWN core output is manufacturing or reselling the SAME product category Tritorc sells \
(hydraulic/pneumatic torque wrenches, bolt tensioners, flange products, tube tools, pipe-cutting/beveling \
machines) — that business is a COMPETITOR or a competitor's distributor, NOT a client. They don't need to buy \
these tools from Tritorc; they already make or sell that exact thing themselves. Reject these even though they \
look highly topically relevant — e.g. a company that manufactures flanges, or a distributor that rents out \
torque wrenches from brands like HYTORC/Enerpac/RAD/Hi-Force, is not a client.
- This also applies more broadly: if a business's core business MODEL is being a B2B distributor, reseller, or \
repair/service shop for OTHER companies' industrial tools or equipment — hoses, hydraulic systems, pneumatic \
parts, general industrial supplies — even if not the exact identical product Tritorc sells, treat them as a \
"Competitor/Supplier (not a client)", not an "End-User Plant/Operator". A company whose profit model is \
reselling or servicing equipment for other businesses is a supplier in this market, not a plant that consumes \
tools for its own internal operations — the two are structurally different, don't conflate them just because \
the reseller might theoretically use a torque wrench in its own shop somewhere.
- If a business instead PERFORMS bolted-joint, onsite-machining, hot-tapping, or pipeline-integrity WORK for \
other companies' plants/pipelines — using tools it must procure from somewhere (shutdown/turnaround \
contractors, onsite machining service shops, hot-tap service companies) — that IS a genuine client. They are a \
tool/rental/service prospect regardless of any secondary services-market overlap with Tritorc.
- "End-User Plant/Operator" means a company that owns/operates physical industrial infrastructure — a \
refinery, chemical plant, wind farm, steel mill — and needs tools for its own facility's upkeep. It does NOT \
mean any company that happens to touch hydraulics/machinery as part of a supplier/distributor business model.
- EPC contractors and construction firms doing their own industrial builds are also genuine clients.

TARGET CLIENT PROFILE — by industry:
- Oil & Gas: pipeline operators, refineries, petrochemical plants, and the shutdown/turnaround maintenance \
contractors who service them — need leak-free flanged joints, heat exchanger servicing, hot tapping, leak \
sealing.
- Wind Energy: wind farm operators and turbine maintenance contractors — foundation bolting, turbine \
component bolting, bearing maintenance.
- Infrastructure: EPC/construction contractors on major structural projects (bridges, heavy structures) \
needing bolting under dynamic load and constant vibration.
- Fertilizer / Chemical: fertilizer and chemical plants needing leak-free joints and heat-exchanger work.
- Steel: steel mills/production facilities needing vibration-resistant bolting on furnace and rolling \
equipment.

WHAT DOES NOT COUNT — be strict here, this is the main source of bad leads:
- Manufacturers or resellers/rental houses of the same tool categories Tritorc sells (see the key test above) \
— these are competitors/suppliers, not clients, no matter how topically relevant they look.
- Generic bolt/nut/fastener manufacturers, wholesalers, or hardware stores selling bolts as commodity \
hardware, with no hydraulic tooling or specialized bolting-service angle — NOT a match, even though "bolt" is \
literally their product.
- General building/civil contractors, renovation firms, telecom/utility resellers, or facilities-maintenance \
companies with no specific pressure-equipment, pipeline, turbine, or heat-exchanger work — NOT a match.
- A business whose homepage mentions an on-topic-sounding word (torque, bolt, flange, hydraulic) only \
coincidentally — in its company name, in an unrelated electrical "voltage" context, or as a generic \
machine-shop offering with no bolting/pipeline focus — NOT a match.
- Any business outside industrial/energy/infrastructure work entirely (retail, food, real estate, generic \
consumer services) — NOT a match.

You will be given a business's name, address, the search phrase that surfaced it, and text scraped from its \
homepage (in whatever language it's written in — read it directly, do not ask for translation, and note that \
homepage text may be sparse or missing). Decide: is this business genuinely a CLIENT per the key test above — \
not just a competitor/supplier that happens to share the same keywords. If homepage text is missing or the \
site was unreachable, you may still judge from the name/address/search phrase, but your reason must say \
plainly that this is an unverified guess with no site content to confirm it.

Also classify the business's own industry vertical — the sector it operates in, not Tritorc's. Prefer one of: \
"Oil and gas", "Wind energy", "Power", "Heavy engineering", "Turbine manufacturing", "Fertilizer/Chemical", \
"Steel". If none fit and there's a clear alternative from the homepage text, name it briefly (2-4 words); if \
there's not enough evidence to tell, use "Unknown".

Respond with a JSON object only, no other text, in this exact shape:
{"aligned": true or false, "customer_type": "EPC Contractor" | "End-User Plant/Operator" | \
"Shutdown/Turnaround Maintenance Contractor" | "Competitor/Supplier (not a client)" | "Irrelevant", \
"industry_sector": "the business's own industry vertical, per the guidance above", \
"reason": "one sentence explaining why, citing the specific evidence, and noting if this is an unverified \
guess with no website content"}"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "aligned": {"type": "boolean"},
        "customer_type": {
            "type": "string",
            "enum": [
                "EPC Contractor",
                "End-User Plant/Operator",
                "Shutdown/Turnaround Maintenance Contractor",
                "Competitor/Supplier (not a client)",
                "Irrelevant",
            ],
        },
        "industry_sector": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["aligned", "customer_type", "industry_sector", "reason"],
}

VALID_CUSTOMER_TYPES = set(_RESPONSE_SCHEMA["properties"]["customer_type"]["enum"])

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if not settings.gemini_api_key:
        return None
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


def _build_user_content(name: str, address: str, website_text: str, matched_keyword: str) -> str:
    homepage_section = website_text[:3000].strip() or "(no website content available — judge from name/address/search phrase alone)"
    return (
        f"Business name: {name}\n"
        f"Address: {address}\n"
        f"Matched search phrase: {matched_keyword}\n"
        f"Homepage text (any language):\n{homepage_section}"
    )


async def score_relevance(name: str, address: str, website_text: str, matched_keyword: str) -> dict | None:
    """Ask Gemini whether this business is plausibly a Tritorc lead, based on
    its own homepage text in whatever language it's written in. Returns None
    if no key is configured or the call fails — callers should treat None as
    "couldn't verify"."""
    client = _get_gemini_client()
    if client is None:
        return None

    user_content = _build_user_content(name, address, website_text, matched_keyword)

    try:
        interaction = client.interactions.create(
            model=GEMINI_MODEL,
            system_instruction=TRITORC_SYSTEM_PROMPT,
            input=user_content,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _RESPONSE_SCHEMA,
            },
        )
        data = json.loads(interaction.output_text)
        await record_llm_call("gemini", success=True)

        customer_type = data.get("customer_type", "Unknown")
        aligned = bool(data.get("aligned"))
        # Defensive consistency check: the model occasionally says aligned=true
        # while still picking a non-client customer_type. customer_type is the
        # more specific judgment, so it wins.
        if customer_type in ("Competitor/Supplier (not a client)", "Irrelevant"):
            aligned = False
        return {
            "aligned": aligned,
            "customer_type": customer_type,
            "industry_sector": data.get("industry_sector") or "Unknown",
            "reason": data.get("reason", ""),
        }
    except Exception as e:
        await record_llm_call("gemini", success=False, error_message=str(e))
        await log_error(search_id=None, stage="relevance_llm", place_id=None, error_message=str(e))
        return None
