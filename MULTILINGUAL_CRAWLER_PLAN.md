# Multilingual Crawler And LLM Fallback Plan

## Current status

Partially implemented.

Active versions:

```text
CRAWL_VERSION = tritorc-crawl-v3
SCORING_VERSION = role-concept-score-v1
```

Implemented:

- Crawlee BeautifulSoup crawler.
- HTTP fallback crawler.
- Lightweight language detection with `lingua-language-detector`.
- Concept dictionaries for English, Spanish, French, Portuguese, and German.
- Localized Google query terms for selected countries.
- DB fields for language, concepts, evidence, and LLM fallback status.
- UI/export fields for language, concepts, crawler tier, and evidence.
- Business-role scoring to exclude suppliers and competitors.
- Optional LLM fallback service is present but disabled by default.

Still future work:

- Evidence snippet translation.
- Larger language coverage beyond the current five languages.
- Manual gold test sets by country/language.
- LLM fallback calibration on reviewed borderline cases.
- Batch-level crawler timeout/progress policy for slow/dead websites.

## Goal

Make LeadDiscovery work for global scraping without depending on English-only website text or broad Google queries.

The target flow should be:

```text
Google Places candidates
-> website crawl
-> language detection
-> multilingual concept extraction
-> rule-based score/tier
-> optional LLM fallback only for borderline/unclear cases
-> UI shows tier, score, language, evidence, and reason
```

The crawler should still show all businesses after a search, but let users filter/export:

```text
Best / Strong / Weak / Reject / Unknown / Role / LLM Reviewed
```

## What We Are Missing Today

1. English-only evidence matching

   The current crawler can score English websites, but Spanish, French, Portuguese, German, Arabic, Hindi, etc. often become `unknown` even when they are relevant.

2. English-only Google search intent

   If we search Spain, France, Brazil, Germany, or Saudi Arabia with only English phrases, Google may return poor or sparse local results. Global scraping needs localized Google query variants too.

3. No language field in DB

   We should store detected language and scoring language, otherwise we cannot audit why a country performs poorly.

4. No concept layer

   Raw phrases like `shutdown`, `parada de planta`, and `arrêt technique` should map to the same internal concept: `shutdown_turnaround`.

   Status: implemented for the current supported languages.

5. No evidence translation layer

   Users may need evidence shown in English, but translating whole pages is expensive. Translate only the matched snippets.

6. No per-country quality benchmark

   We need sample sets by region/language before claiming accuracy.

7. No LLM fallback policy

   If LLM is used, it should be used only for borderline cases, not every business.

   Status: policy and fields exist; fallback is disabled by default.

8. Supplier/competitor distinction

   Industrial relevance alone was not enough. The Argentina audit showed suppliers/distributors being promoted. The v3 crawler now adds `business_role` scoring and rejects suppliers/competitors by default.

## Recommended Architecture

### 1. Language Detection

Use one lightweight detector:

```text
lingua-language-detector
```

Why:

```text
works offline
supports many languages
good for short text snippets
no API cost
```

Store:

```text
detected_language: "en" | "es" | "fr" | "pt" | "de" | ...
language_confidence: 0.0-1.0
```

Fallback:

```text
If confidence is low, use website html lang attribute, country, and Google result locale as hints.
```

### 2. Concept Dictionaries

Do not score raw words directly across languages. Score concepts.

Example:

```json
{
  "shutdown_turnaround": {
    "weight": 18,
    "phrases": {
      "en": ["shutdown", "turnaround", "plant shutdown"],
      "es": ["parada de planta", "mantenimiento de parada"],
      "fr": ["arrêt technique", "arrêt de maintenance"],
      "pt": ["parada de manutenção", "parada de planta"]
    }
  }
}
```

Suggested concept groups:

```text
controlled_bolting
bolt_tensioning
flange_management
flange_facing
onsite_machining
hot_tapping
pipeline_integrity
pipeline_maintenance
hydrotesting
leak_sealing
heat_exchanger
retubing
industrial_shutdown
oil_gas
refinery
petrochemical
chemical_plant
fertilizer_plant
power_plant
steel_plant
wind_turbine
epc
industrial_maintenance
pressure_vessel
```

Negative concept groups:

