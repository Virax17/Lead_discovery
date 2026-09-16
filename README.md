# LeadDiscovery

LeadDiscovery is a FastAPI + React application for finding potential Tritorc cold-mail leads from Google Places, crawling their websites, scoring their fit, and exporting qualified businesses.

The current goal is not generic industrial company discovery. The app should find businesses that are likely to buy or use Tritorc products/services, while excluding competitors, suppliers, distributors, and unrelated local businesses.

## Current lead-quality logic

The active crawler/scorer version is:

```text
CRAWL_VERSION = tritorc-crawl-v3
SCORING_VERSION = role-concept-score-v1
```

The pipeline is:

```text
Google Places candidates
-> website crawl with Crawlee
-> language detection
-> multilingual concept matching
-> business-role classification
-> final tier: best / strong / weak / reject / unknown
-> UI filters and export
```

## What counts as a good Tritorc lead

Good leads are businesses that likely need controlled bolting, onsite machining, pipeline/process integrity, hot tapping, hydrotesting, leak sealing, heat-exchanger work, shutdown/turnaround support, or industrial maintenance.

Preferred roles:

- `end_user_operator`
- `industrial_service_contractor`
- `epc_contractor`

Examples:

- refinery / petrochemical / chemical / fertilizer plant operators
- pipeline operators
- shutdown or turnaround maintenance contractors
- oil & gas field-service contractors
- hot tapping / hydrotesting / pipeline integrity service companies
- industrial EPC contractors
- power, steel, wind, and heavy-industry maintenance targets

## What should be excluded

The app now classifies and rejects:

- `supplier_distributor`
- `competitor_manufacturer`
- `generic_local_service`

Examples to exclude:

- hydraulic torque wrench sellers
- bolt tensioner sellers
- flange-facing / pipe-cutting machine sellers
- industrial tool rental/sales companies
- authorized distributors of competing tool brands
- valve, fitting, hose, fastener, hardware, and machine-tool sellers
- generic building maintenance, HVAC, residential construction, renovation, restaurants, schools, real estate, etc.

Important distinction:

```text
Service contractor using tools = possible lead
Company selling/renting competing tools = reject
End-user plant/operator = good lead
```

## Main features

- Google Places search by country/state/city.
- Buyer-focused default keywords.
- Crawlee-based website crawling.
- Multilingual concept scoring for English, Spanish, French, Portuguese, and German.
- Business-role scoring to reject suppliers/competitors.
- Tier filters: Best, Strong, Weak, Reject, Unknown.
- Role filters: End-user, Service Contractor, EPC, Supplier/Distributor, Competitor, Generic Service, Unknown.
- Master database with deduplication by Google `place_id`.
- CSV/XLSX exports with crawler evidence, role reason, query source, language, and score.
- User login, JWT auth, credit limits, and admin portal.
- Google Places API quota tracking.
- Optional LLM fallback fields are implemented but disabled by default.

## Important implementation docs

- [Current implementation status](C:/Users/VP89/Desktop/Lead_discovery/IMPLEMENTATION_STATUS.md)
- [Supplier/role scoring fix plan](C:/Users/VP89/Desktop/Lead_discovery/SUPPLIER_ROLE_SCORING_FIX_PLAN.md)
- [Multilingual crawler plan](C:/Users/VP89/Desktop/Lead_discovery/MULTILINGUAL_CRAWLER_PLAN.md)
- [Deployment guide](C:/Users/VP89/Desktop/Lead_discovery/DEPLOYMENT.md)

## Project structure

```text
Lead_discovery/
|-- backend/
|   |-- app/
|   |   |-- api/
|   |   |-- config/
|   |   |-- db/
|   |   |-- models/
|   |   `-- services/
|   |-- scripts/
|   |-- requirements.txt
|   |-- run_backend.ps1
|   `-- run_backend.bat
|-- frontend/
|   |-- src/
|   |-- package.json
|   `-- vite.config.js
|-- data/audit/
|-- DEPLOYMENT.md
|-- IMPLEMENTATION_STATUS.md
|-- MULTILINGUAL_CRAWLER_PLAN.md
|-- SUPPLIER_ROLE_SCORING_FIX_PLAN.md
`-- README.md
```

## Local setup

### Backend

From PowerShell:

```powershell
cd C:\Users\VP89\Desktop\Lead_discovery\backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

If you use port `8001`, make sure the frontend `VITE_API_BASE` or Vite proxy also points to `8001`.

Backend URLs:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/api
```

### Frontend

Open a second PowerShell:

```powershell
cd C:\Users\VP89\Desktop\Lead_discovery\frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://127.0.0.1:5173/
```

If ports `5173` or `5174` are busy, Vite will automatically choose another port.

## Environment variables

Backend `.env`:

```env
GOOGLE_PLACES_API_KEY=your-google-places-api-key
MONGO_URI=your-mongodb-atlas-uri-or-local-mongodb-uri
MONGO_DB_NAME=lead_discovery
APP_SECRET_KEY=replace-with-a-long-random-secret

BOOTSTRAP_ADMIN_USERNAME=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=choose-a-strong-password
BOOTSTRAP_ADMIN_CREDIT_LIMIT=1000

BOOTSTRAP_USER_USERNAME=test@example.com
BOOTSTRAP_USER_PASSWORD=choose-a-test-password
BOOTSTRAP_USER_CREDIT_LIMIT=1000

CORS_ALLOWED_ORIGINS=

GEMINI_API_KEY=your-google-ai-studio-gemini-api-key

LLM_FALLBACK_ENABLED=false
LLM_FALLBACK_MIN_SCORE=40
LLM_FALLBACK_MAX_SCORE=69
LLM_FALLBACK_MAX_CALLS_PER_SEARCH=50
LLM_FALLBACK_MAX_CALLS_PER_MONTH=1000
```

Keep real `.env` files private.

## Useful validation commands

Backend:

```powershell
cd C:\Users\VP89\Desktop\Lead_discovery\backend
.\venv\Scripts\python.exe -m compileall -q app scripts
.\venv\Scripts\python.exe -c "import app.main; print('backend import ok')"
```

Frontend:

```powershell
cd C:\Users\VP89\Desktop\Lead_discovery\frontend
npm run build
```

Argentina audit:

```powershell
cd C:\Users\VP89\Desktop\Lead_discovery\backend
.\venv\Scripts\python.exe scripts\audit_crawl_snapshot.py --country Argentina --limit 52 --max-pages 2 --output ../data/audit/crawl_audit_argentina_aug3_role_v2.json
```

## Latest Argentina audit result

Using the Aug 3 Argentina dataset with the role-aware crawler:

```text
Strong: 1
Weak: 1
Reject: 37
Unknown: 12
```

Key expected behavior:

- `Swagelok Argentina` is rejected as `supplier_distributor`.
- `BINNING OIL TOOLS` is rejected as `supplier_distributor`.
- `Morken Group` remains `strong`.
- `Quintana WellPro` remains `weak`.

Report:

[crawl_audit_argentina_aug3_role_v2.json](C:/Users/VP89/Desktop/Lead_discovery/data/audit/crawl_audit_argentina_aug3_role_v2.json)

## Team workflow rule

Before future coding or new project work:

1. Create or update a research/implementation `.md` plan first.
2. Use higher-model reasoning for planning when available.
3. Wait for approval.
4. Then implement, validate, and update docs.

This rule exists because crawler/search quality changes can easily create false positives or burn API quota.

