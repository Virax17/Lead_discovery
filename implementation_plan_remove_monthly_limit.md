# Remove Local 1,000-Request Monthly Limit

## Goal

Remove the application's global 1,000 Google Places requests-per-month blocking rule. Google Cloud remains responsible for billing, free-tier accounting, project quotas, and rate limiting.

## Current behavior

- `backend/app/config/quota.py` defines a 1,000-call monthly limit and an 800-call warning threshold.
- `backend/app/services/quota_tracker.py` blocks Google Places calls at that limit unless `allow_paid_overage` is enabled.
- The dashboard predicts whether a search will exceed 1,000 and prevents submission.
- The application header and admin screen display usage as `used / 1,000`.
- Per-user credit limits and Google HTTP 429 handling are separate controls.

## Proposed implementation

1. Remove the global monthly-limit and warning checks from `quota_tracker.py`.
2. Continue recording monthly and per-user request counts for visibility.
3. Preserve per-user credit limits; users with an explicitly configured limit will still be blocked at that limit.
4. Preserve Google Places 429 handling and retry behavior.
5. Return unlimited/global-monitoring semantics from the quota API (no remaining-call or block threshold).
6. Update the dashboard, application header, and admin usage display so they show calls used without `/ 1,000`, projected-overage warnings, or local global blocking.
7. Remove or retire the obsolete fixed-price overage estimate, because actual Google charges vary by SKU and billing country.
8. Update `DEPLOYMENT.md` to state that Google Cloud quotas/budgets govern global usage and that application-level per-user limits remain available.

## Verification

- Backend: confirm calls above 1,000 return `OK` unless an explicit per-user limit is exceeded.
- Backend: confirm monthly usage counters still increment.
- Backend: confirm a configured per-user credit limit still blocks calls.
- Frontend: run the production build and confirm no UI logic assumes a 1,000-call ceiling.
- Search flow: confirm Google 429 responses still stop the search safely.

## Operational caution

Removing this limit permits Google Maps charges after the applicable free allowance and trial credit are exhausted. Google Cloud budget alerts do not normally stop API usage; a Google API quota is needed for a hard provider-side cap.
