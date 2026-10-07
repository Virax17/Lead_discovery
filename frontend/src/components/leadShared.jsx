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

export const customerTypeLabel = (role) => CUSTOMER_TYPE_LABELS[role || 'unknown'] || 'Unknown';

// Competitor if the rule-based scorer OR the enrichment LLM says so.
// Tritorc's own record is never a competitor, even though its site matches the
// competitor keywords (torque wrenches, bolt tensioners...).
const isOwnCompany = (r) => /tritorc/i.test(`${r?.website || ''} ${r?.domain || ''} ${r?.company_name || r?.name || ''}`);

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