```text
residential_construction
roofing
remodeling
hvac
plumbing
retail
restaurant
school
real_estate
hotel
clinic
hardware_store
tool_distributor
fastener_supplier
equipment_dealer
```

### 3. Localized Google Queries

For each country/language, generate query variants in the likely local language.

Example for Spanish:

```text
contratista mantenimiento refinería en {location}
servicios integridad de ductos en {location}
mecanizado in situ industrial en {location}
contratista parada de planta en {location}
```

Example for French:

```text
maintenance industrielle raffinerie à {location}
services intégrité pipeline à {location}
usinage sur site industriel à {location}
arrêt technique industriel à {location}
```

Keep English queries too in countries where English is common for industrial websites.

Store the exact query:

```text
source_query
source_query_language
source_keyword
```

This is required for auditing bad result sources.

### 4. Crawler Extraction

Crawler should collect:

```text
html lang
page title
meta description
body text
same-domain service/industry/about pages
matched snippets
page URL for each snippet
```

Preferred paths should also be multilingual later:

```text
/services
/industries
/about
/oil-gas
/pipeline
/maintenance
/servicios
/industrias
/sobre-nosotros
/services
/industries
/a-propos
/servicos
/industrias
/sobre
```

### 5. Scoring

Score concepts, not phrases.

Example:

```text
pipeline_integrity: +20
controlled_bolting: +20
onsite_machining: +18
hot_tapping: +18
shutdown_turnaround: +18
refinery: +16
petrochemical: +16
oil_gas: +14
industrial_maintenance: +12
```

Negative examples:

```text
plumbing: -30
roofing: -28
remodeling: -28
school: -28
restaurant: -35
real_estate: -30
tool_distributor: -18
fastener_supplier: -18
```

Tier rules:

```text
Best: 85-100, multiple strong concepts, no serious negative signal
Strong: 70-84, clear industrial fit
Weak: 40-69, plausible but not enough evidence
Reject: 0-39, irrelevant or negative evidence dominates
Unknown: no crawlable content or unsupported language
```

### 5b. Business-role scoring

Implemented in `tritorc-crawl-v3`.

The scorer classifies each business into:

```text
end_user_operator
industrial_service_contractor
epc_contractor
supplier_distributor
competitor_manufacturer
generic_local_service
unknown
```

Competitors and suppliers are excluded by default, even if their websites mention oil & gas, refinery, pipeline, bolting, or flange terms.

This prevents false positives such as industrial distributors, valve sellers, hydraulic tool sellers, and competitor tool/rental companies.

### 6. Evidence Translation

Do not translate whole pages by default.

Translate only:

```text
top 3-5 matched snippets
crawl reason
optional user-visible explanation
```

Store both:

```text
crawl_evidence_original
crawl_evidence_translated
```

This keeps cost low and preserves the original evidence for audit.

## LLM Fallback

LLM should not run for every candidate.

Use LLM only when:

```text
crawl_tier = weak
crawl_score is between 40 and 69
crawl_tier = unknown but Google metadata/query looks industrial
positive and negative concepts conflict
detected language is unsupported
website crawl failed but company name/query strongly suggests industrial fit
```

Do not use LLM when:

```text
crawl_tier = best
crawl_tier = strong
crawl_tier = reject with strong negative Google type
no website and no industrial Google metadata
```

### LLM Prompt Inputs

Send only compact evidence:

```text
company name
address
country
detected language
Google types / primary type
source query
matched positive concepts
matched negative concepts
top original snippets
translated snippets if available
```

Do not send entire crawled pages unless needed.

### LLM Output Schema

```json
{
  "llm_decision": "accept" | "reject" | "manual_review",
  "llm_tier": "best" | "strong" | "weak" | "reject" | "unknown",
  "llm_confidence": 0,
  "customer_type": "End-User Plant/Operator",
  "industry_sector": "Oil and gas",
  "reason": "Short evidence-based reason",
  "evidence_used": ["snippet or concept"],
  "risk_flags": ["possible supplier", "thin website", "translation uncertainty"]
}
```

### LLM Budget Controls

Add settings:

```text
LLM_FALLBACK_ENABLED=false
LLM_FALLBACK_MIN_SCORE=40
LLM_FALLBACK_MAX_SCORE=69
LLM_FALLBACK_MAX_CALLS_PER_SEARCH=50
LLM_FALLBACK_MAX_CALLS_PER_MONTH=1000
```

