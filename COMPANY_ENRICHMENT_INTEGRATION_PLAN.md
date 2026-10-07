# Company Enrichment Platform — integration plan

Source: https://github.com/tritorc-ai/Company-Enrichment-Platform (1 commit, 5 files, ~1,800 lines).
Status: **Phase 1 implemented and verified (decisions: port into app, store in Mongo, Groq OK). Phase 2 (theme) done inline — page built with Lead Discovery's Tailwind patterns. Not committed.**

## How the Enrichment Platform works today (standalone)

Stack: single-file FastAPI app (`server.py`, 607 lines) + one static page (`static/index.html`, 932 lines, vanilla JS, own purple/blue theme) + `tritorc_offerings.json` (Tritorc catalog, 270 lines). No auth, no database, no persistence — state lives in the browser.

Flow per input line (`enrich_company`):
1. **Input resolution** — a line can be a company name, a URL/domain, or an email. Email on a company domain -> `https://domain`; webmail (gmail etc.) -> treated as "no website".
2. **Find site** (names only) — `find_official_site`: Serper search (`SERPER_API_KEY`) + Groq LLM picks the official site; reachability probed with HEAD/GET, TLS-verify retry.
3. **Crawl** — `crawl_company_site`: `requests` + BeautifulSoup, up to 4 pages, text capped to 6,000 chars.
4. **LLM extraction** — Groq (`openai/gpt-oss-120b`, JSON mode, retry on 429/json errors) fills a fixed schema: company_name, website, country, industry, company_category (`distributor` | `ECP` | `end_user`), business_description, key_operations, projects_or_recent_activity, tritorc_relevance (grounded in the offerings catalog).
5. **API** — `POST /api/parse-file` (CSV/XLSX/JSON -> company names), `POST /api/enrich` (Server-Sent Events stream: start / progress / complete), `POST /api/export-xlsx`, `GET /` serves the page.

Env needed: `GROQ_API_KEY`, optional `SERPER_API_KEY`, `GROQ_MODEL`.

## How Lead Discovery works today (relevant parts)

FastAPI + MongoDB + React (Vite, Tailwind 4, lucide-react, react-router), JWT login, per-user credits. Already contains `services/company_profile_crawler.py` (URL -> company profile, httpx fallback, own scoring/role classifier) and `api/companies.py` — **overlapping capability** with the enrichment platform, but rule-based (no LLM, no Serper).

## Proposed integration (Phase 1: make it work)

Approach: port into Lead Discovery as a feature, not a separate app, so it shares login, Mongo and the React shell.

1. **Backend**
   - `backend/app/services/enrichment/` — port `find_official_site`, `crawl_company_site`, prompt builder, Groq call + retry, `resolve_from_email`, file parsing. Keep logic intact; swap `print`/ad-hoc errors for `error_logger`.
   - `backend/app/config/tritorc_offerings.json` — move the catalog.
   - `backend/app/api/enrichment.py` — routes under `/api/enrichment/*` (`parse-file`, `enrich` SSE, `export-xlsx`), behind existing auth dependency.
   - New deps in `requirements.txt`: `groq`, `openpyxl` (if absent), `beautifulsoup4`, `lxml`, `python-multipart`. New env: `GROQ_API_KEY`, `SERPER_API_KEY`, `GROQ_MODEL` (add to `.env.example`).
   - Sync `requests` calls run in executor (as today) so they don't block the event loop.
2. **Frontend** — new `Enrichment.jsx` page at `/enrichment` + nav link, porting the existing UI behaviour: textarea/file upload, SSE progress, results cards, XLSX download. Phase 1 may reuse the original markup/styling to prove function first.
3. **Verify** — run backend+frontend, enrich 3 sample inputs (name, URL, email), check SSE progress, XLSX export, error paths (missing keys, unreachable site).

## Phase 2: theme

Restyle the Enrichment page with Lead Discovery's tokens (Tailwind slate/neutral palette, Inter font, existing card/button/chip patterns from `Dashboard.jsx` / `Results.jsx`, lucide icons), replacing the purple-blue gradient. Check light-mode parity and mobile width.

## Decisions needed

1. **Integration style** — port into this app (recommended) vs. run the original as a separate service and link/iframe it.
2. **Keys** — need your `GROQ_API_KEY` (and `SERPER_API_KEY` if name->website lookup should work) in `backend/.env`. I won't create these.
3. **Persistence (optional, later)** — save enrichment results to Mongo / link to Master Database entries and consume credits? Phase 1 keeps it stateless like the original.
4. **Overlap** — keep both the rule-based profile crawler and this LLM enrichment, or later merge them?
5. **Data sensitivity** — crawled text goes to Groq (third party); confirm that's acceptable for this data.

## Implemented schema — `company_enrichments` (Mongo)

| field | purpose |
|---|---|
| `cache_key` (unique) | domain, or `name:<name_key>` when no site found |
| `domain`, `website` | normalized host / root URL |
| `name_keys[]`, `input_aliases[]` | normalized names (+ domain stem) and raw inputs that resolved here -> name lookups |
| `place_ids[]` | Google Places ids linked by the map pipeline (`link_place_id`) |
| `company_name, country, industry, company_category, business_description, key_operations[], projects_or_recent_activity[], tritorc_relevance[]` | LLM extraction |
| `crawled_pages[{url,text}]`, `crawl_status`, `crawl_error`, `crawl_version`, `last_crawled_at` | the reusable crawl |
| `llm_model`, `enriched_at`, `hit_count`, `created_by`, `created_at`, `updated_at` | provenance |

Reuse API for the Places/map pipeline (`app/services/enrichment_store.py`): `find_enrichment(domain|name|place_id)`, `get_cached_pages(domain)`, `link_place_id(domain, place_id)`; HTTP: `GET /api/enrichment/lookup`. Freshness: `ENRICHMENT_CACHE_MAX_AGE_DAYS` (90).

**Not yet done:** wiring `crawl_scorer`/`search_runner` to call `get_cached_pages` before crawling (separate, riskier change to scoring — needs its own approval).
