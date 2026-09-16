# LeadDiscovery Implementation Status

Last updated after the supplier/competitor exclusion implementation.

## Current active crawler

```text
CRAWL_VERSION = tritorc-crawl-v3
SCORING_VERSION = role-concept-score-v1
```

## Current discovery architecture

```text
Google Places search
-> deduplicate by place_id
-> crawl website with Crawlee BeautifulSoup
-> fallback HTTP crawl if Crawlee returns no pages
-> detect language with lingua-language-detector
-> match multilingual technical concepts
-> classify business role
-> assign tier
-> store result in MongoDB
-> display/filter/export from frontend
```

## Implemented

### Google search improvements

- Buyer-focused default search keywords.
- Removed supplier-style keyword defaults from the main search set.
- Stores `source_query`, `source_keyword`, and `source_query_language` for new searches.
- Localized query support for selected countries/languages.

### Website crawler

- Crawlee BeautifulSoup crawler added.
- Same-domain crawl with preferred service/industry/about pages.
- HTTP fallback crawler added.
- Fast navigation timeout added for dead/slow sites.
- Stable Crawlee storage directory configured.

### Multilingual scoring

Supported concept dictionaries:

- English
- Spanish
- French
- Portuguese
- German

Stores:

- `detected_language`
- `language_confidence`
- `scoring_language`
- `matched_concepts`
- `positive_concepts`
- `negative_concepts`
- `scoring_version`

### Business-role scoring

Implemented roles:

- `end_user_operator`
- `industrial_service_contractor`
- `epc_contractor`
- `supplier_distributor`
- `competitor_manufacturer`
- `generic_local_service`
- `unknown`

Competitors and suppliers are rejected by default.

Service contractor/operator/EPC evidence can qualify a business if the technical concepts also fit Tritorc.

Stores:

- `business_role`
- `business_role_score`
- `business_role_signals`
- `business_role_negative_signals`
- `business_role_reason`

### UI and exports

Results and Master Database now show:

- Crawl Tier
- Crawl Score
- Crawl Reason
- Crawl Evidence
- Detected Language
- Positive Concepts
- Negative Concepts
- Business Role
- Role Reason
- LLM Fallback Status
- Source Query
- Source Query Language

Filters:

- Tier filters
- Role filters

Exports include crawler, language, concept, and business-role fields.

### LLM fallback

The data fields and gated fallback service exist, but LLM fallback is disabled by default.

Default:

```text
LLM_FALLBACK_ENABLED=false
```

It should only be enabled later for borderline cases after rule-based quality is stable.

## Latest Argentina audit

Input:

```text
Aug 3 Argentina search snapshot
51 scored records
```

Report:

[crawl_audit_argentina_aug3_role_v2.json](C:/Users/VP89/Desktop/Lead_discovery/data/audit/crawl_audit_argentina_aug3_role_v2.json)

Result:

```text
Strong: 1
Weak: 1
Reject: 37
Unknown: 12
```

Important checks:

- `Swagelok Argentina` is rejected as `supplier_distributor`.
- `BINNING OIL TOOLS` is rejected as `supplier_distributor`.
- `Morken Group` remains `strong` as `industrial_service_contractor`.
- `Quintana WellPro` remains `weak` as `industrial_service_contractor`.

## Known issues / next plans

### 1. Google API quota is exhausted

Current monthly limit:

```text
1000 / 1000
```

New searches are blocked while paid overage is off.

### 2. Old data lacks full metadata

Older records often have:

- no `source_query`
- no Google type fields
- no crawl version
- no role fields

They must be re-crawled/re-scored under `tritorc-crawl-v3`.

### 3. Dead websites slow audits

Many old sites are dead, blocked, or slow. The crawler now has a shorter navigation timeout, but a future approved plan should add a batch-level per-record timeout and better progress logging.

### 4. Need manually labeled gold set

Before claiming high accuracy, create a manually reviewed test set:

- 50 likely good leads
- 50 suppliers/competitors
- 50 generic rejects
- 50 unknown/unreachable

Use that set for regression tests.

### 5. Search query strategy still matters most

Crawler can reject bad results, but Google query quality determines how many useful candidates enter the funnel.

Avoid supplier/product queries. Prefer operator/service/buyer queries.

## Workflow rule

Before future coding or new project work:

1. Create or update a research/implementation `.md` plan.
2. Get approval.
3. Implement.
4. Validate.
5. Update docs.

