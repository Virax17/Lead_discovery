# LeadDiscovery

LeadDiscovery is a FastAPI + React application that finds sales leads for Tritorc — a manufacturer of hydraulic torque wrenches, bolt tensioners, flange-facing/onsite-machining tools, and pipeline-integrity equipment. It searches Google Places for businesses in a given country/state/city (or a country-wide automatic sweep, or a custom area drawn on a map), crawls each business's website, scores how well it actually fits Tritorc's buyer profile, and exports a clean, deduplicated list of qualified companies with contact details.

The goal is not generic "industrial company" discovery. The system is built to find businesses that would plausibly **buy or use** Tritorc's tools and services — end-user plant operators, shutdown/turnaround maintenance contractors, EPC contractors — while actively excluding competitors, tool distributors/suppliers, and unrelated local businesses that a naive keyword search would otherwise pull in.

---

## Quick start

You need: **Python 3.12**, **Node 20+**, a **MongoDB** (local or Atlas) and a **Google Places API key**. The Enrichment page also needs a free **Groq** key (a Gemini key is optional and used as backup).

```bash
# 1. Backend  (terminal 1)
cd backend
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt     # Windows (macOS/Linux: venv/bin/python)
cp .env.example .env                                           # then fill in the keys, see "Environment variables"
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 2. Frontend  (terminal 2)
cd frontend
npm install
npm run dev                                                     # open http://127.0.0.1:5173
```

Sign in with the `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` you put in `backend/.env`. Check the API is up at `http://127.0.0.1:8000/health` (interactive docs at `/docs`).

Run the offline tests (no network or API keys needed):

```bash
cd backend
venv\Scripts\python.exe -m unittest discover -s tests
```

---

## User flow

1. **Set up a search** (`Dashboard`) — pick a country, then choose one of three location modes:
   - **State/City** — a specific state and/or city, searched directly.
   - **Auto (leave state/city blank)** — the backend automatically fans out across the country's real industrial hubs (see [Layer 1](#layer-1--sourcing-google-places) below) instead of one broad, low-yield country-wide query.
   - **Custom area** — draw a center point and radius (up to 50km) directly on a map, for targeting one specific industrial cluster (a port, a refinery corridor) precisely.

   Keywords and industry tags come pre-loaded with a buyer-focused default list (shutdown/turnaround contractor, hot tapping, flange facing, heat-exchanger retubing, etc.) and are fully editable. Before starting, the screen shows a live cost estimate (projected Google Places API calls) and current quota usage, so a search can't be started blind.

2. **Watch it run** (`Progress`) — a live progress bar, running result count, and a **Stop** button that cleanly halts the search mid-run (already-found results are kept, nothing is lost).

3. **Review results** (`Results`) — every business found in that search, with tier (Best/Strong/Weak/Reject/Unknown) and role (End-user, Service Contractor, EPC, Supplier/Distributor, Competitor, Generic Service, Unknown) filter chips, the crawler's reasoning and evidence snippets, and CSV/XLSX export with a column picker.

4. **Master Database** — every business ever found, across every search, deduplicated by Google `place_id`. This is the durable, cumulative dataset — re-running a search doesn't create duplicates, it just refreshes what's already known.

5. **History** — past searches with their status, result counts, and quota cost, so a repeat search can reuse what's already been covered instead of re-spending API quota on the same ground (see the skip-log in Layer 1).

