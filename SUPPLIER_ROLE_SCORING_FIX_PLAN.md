# Implemented Fix: Turn Crawler From Industrial-Relevance Detector Into Tritorc-Buyer Detector

## Status

Implemented.

Active versions:

```text
CRAWL_VERSION = tritorc-crawl-v3
SCORING_VERSION = role-concept-score-v1
```

Latest audit report:

[crawl_audit_argentina_aug3_role_v2.json](C:/Users/VP89/Desktop/Lead_discovery/data/audit/crawl_audit_argentina_aug3_role_v2.json)

Latest Argentina result:

```text
Strong: 1
Weak: 1
Reject: 37
Unknown: 12
```

Confirmed behavior:

- `Swagelok Argentina - Flusitec S.A.` is rejected as `supplier_distributor`.
- `BINNING OIL TOOLS S.A.` is rejected as `supplier_distributor`.
- `Morken Group` remains `strong` as `industrial_service_contractor`.
- `Quintana WellPro` remains `weak` as `industrial_service_contractor`.

## Problem found in Argentina audit

The new crawler is rejecting many unrelated businesses, but it still promotes industrial suppliers/distributors as good leads.

Example failure:

- `Swagelok Argentina - Flusitec S.A.` scored `best`
- Reason: site contains oil & gas / refinery / pipeline integrity terms
- Actual issue: Swagelok is more likely a supplier/distributor, not a Tritorc buyer

So the scoring is currently answering:

> Is this business industrially related?

But we need it to answer:

> Is this business likely to buy/use Tritorc tools or services?

## Implemented strategy

Add a separate `business_role` layer before final tiering.

The crawler should classify each company as one of:

- `end_user_operator`
- `industrial_service_contractor`
- `epc_contractor`
- `supplier_distributor`
- `competitor_manufacturer`
- `generic_local_service`
- `unknown`

Then final tier should depend on both:

1. Tritorc-fit technical concepts
2. Business role

## Scoring rule change

### Qualify higher

Promote only if there is evidence of buyer/operator/contractor role:

- owns/operates refinery, plant, pipeline, terminal, wind farm, steel mill
- performs maintenance, shutdown, turnaround, hydrotesting, hot tapping, leak sealing, retubing
- EPC/industrial construction for process/heavy industry

### Penalize or reject

Demote if business model is mainly:

- supplier
- distributor
- authorized distributor
- reseller
- catalog/product seller
- valve/fitting/hose/fastener seller
- hydraulic tool seller/rental house
- CNC/machine tool seller
- competitor manufacturer

### Implemented tier logic

| Technical fit | Business role | Final tier |
|---|---|---|
| high | end-user/operator | best/strong |
| high | industrial service contractor | best/strong |
| high | EPC contractor | strong |
| high | supplier/distributor | reject |
| high | competitor manufacturer | reject |
| low | any supplier/generic role | reject |
| unreachable website | no strong metadata | unknown |

## Google search fix

Remove/avoid supplier-style keywords:

- hydraulic torque wrench supplier
- hydraulic bolt tensioner supplier
- flange facing machine
- tube expander
- controlled bolting as standalone

Use buyer/service/operator searches instead:

English:

- refinery maintenance contractor
- petrochemical plant maintenance contractor
- pipeline integrity services
- pipeline maintenance contractor
- hydrostatic testing pipeline contractor
- hot tapping contractor
- industrial shutdown contractor
- turnaround maintenance contractor
- oil gas maintenance contractor
- chemical plant maintenance contractor
- fertilizer plant maintenance contractor
- power plant maintenance contractor
- steel plant maintenance contractor
- industrial EPC contractor

Spanish for Argentina/LatAm:

- contratista mantenimiento refinería
- mantenimiento planta petroquímica
- servicios integridad de ductos
- mantenimiento de ductos
- prueba hidrostática ductos
- servicio hot tapping
- contratista parada de planta
- mantenimiento industrial petróleo y gas
- mantenimiento planta química
- contratista EPC industrial

## Data model additions implemented

Fields added to master businesses:

- `business_role`
- `business_role_score`
- `business_role_signals`
- `business_role_negative_signals`
- `business_role_reason`

Optional future:

- `manual_review_status`
- `manual_review_label`
- `manual_review_notes`

## UI changes implemented

Show role beside crawl tier:

- Crawl Tier
- Crawl Score
- Business Role
- Role Reason
- Positive Concepts
- Negative Concepts

Added filters:

- All
- Best
- Strong
- Weak
- Reject
- Unknown
- Supplier/Distributor
- End-user/Operator
- Service Contractor
- EPC Contractor

## Export changes implemented

Include:

- Business Role
- Business Role Score
- Business Role Signals
- Business Role Negative Signals
- Business Role Reason

## Test plan and result

Use Argentina Aug 3 as the first regression set.

Expected improvements:

- Swagelok should no longer be `best`; should be `reject`
- valve/tool/hose/fastener distributors should be demoted
- Morken Group should remain `strong`
- generic construction/facility businesses should remain `reject`
- unreachable sites should remain `unknown`

Acceptance target for this pass:

- At least 70% of obvious suppliers/distributors demoted to `weak` or `reject`
- No generic local/residential services in `best` or `strong`
- Service contractors like Morken remain `strong`

Result:

```text
Accepted.

No businesses were scored as best in the Argentina regression set.
Only Morken Group remained strong.
Only Quintana WellPro remained weak.
Known suppliers/competitors were rejected.
```

## Implementation order completed

1. Added role concept dictionaries in crawler config.
2. Extended crawler scorer to classify `business_role`.
3. Updated final tier logic to use role + technical score.
4. Added schema/export/index fields.
5. Added UI columns and filters.
6. Re-ran Argentina audit.
7. Tuned supplier-signal precedence so real service contractors survive.

## Not included in this pass

- No active LLM fallback
- No paid Google API calls
- No database overwrite unless explicitly approved after audit
- No multilingual expansion beyond the current dictionary languages