Store:

```text
llm_fallback_status
llm_fallback_provider
llm_fallback_model
llm_fallback_confidence
llm_fallback_reason
llm_fallback_checked_at
```

Cache by:

```text
place_id
crawl_version
scoring_version
llm_prompt_version
```

## DB Fields To Add Later

```text
detected_language
language_confidence
source_query_language
scoring_language
matched_concepts
positive_concepts
negative_concepts
crawl_evidence_original
crawl_evidence_translated
crawl_evidence_urls
translation_status
translation_provider
translation_checked_at
llm_fallback_status
llm_fallback_provider
llm_fallback_model
llm_fallback_decision
llm_fallback_confidence
llm_fallback_reason
llm_fallback_checked_at
scoring_version
business_role
business_role_score
business_role_signals
business_role_negative_signals
business_role_reason
```

Status: these fields are now implemented.

## Rollout Plan

### Phase 1: English Baseline

Already started.

Goals:

```text
English crawler stable
English scoring tuned
Best/Strong/Weak/Reject/Unknown UI works
Exports by tier work
Old English data audit works
```

### Phase 2: Language Detection

Add language detection to crawled text and DB.

Do not change scoring yet.

Output:

```text
country -> detected language distribution
unknown rate by language
```

### Phase 3: Concept Dictionary System

Move English signals into concept JSON/YAML files.

Then add Spanish/French/Portuguese phrase dictionaries.

Output:

```text
matched_concepts instead of raw matched phrases
```

Status: implemented in Python config dictionaries.

### Phase 4: Localized Google Queries

Generate localized query sets by country/language.

Track:

```text
source_query
source_query_language
results per query
reject rate per query
strong rate per query
```

### Phase 5: Snippet Translation

Translate only matched snippets for display/export.

Keep original snippets in DB.

### Phase 6: LLM Borderline Fallback

Enable LLM fallback only for weak/unknown/conflicting cases.

Keep it off by default until audit proves the rule-based layer is stable.

Status: service and fields exist; default remains off.

### Phase 6b: Supplier/Competitor Exclusion

Status: implemented as `role-concept-score-v1`.

Regression result on Argentina Aug 3:

```text
Strong: 1
Weak: 1
Reject: 37
Unknown: 12
```

### Phase 7: Accuracy Audit

For each major language/country, manually review samples:

```text
50 Best/Strong
50 Weak
50 Reject
50 Unknown
```

Track:

```text
precision for Best/Strong
false reject rate
unknown rate
LLM correction rate
cost per useful lead
```

## Accuracy Expectations

Early English-only:

```text
Best/Strong precision: 70-85%
Weak: manual review
Reject precision: 70-90%
```

After multilingual concepts and localized queries:

```text
Best/Strong precision: 80-90%
Unknown rate should drop significantly in supported languages
```

With LLM fallback for borderline cases:

```text
Best/Strong precision: 85-93%
Lower false rejects on non-English and thin websites
Higher cost, but controlled by fallback budgets
```

These are estimates until we build reviewed test sets.

## Important Risks

1. Local language ambiguity

   Industrial terms can overlap with unrelated sectors. Example: tension/tensioning can mean electrical voltage in some languages.

2. Translation can hide nuance

   Use original snippets as source of truth; translated snippets are for user display.

3. Country language is not always website language

   Global industrial companies often publish English pages even in non-English countries.

4. Supplier vs client distinction is hard

   Tool distributors and fastener suppliers must stay negative unless they also clearly operate plants or perform industrial service work.

5. JavaScript-heavy sites

   Crawlee BeautifulSoup/HTTP may miss content. Playwright should remain optional for selected failed/high-potential records only.

6. EC2 capacity

   The deployed backend is on `t3.micro`; keep concurrency low and avoid full browser crawling by default.

7. Legal/polite crawling

   Keep same-domain limits, request timeouts, low concurrency, and avoid aggressive recrawling.

## Recommendation

Build multilingual support as a concept-extraction system, not as full-page translation.

Use LLM only as a budgeted fallback for borderline/unknown/conflicting cases. This keeps global accuracy high without making every search expensive or slow.