6. **Company Enrichment** — paste company names or websites (or upload a CSV/XLSX/TXT/JSON list) and get a verdict for each. See [Company Enrichment](#company-enrichment) below.

7. **Admin** — user accounts, per-user credit limits, monthly quota usage, and maintenance actions (e.g. marking stuck searches as failed).

---

## Core system: the three-layer pipeline

```text
Layer 1 — SOURCING           Layer 2 — CRAWL & SCORE            Layer 3 — LLM REVIEW
Google Places Text Search -> Crawlee website crawl            -> Gemini second opinion
(anchor-seeded fan-out,       + multilingual concept/role         (only for the tiers/
 adaptive drill-down,         matching -> score -> tier            languages the rule
 custom radius, skip-log)     (best/strong/weak/reject/unknown)    engine can't trust)
```

### Layer 1 — sourcing (Google Places)

A plain "keyword in country" search only ever returns Google's top ~60 most prominent, relevance-ranked results — re-running it just resurfaces the same handful of famous businesses, no matter how many times you search. To get real coverage, an automatic (state/city left blank) search instead:

- **Discovers real industrial anchors.** Rather than guessing where a country's industry is, the system asks Google directly — querying asset-owner terms ("oil refinery", "petrochemical plant", "LNG terminal", "shipyard", etc.) per state and keeping the real coordinates returned. This was a deliberate fix for a measured problem: naive state-centroid circles landed 100–400+ km from every real refinery/plant tested. Anchors are cached per state (`industrial_anchors.py`) so this discovery cost is paid once, not on every search.
- **Picks one circle per state, fairly.** Candidate anchors are ranked by local density and by how unambiguous their matching keyword was (a match on "oil refinery" is trusted more than "steel plant", which can also match a trading company) — capped at 25 locations total, one per state, so a few dense metro areas can't crowd out every other state's slot.
- **Searches each location with a real 50km geographic circle** (`locationBias`), not just a location name in the query text.
- **Drills down adaptively.** If a state's circle comes back saturated (Google had more results than the 60-result page ceiling gave up), the system automatically sweeps up to 10 of that state's cities individually — spending extra API calls only where the data proves they're needed.
- **Never re-asks a question it already answered.** A persistent skip-log remembers which (country, state, city, keyword) combinations were already fully searched, so a repeat search costs nothing for ground already covered — versioned so a change to the sourcing logic itself doesn't get masked by stale "already searched" entries.
- **Custom area mode** bypasses all of the above — a user-drawn circle is a deliberate, exact request, searched once, with no skip-log and no drill-down.

### Layer 2 — crawl & score, in detail

#### Before any crawling happens: the Google-type pre-filter

If Google's own place `types` (or `primaryType`) for a business match an obviously non-industrial category — `school`, `restaurant`, `cafe`, `lodging`, `real_estate_agency`, `plumber`, `roofing_contractor`, `electrician`, `car_repair`, `store`, `shopping_mall`, `local_government_office`, etc. — the business is rejected immediately with `status="skipped"`, no crawl attempted at all. This is a free, zero-cost filter that catches the most obvious non-fits before spending any crawl time on them.

If there's no website on file at all, the business gets `tier="unknown"` with a "no website available" reason — also with no crawl attempted.

#### The crawl itself

Each remaining business's website is crawled with [Crawlee](https://crawlee.dev/)'s `BeautifulSoupCrawler`:

- **Up to 10 pages, 2 links deep** from the homepage (`MAX_PAGES_PER_SITE = 10`, `max_crawl_depth = 2`). No JavaScript rendering — this is a deliberate scope decision (a Playwright-based JS-rendering retry would catch more React/Wix/Squarespace sites, but adds a real headless-browser dependency to the deployment, so it was left out in favor of depth/breadth improvements that need no new infrastructure).
- **10-second navigation timeout per page**, one retry, no session rotation — a slow or broken site fails fast rather than stalling the whole crawl.
- **A `httpx` + BeautifulSoup fallback** kicks in if the primary Crawlee run finds nothing at all (e.g. blocked or mis-configured sites).
- Each page's text is stripped of `script`/`style`/`noscript`/`svg` tags, whitespace-normalized, and capped at 12,000 characters per page.
- **Which pages get crawled first is not left to chance.** Links are ranked by a priority score before the crawler decides where to spend its 10-page budget: generic industry-relevant terms in the URL (`oil`, `gas`, `refinery`, `pipeline`, `bolting`, `flange`, `integrity`, `calibration`, `rental`, etc.) each add a small amount; a link that looks like a **dedicated services/capabilities page** — `services`, `capabilities`, `what-we-do`, and their Spanish/Portuguese/German/French equivalents (`servicio(s)`, `serviço(s)`/`servico(s)`, `leistung`, `prestation`) — gets a dominant +100 bonus, so a site's actual "what we do" page is crawled essentially first, ahead of `/about` or generic content, in whatever language it's written in. Deeper URLs (more `/` segments) are mildly deprioritized.

#### Language detection

The combined crawled text is run through [`lingua`](https://github.com/pemistahl/lingua-py)'s language detector across **all 87 languages it supports** — not a narrow hand-picked subset. If no text sample is available (crawl failed), detection falls back to the business's original search-query language, then a country-code heuristic, then English as a last resort.

The detected language and the *scoring* language are tracked separately: concept matching itself only has real, hand-built phrase lists for **English, Spanish, French, Portuguese, and German** (`WELL_COVERED_LANGUAGES`). A business correctly detected as, say, Japanese or Arabic still gets scored against the English phrase list as a weak fallback signal — but critically, the LLM fallback layer (Layer 3) is told explicitly when this has happened, and treats it as a signal to force a review regardless of what tier the rule engine landed on, rather than silently trusting a score computed from the wrong language's taxonomy.

#### Concept matching and scoring

The crawled text (in whichever language is being scored) is checked for substring matches against three phrase-list taxonomies:

- **`CONCEPT_PHRASES`** (positive) — split into **core** concepts, which are direct evidence of the actual work Tritorc's tools are for (controlled bolting, bolt tensioning, flange management/facing, onsite machining, hot tapping, pipeline integrity/maintenance, hydrotesting, leak sealing, heat-exchanger retubing, structural bolting, joint integrity, torque services, hot bolting, line stopping), and **context** concepts, which identify an industry sector but aren't proof of the work itself (oil & gas, refinery, petrochemical, fertilizer/grain elevator, power plant, steel plant, wind turbine, LNG, shipyard, mining, cement plant, nuclear, FPSO, EPC, industrial maintenance, pressure vessel). Each concept carries its own point weight (12–20).
- **`NEGATIVE_CONCEPT_PHRASES`** — roofing, remodeling, HVAC, plumbing, school, chamber of commerce, real estate, restaurant, retail, hardware store, residential construction, hotel, clinic, tool/fastener/equipment distributor language (weights 16–35).
- **`BUSINESS_ROLE_PHRASES`** — separately classifies the business itself as `end_user_operator`, `industrial_service_contractor`, or `epc_contractor` (positive roles, +34 to +45) versus `supplier_distributor`, `competitor_manufacturer`, or `generic_local_service` (negative roles, −45 to −60). Role classification takes precedence in a fixed order: a `competitor_manufacturer` match (branded/competing-tool language, or a known competitor brand name) hard-rejects the business outright regardless of any positive concept evidence, since the rule engine alone can't reliably tell "sells the same tools" from "does the same kind of work" — that specific ambiguity is exactly what Layer 3 exists to resolve. A `supplier_distributor` or `generic_local_service` match only rejects if there's no positive role evidence at all; a genuine positive role always wins if both are present.

The final numeric score is `positive_score + business_role_score − negative_score`, clamped to 0–100, plus a small diversity bonus for businesses matching several distinct concepts and an extra bonus specifically for `pipeline_integrity` or `controlled_bolting` matches (Tritorc's two strongest, least-ambiguous signals).

**Tiering** then applies two deliberate guardrails on top of the raw score:

- **A core-concept gate on the top tiers.** `best` (score ≥ 85) and `strong` (score ≥ 70) both require at least one **core** concept to have matched — context concepts alone can no longer produce a false "best" verdict (a confirmed live failure case: `oil_gas` + `refinery` + `industrial_maintenance` + `power_plant` + a role phrase alone summed to score 100 with zero real evidence of bolting/machining/integrity work). Without a core concept, a business that would otherwise score 85+ is capped at `strong`, and 70+ is capped at `weak` — keeping it visible for review rather than silently discarding it.
- **A two-word floor on "negative outweighs positive."** A business is only rejected purely for negative signal if `negative_score ≥ 45` *and* `positive_score < 40` — since no single negative phrase is weighted that high, this requires at least two distinct negative concepts to fire, so one incidental off-topic sentence (a client mentioned in a portfolio, an unrelated past project) can no longer override strong positive evidence on its own.

Every positive **and** negative concept match is captured with a quoted, verbatim evidence snippet from the actual crawled page (not just the concept's name) — shown in the UI and, critically, passed to the LLM fallback in Layer 3 so it can judge a negative mention in context instead of guessing from a bare label.

#### Versioning

`CRAWL_VERSION` is bumped every time the scoring logic changes meaningfully (currently `tritorc-crawl-v8`). A business already scored under an older version is treated as needing re-evaluation — `backfill_scores.py` re-processes exactly this backlog, re-crawling and re-scoring under the current logic using the website already on file, at zero added Google Places quota cost.

### Layer 3 — LLM fallback review (Gemini)

The rule engine above is fast and free, but it's still a blunt keyword matcher — a single incidental negative word (an unrelated client mentioned in a portfolio) or a role phrase matched out of context can still misfire. `gemini-3.5-flash-lite` gives a second opinion, but only where it's actually needed:

- **Never** for a `best`-tier verdict that already required real core evidence to get there.
- **Always** for `weak` tier (the rule engine's own "not sure" tier), for a `reject` that still has positive concept evidence or a positive role signal, for a `strong` verdict with a genuine mixed positive/negative signal, and for **any business in a language the taxonomy doesn't cover** — regardless of what tier the rule engine gave it, since that tier can't be trusted for the same reason.
- The prompt is shown the rule engine's tier/role/concepts **and quoted evidence snippets for both positive and negative matches** (not just the concept names), so it can judge whether a negative mention is incidental or describes the business's own core work — the exact failure mode most likely to wrongly reject a real lead.
- Bounded by a per-search and a monthly call cap so cost can't run away regardless of search volume.

---

## Company Enrichment

Takes a list of company names or websites, crawls each company's own website, and has an AI read it to say who the company is and whether it is a good lead.

**Pick the seller.** A toggle at the top chooses whose point of view the verdict uses: **Tritorc** or **Ozat** (ozat-tools.com). Each seller has its own product catalog, competitor list and accept/reject rules (`backend/app/services/seller_profiles.py`), and its own stored results. The website crawl is shared, so judging a company already crawled for the other seller costs one AI call and no new crawl.

**What you get per company**

- **Crawl Tier** (best/strong/weak/reject/unknown) from the keyword scorer, shown with its score.
- **LLM Decision**: *Accept* (green row), *Review* (yellow: low confidence or thin evidence), *Reject* (red), or *Weak* (light orange). Competitors (e.g. HYTORC, Enerpac for Tritorc) are marked and rejected; distributors, resellers and rental houses are accepted.
- Customer type (End user / EPC / Distributor / Competitor), industry, address, phone, contacts, recent projects, "why it fits", and a turnover class (**A / B / C**) when the site states one.
- Your own override (Accept / Review / Reject plus a note) and a **Wrong company?** button that re-matches by website.

**How duplicates and re-runs work.** Every company is stored once in MongoDB (`company_enrichments`). A name, a website and spelling variants (`Acme Ltd`, `ACME`, `acme.com`) all point to the same record. A saved result is reused instead of re-crawling while it is younger than 90 days (`ENRICHMENT_CACHE_MAX_AGE_DAYS`); it is re-crawled only when older, when the last crawl failed, or when you press Retry/Refresh. If the same company is requested twice at once, the second request waits and reuses the first one's result.

**Automatic deletion.** Enrichment data (stored companies and the Past sessions list, nothing else) is deleted automatically 15 days after it was last enriched or started, using MongoDB TTL indexes (`ENRICHMENT_RETENTION_DAYS`, default 15, `0` turns it off). Viewing a saved result does not extend it; enriching or retrying it again does. Because of this, the effective reuse window is 15 days even though `ENRICHMENT_CACHE_MAX_AGE_DAYS` defaults to 90. Lead Discovery searches and the Master Database are never touched.

**How the AI is called.** Groq (`openai/gpt-oss-120b`) first; if it fails (daily limit, busy, outage, unreadable answer) the request automatically falls back to Gemini (`GEMINI_API_KEY`). Failures are shown in plain language with a Retry button. Results stream into the table one company at a time, so Stop keeps everything finished so far.

**Safety.** Only public http(s) websites are fetched (private/internal addresses are blocked and redirects are re-checked), page downloads are size- and time-capped, page text is treated as untrusted data, and spreadsheet exports neutralise formula-style cells.

Key files: `backend/app/api/enrichment.py` (routes), `services/enrichment_engine.py` (crawl + AI), `services/enrichment_store.py` (storage, cache, per-seller views), `services/seller_profiles.py` (Tritorc/Ozat), `services/ozat_scorer.py`, and `frontend/src/components/Enrichment*.jsx`.

---

## What counts as a good Tritorc lead

Preferred roles: `end_user_operator`, `industrial_service_contractor`, `epc_contractor`.

Examples: refinery/petrochemical/fertilizer/power/steel plant operators, pipeline operators, shutdown/turnaround maintenance contractors, hot tapping/hydrotesting/pipeline integrity service companies, industrial EPC contractors, wind/heavy-industry maintenance contractors, heat-exchanger retubing specialists, tool rental/hire fleets and calibration labs (channel, not competition).

## What gets excluded

`supplier_distributor`, `competitor_manufacturer`, `generic_local_service` — hydraulic torque wrench/bolt tensioner/flange-facing-machine **sellers or renters**, valve/fitting/hose/fastener/hardware/machine-tool sellers, and generic building maintenance, HVAC, residential construction, restaurants, schools, real estate, etc.

```text
Service contractor doing the work at someone else's plant = possible lead
Company selling/renting the same tool category           = reject
End-user plant/operator                                    = good lead
```

---

## Main features

- Three search modes: state/city, automatic country-wide fan-out (anchor-seeded, with adaptive city drill-down), and a manual map-drawn radius search.
- Buyer-focused default keywords and industry tags, fully editable.
- Live cost estimate and quota snapshot before every search; a Stop button mid-search.
- Crawlee-based website crawling with service-page prioritization across languages.
- Core/context concept scoring and business-role classification, covering English, Spanish, French, Portuguese, and German phrase taxonomies, with 87-language detection.
- Gemini LLM fallback review, targeted at exactly the cases the rule engine can't trust.
- Tier filters (Best/Strong/Weak/Reject/Unknown) and role filters, with crawler evidence and LLM reasoning shown per business.
- Master database with deduplication by Google `place_id`, persistent across every search ever run.
- CSV/XLSX export with a column picker.
- `backfill_scores.py` — re-scores any business whose stored score predates the current scoring logic, using its already-stored website, at **zero** added Google Places quota cost.
- **Company Enrichment** with a Tritorc/Ozat seller toggle, accept/review/reject verdicts, a shared crawl cache, and Groq-with-Gemini-backup AI.
- JWT auth, per-user credit limits, admin portal, and Google Places API quota tracking (5,000 free calls/month, matching Google's actual free tier).

## Important implementation docs

- [Current implementation status](IMPLEMENTATION_STATUS.md)
- [Deployment guide](DEPLOYMENT.md)
- [Company Enrichment plan](COMPANY_ENRICHMENT_INTEGRATION_PLAN.md)

Older, narrower planning docs (`SUPPLIER_ROLE_SCORING_FIX_PLAN.md`, `MULTILINGUAL_CRAWLER_PLAN.md`, `BROWSER_PLUGIN_*`) remain in the repo for historical context but describe earlier stages of the system — this README reflects the current, active architecture.

## Project structure

```text
Lead_discovery/
|-- backend/
|   |-- app/
|   |   |-- api/          # FastAPI routes (auth, searches, quota, admin, settings, enrichment)
|   |   |-- config/       # settings, quota thresholds, concept/keyword taxonomy, geo data
|   |   |-- db/           # Mongo connection + index setup
|   |   |-- models/       # Pydantic schemas
|   |   `-- services/     # search_runner, places_client, industrial_anchors,
|   |                     # crawl_scorer, llm_fallback, location_search_log,
|   |                     # enrichment_engine/store, seller_profiles, ozat_scorer, ...
|   |-- scripts/          # backfill_scores.py and other one-off/maintenance scripts
|   |-- tests/            # offline unit tests (python -m unittest discover -s tests)
|   |-- Dockerfile        # production image
|   |-- requirements.txt
|   |-- run_backend.ps1
|   `-- run_backend.bat
|-- frontend/
|   |-- src/
|   |   |-- components/   # Dashboard, LocationPicker, Progress, Results,
|   |   |                 # MasterDatabase, History, Admin, Login,
|   |   |                 # Enrichment, EnrichmentResults, leadShared
|   |   `-- ...
|   |-- package.json
|   `-- vite.config.js
|-- docker-compose.yml   # production compose file (used on the server)
|-- .github/workflows/   # deploy-backend.yml: build image, deploy to EC2 on merge to master
|-- deploy/              # server setup script
|-- DEPLOYMENT.md
|-- IMPLEMENTATION_STATUS.md
`-- README.md
```

## Local setup

### Backend

From PowerShell:

```powershell
cd backend
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
cd frontend
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

# Company Enrichment
GROQ_API_KEY=your-groq-api-key              # required for the Enrichment page
GROQ_MODEL=openai/gpt-oss-120b
SERPER_API_KEY=                             # optional: company name -> official website lookup
ENRICHMENT_CACHE_MAX_AGE_DAYS=90            # reuse a saved crawl for this long
ENRICHMENT_RETENTION_DAYS=15                # delete enrichment data this long after it was last updated (0 = never)

# Backup AI for Enrichment (used when Groq fails) and for the Lead Discovery LLM fallback
GEMINI_API_KEY=your-google-ai-studio-gemini-api-key

LLM_FALLBACK_ENABLED=false
LLM_FALLBACK_MIN_SCORE=40
LLM_FALLBACK_MAX_SCORE=69
LLM_FALLBACK_MAX_CALLS_PER_SEARCH=50
LLM_FALLBACK_MAX_CALLS_PER_MONTH=1000
```

Keep real `.env` files private. `GEMINI_API_KEY`/`LLM_FALLBACK_ENABLED` are optional — the rule-engine layers (sourcing + crawl/score) work fully without them; leaving the LLM fallback off just means Layer 3 never runs.

## Useful validation commands

Backend:

```powershell
cd backend
.\venv\Scripts\python.exe -m compileall -q app scripts
.\venv\Scripts\python.exe -c "import app.main; print('backend import ok')"
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Frontend:

```powershell
cd frontend
npm run build
```

Re-score existing businesses under the current scoring logic (no Places quota used):

```powershell
cd backend
.\venv\Scripts\python.exe -m scripts.backfill_scores --dry-run --limit 20
.\venv\Scripts\python.exe -m scripts.backfill_scores --concurrency 4
```

## Deployment

The backend runs as a **Docker container** on an AWS EC2 instance behind nginx (HTTPS), and the frontend deploys on Vercel.

- **Pull request:** GitHub Actions builds the Docker image only (nothing is published or deployed).
- **Merge to `master`:** Actions builds and pushes `ghcr.io/tritorc-ai1/lead-discovery-backend`, SSHes into the server, and restarts the container with the new image. The server's `.env` holds the secrets; they are never in the image.
- If a deploy fails, open the run under the repo's **Actions** tab (`Deploy backend`) and read the `deploy` job log; on the server, `docker compose logs backend` shows the same startup output.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full setup and redeploy steps.

## Team workflow rule

Before future coding or new project work:

1. Create or update a research/implementation `.md` plan first.
2. Use higher-model reasoning for planning when available.
3. Wait for approval.
4. Then implement, validate, and update docs.

This rule exists because crawler/search quality changes can easily create false positives or burn API quota.
