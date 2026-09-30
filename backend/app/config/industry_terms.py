"""Maps the crawler's already-detected Tritorc-relevance concepts (from
app.config.crawl_concepts) to a real industry vertical, computed from actual
crawled site content -- not the business name/search-keyword substring match
that caused the old "Bolting" (a telecom company) misclassification bug.
Reuses the existing multilingual concept detection instead of re-scanning
page text with a second keyword list, so industry_type can never disagree
with matched_domain_concepts.
"""

from __future__ import annotations

# Checked in order -- first matching bucket wins when a site's content spans
# more than one vertical (e.g. an EPC contractor mentioning several sectors
# it has built for).
INDUSTRY_BUCKETS: list[tuple[str, set[str]]] = [
    ("oil_and_gas", {"oil_gas", "refinery", "petrochemical", "lng", "fpso"}),
    ("pipeline", {"pipeline_integrity", "pipeline_maintenance", "line_stopping"}),
    ("power_and_energy", {"power_plant", "nuclear"}),
    ("wind_energy", {"wind_turbine"}),
    ("steel_and_heavy_industry", {"steel_plant", "cement_plant", "structural_bolting"}),
    ("chemical_and_fertilizer", {"fertilizer_plant", "grain_elevator"}),
    ("mining", {"mining"}),
    ("marine_and_shipyard", {"shipyard"}),
    ("epc_construction", {"epc"}),
]


def industry_type_from_concepts(positive_concepts: list[str]) -> str:
    concept_set = set(positive_concepts)
    for label, concepts in INDUSTRY_BUCKETS:
        if concept_set & concepts:
            return label
    return "unknown"
