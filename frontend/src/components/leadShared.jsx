import React, { useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { enrichSingle } from '../api';

// One customer-type vocabulary for Lead Discovery and Enrichment, derived from
// the crawler's business_role (mirrors CUSTOMER_TYPE_LABELS in export_engine.py).
const CUSTOMER_TYPE_LABELS = {
    end_user_operator: 'End User',
    industrial_service_contractor: 'Service Contractor',
    epc_contractor: 'EPC Contractor',
    supplier_distributor: 'Distributor',
    competitor_manufacturer: 'Competitor',
    generic_local_service: 'Not Relevant',
    unknown: 'Unknown',
};

const CATEGORY_LABELS = { competitor: 'Competitor', distributor: 'Distributor', ECP: 'EPC', end_user: 'End User' };

// The enrichment LLM's category (EPC, End User...) wins when present; otherwise the crawler's role.
export const customerTypeLabel = (role, category) =>
    CATEGORY_LABELS[category] || CUSTOMER_TYPE_LABELS[role || 'unknown'] || 'Unknown';

// Accept / review / reject: the LLM's verdict when stored, otherwise derived from the crawl tier
// so older enrichments still show something sensible.
const VERDICT_STYLES = {
    accept: { label: 'Accept', cls: 'bg-emerald-100 text-emerald-700' },
    review: { label: 'Review', cls: 'bg-yellow-100 text-yellow-800' },
    reject: { label: 'Reject', cls: 'bg-rose-100 text-rose-700' },
    unjudged: { label: 'Not judged', cls: 'bg-slate-100 text-slate-600' },
};

export function llmVerdict(r) {
    if (isOwnCompany(r)) return null;
    // another seller's view (e.g. Ozat): nothing to derive from Tritorc's scorer, so until it is judged it is just "not judged"
    if (r?.profile && r.profile !== 'tritorc' && r.judged_for_profile === false && !['accept', 'review', 'reject'].includes(r?.override_decision)) return { key: 'unjudged', derived: true };
    if (['accept', 'review', 'reject'].includes(r?.override_decision)) return { key: r.override_decision, derived: false, override: true };
    if (VERDICT_STYLES[r?.llm_decision]) return { key: r.llm_decision, derived: false };
    if (isCompetitor(r)) return { key: 'reject', derived: true };
    if (r?.business_role === 'supplier_distributor') return { key: 'review', derived: true };
    const tier = r?.crawl_tier;
    if (tier === 'best' || tier === 'strong') return { key: 'accept', derived: true };
    // The keyword scorer alone wrongly rejects real leads (client lists, thin crawls), so a
    // scorer-only reject is "not judged" until the LLM has looked at the company.
    if (tier === 'reject') return { key: 'unjudged', derived: true };
    if (tier === 'weak' || tier === 'unknown') return { key: 'review', derived: true };
    return null;
}

// A / B / C size class by annual turnover (bands live in backend enrichment_engine.TURNOVER_BANDS).
const TURNOVER_STYLES = {
    A: 'bg-indigo-100 text-indigo-800',
    B: 'bg-sky-100 text-sky-800',
    C: 'bg-slate-100 text-slate-600',
};
const TURNOVER_BANDS = { A: 'US$100M or more a year', B: 'US$10M to under US$100M', C: 'under US$10M' };

export function TurnoverChip({ r }) {
    const c = r?.turnover_class;
    if (!TURNOVER_STYLES[c]) return <span className="text-slate-300">—</span>;
    const how = r.turnover_basis === 'stated'
        ? `Stated on their site${r.annual_turnover ? `: ${r.annual_turnover}` : ''}`
        : `Estimated (${r.turnover_basis || 'size'})`;
    return (
        <span
            className={`inline-flex min-w-[1.75rem] justify-center rounded-full px-2.5 py-0.5 text-xs font-bold ${TURNOVER_STYLES[c]}`}
            title={`Class ${c} = ${TURNOVER_BANDS[c]}. ${how}.`}
        >
            {c}
        </span>
    );
}

// Plain-language reason a company's website could not be read (from the stored crawl_error).
export function crawlProblem(r) {
    if (!r || r.error || !r.crawl_status || r.crawl_status === 'ok') return null;
    const e = String(r.crawl_error || '').toLowerCase();
    if (e.includes('no website')) return 'No website found for this name';
    if (e.includes('blocked:')) return 'Skipped: not a public website';
    if (/status (401|403|429|5\d\d)/.test(e)) return 'Their site blocks automated visits';
    if (e.includes('error fetching')) return "Their website didn't respond";
    return "Couldn't read their website";
}

export function VerdictChip({ r }) {
    const v = llmVerdict(r);
    if (!v) return <span className="text-slate-300">—</span>;
    const s = VERDICT_STYLES[v.key];
    return (
        <span
            className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${s.cls}`}
            title={v.override
                ? `Your decision${r.override_note ? `: ${r.override_note}` : ''}`
                : r.llm_decision_reason || (v.key === 'unjudged'
                    ? 'Only the keyword scorer has seen this company. Enrich it again to get an LLM verdict (uses the saved crawl, no re-crawl).'
                    : v.derived ? 'Derived from the crawl tier. Enrich again for an LLM verdict.' : '')}
        >
            {s.label}{v.override && <span className="ml-1 text-[10px] font-medium opacity-70">you</span>}
        </span>
    );
}

// Competitor if the rule-based scorer OR the enrichment LLM says so.
// The seller's own record (Tritorc, or Ozat in the Ozat view) is never a competitor, even though its
// site matches the competitor keywords (torque wrenches, impact sockets...).
const OWN_COMPANY = { tritorc: /tritorc/i, ozat: /ozat/i };
const isOwnCompany = (r) => (OWN_COMPANY[r?.profile] || OWN_COMPANY.tritorc).test(`${r?.website || ''} ${r?.domain || ''} ${r?.company_name || r?.name || ''}`);

export const isCompetitor = (r) =>
    !isOwnCompany(r) && (
        r?.business_role === 'competitor_manufacturer'
        || r?.is_competitor === true
        || r?.company_category === 'competitor'
        || r?.enrichment?.is_competitor === true
        || r?.enrichment?.company_category === 'competitor'
    );

export function CompetitorBadge({ r }) {
    if (!isCompetitor(r)) return null;
    return (
        <span className="inline-flex shrink-0 whitespace-nowrap rounded-full bg-rose-600 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">
            Competitor
        </span>
    );
}

// The 11 columns both views lead with, in order (key/label are shared; each
// view renders its own cell content).
export const PRIORITY_COLUMNS = [
    { key: 'source', label: 'Source' },
    { key: 'name', label: 'Company Name' },
    { key: 'website', label: 'Website' },
    { key: 'address', label: 'Address' },
    { key: 'phone_number', label: 'Phone Number' },
    { key: 'crawl_tier', label: 'Crawl Tier' },
    { key: 'llm_fallback_decision', label: 'LLM Decision' },
    { key: 'industry_type', label: 'Industry Type' },
    { key: 'customer_type', label: 'Customer Type' },
    { key: 'recent_projects', label: 'Recent Projects' },
    { key: 'tritorc_relevance', label: 'Tritorc Relevance' },
];

export function listText(value, max = 220) {
    if (!value || value.length === 0) return '-';
    const text = Array.isArray(value) ? value.join('; ') : String(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

// Per-row button for businesses that have not been through Company Enrichment.
export function EnrichButton({ business, onEnriched }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const run = async () => {
        setBusy(true);
        setError('');
        try {
            const data = await enrichSingle({
                companyName: business.name,
                website: business.website,
                placeId: business.place_id,
            });
            onEnriched(data);
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <div>
            <button
                type="button"
                onClick={run}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-60"
            >
                {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                {busy ? 'Enriching…' : 'Enrich'}
            </button>
            {error && <div className="mt-1 max-w-[12rem] text-xs text-rose-600">{error}</div>}
        </div>
    );
}
