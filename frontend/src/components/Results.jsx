import React, { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { AlertTriangle, Download, SlidersHorizontal, X } from 'lucide-react';
import { downloadFile, fetchSearch } from '../api';
import { useI18n } from '../i18n/I18nContext';
import { useShell } from '../context/ShellContext';

// Decision-relevant fields first (identity, then the actual verdict and
// why), internal debug/signal fields after — so the columns that matter
// for "is this a real lead" aren't buried behind crawler internals.
const DEFAULT_COLUMNS = [
    { key: 'source', label: 'Source' },
    { key: 'name', label: 'Company Name' },
    { key: 'address', label: 'Address' },
    { key: 'website', label: 'Website' },
    { key: 'phone_number', label: 'Phone Number' },
    { key: 'crawl_tier', label: 'Crawl Tier' },
    { key: 'business_role', label: 'Business Role' },
    { key: 'llm_fallback_decision', label: 'LLM Fallback Decision' },
    { key: 'crawl_reason', label: 'Crawl Reason' },
    { key: 'llm_fallback_reason', label: 'LLM Fallback Reason' },
    { key: 'industry_type', label: 'Industry Type' },
    { key: 'crawl_score', label: 'Crawl Score' },
    { key: 'llm_fallback_status', label: 'LLM Fallback' },
    { key: 'llm_fallback_confidence', label: 'LLM Fallback Confidence' },
    { key: 'crawl_evidence', label: 'Crawl Evidence' },
    { key: 'positive_concepts', label: 'Positive Concepts' },
    { key: 'negative_concepts', label: 'Negative Concepts' },
    { key: 'business_role_reason', label: 'Role Reason' },
    { key: 'detected_language', label: 'Detected Language' },
    { key: 'source_query', label: 'Source Query' },
    { key: 'source_query_language', label: 'Query Language' },
    { key: 'website_signal', label: 'Website Signal' },
    { key: 'maps_url', label: 'Google Maps URL' }
];

const TIER_FILTERS = [
    { key: 'best', label: 'Best' },
    { key: 'strong', label: 'Strong' },
    { key: 'weak', label: 'Weak' },
    { key: 'reject', label: 'Reject' },
    { key: 'unknown', label: 'Unknown' },
];

const ROLE_FILTERS = [
    { key: 'end_user_operator', label: 'End-user' },
    { key: 'industrial_service_contractor', label: 'Service Contractor' },
    { key: 'epc_contractor', label: 'EPC' },
    { key: 'supplier_distributor', label: 'Supplier/Distributor' },
    { key: 'competitor_manufacturer', label: 'Competitor' },
    { key: 'generic_local_service', label: 'Generic Service' },
    { key: 'unknown', label: 'Unknown Role' },
];

function formatEvidence(value) {
    if (!value || value.length === 0) return '-';
    const text = Array.isArray(value) ? value.join('; ') : String(value);
    return text.length > 180 ? `${text.slice(0, 180)}...` : text;
}

export default function Results() {
    const { id } = useParams();
    const navigate = useNavigate();
    const { t, formatNumber } = useI18n();
    const { refreshQuota } = useShell();
    const [searchData, setSearchData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showExportPicker, setShowExportPicker] = useState(false);
    const [selectedColumns, setSelectedColumns] = useState(DEFAULT_COLUMNS.map(column => column.key));
    // Multi-select, defaulting to everything checked (identical to the old
    // "all" behavior) — uncheck "Reject" to exclude it from both the table
    // and the download in one step, instead of only being able to view/
    // export exactly one tier at a time.
    const [selectedTierKeys, setSelectedTierKeys] = useState(TIER_FILTERS.map(f => f.key));
    const [selectedRoleKeys, setSelectedRoleKeys] = useState(ROLE_FILTERS.map(f => f.key));

    React.useEffect(() => {
        fetchSearch(id).then(data => {
            setSearchData(data);
            setLoading(false);
            refreshQuota();
        }).catch(() => {
            navigate('/');
        });
    }, [id, navigate, refreshQuota]);

    const businesses = searchData?.businesses || [];
    const filteredBusinesses = useMemo(
        () => businesses.filter(business => {
            const tierMatch = selectedTierKeys.includes(business.crawl_tier || 'unknown');
            const roleMatch = selectedRoleKeys.includes(business.business_role || 'unknown');
            return tierMatch && roleMatch;
        }),
        [businesses, selectedTierKeys, selectedRoleKeys]
    );
    const quotaLimited = searchData?.status === 'completed_quota_limited';
    const rateLimited = searchData?.status === 'completed_rate_limited';
    const failed = searchData?.status === 'failed';
    const exportColumns = useMemo(() => DEFAULT_COLUMNS.filter(column => selectedColumns.includes(column.key)), [selectedColumns]);

    const toggleColumn = (key) => {
        setSelectedColumns(prev => prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]);
    };

    const toggleTier = (key) => {
        setSelectedTierKeys(prev => prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]);
    };

    const toggleRole = (key) => {
        setSelectedRoleKeys(prev => prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]);
    };

    const handleDownload = async (format) => {
        // Everything selected = no filter, matching the backend's existing
        // "no selected_tiers/selected_roles = no $match stage" behavior.
        const selectedTiers = selectedTierKeys.length === TIER_FILTERS.length ? [] : selectedTierKeys;
        const selectedRoles = selectedRoleKeys.length === ROLE_FILTERS.length ? [] : selectedRoleKeys;
        await downloadFile(id, format, exportColumns.map(column => column.label), selectedTiers, selectedRoles);
        setShowExportPicker(false);
    };

    if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-600">{t('common.loading')}</div>;
    if (!searchData) return null;

    return (
        <div className="space-y-6">
            <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_20px_80px_rgba(15,23,42,0.08)]">
                <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_55%,#38bdf8_100%)] px-8 py-8 text-white">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                            <h2 className="text-3xl font-semibold tracking-tight">{t('results.title')}</h2>
                            <p className="mt-2 text-sm text-slate-100/90">
                                {t('results.found', { count: formatNumber(searchData.total_results || 0) })}
                                {' · '}
                                {t('results.creditsUsed', { count: formatNumber(searchData.place_details_calls_used || 0) })}
                            </p>
                        </div>
                        <div className="flex flex-wrap gap-3">
                            <button onClick={() => setShowExportPicker(true)} className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-2 text-sm font-medium text-white backdrop-blur hover:bg-white/20">
                                <SlidersHorizontal className="h-4 w-4" />
                                {t('results.customizeExport')}
                            </button>
                        </div>
                    </div>
                </div>

                {quotaLimited && (
                    <div className="m-8 rounded-2xl border border-amber-200 bg-amber-50 p-4">
                        <div className="flex gap-3">
                            <AlertTriangle className="h-5 w-5 text-amber-600" />
                            <div>
                                <p className="text-sm font-semibold text-amber-900">{t('results.quotaStopped')}</p>
                                <p className="mt-1 text-sm text-amber-800">{t('results.partial')}</p>
                            </div>
                        </div>
                    </div>
                )}

                {rateLimited && (
                    <div className="m-8 rounded-2xl border border-rose-200 bg-rose-50 p-4">
                        <div className="flex gap-3">
                            <AlertTriangle className="h-5 w-5 text-rose-600" />
                            <div>
                                <p className="text-sm font-semibold text-rose-900">{t('results.rateLimitedTitle')}</p>
                                <p className="mt-1 text-sm text-rose-800">{t('results.rateLimitedDetail')}</p>
                            </div>
                        </div>
                    </div>
                )}

                {failed && (
                    <div className="m-8 rounded-2xl border border-rose-200 bg-rose-50 p-4">
                        <div className="flex gap-3">
                            <AlertTriangle className="h-5 w-5 text-rose-600" />
                            <div>
                                <p className="text-sm font-semibold text-rose-900">{t('results.failedTitle')}</p>
                                <p className="mt-1 text-sm text-rose-800">{t('results.failedDetail')}</p>
                            </div>
                        </div>
                    </div>
                )}

                <div className="overflow-x-auto px-8 pb-8">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Tiers (uncheck to exclude, e.g. Reject):</span>
                        {TIER_FILTERS.map(filter => (
                            <button
                                key={filter.key}
                                type="button"
                                onClick={() => toggleTier(filter.key)}
                                aria-pressed={selectedTierKeys.includes(filter.key)}
                                className={`rounded-full border px-4 py-2 text-sm font-medium transition ${selectedTierKeys.includes(filter.key) ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 bg-white text-slate-400 line-through hover:border-blue-300 hover:text-blue-600'}`}
                            >
                                {filter.label}
                            </button>
                        ))}
                    </div>
                    <div className="mb-4 flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Roles:</span>
                        {ROLE_FILTERS.map(filter => (
                            <button
                                key={filter.key}
                                type="button"
                                onClick={() => toggleRole(filter.key)}
                                aria-pressed={selectedRoleKeys.includes(filter.key)}
                                className={`rounded-full border px-4 py-2 text-sm font-medium transition ${selectedRoleKeys.includes(filter.key) ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-slate-200 bg-white text-slate-400 line-through hover:border-indigo-300 hover:text-indigo-600'}`}
                            >
                                {filter.label}
                            </button>
                        ))}
                    </div>
                    <table className="min-w-full divide-y divide-slate-200 rounded-2xl border border-slate-200">
                        <thead className="bg-slate-50">
                            <tr>
                                {DEFAULT_COLUMNS.map(column => (
                                    <th key={column.key} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                                        {column.label}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-200 bg-white">
                            {filteredBusinesses.map((business, index) => (
                                <tr key={index} className="hover:bg-slate-50">
                                    <td className="px-6 py-4 text-sm text-slate-600">LeadDiscovery</td>
                                    <td className="px-6 py-4 text-sm font-medium text-slate-900">{business.name}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.address}</td>
                                    <td className="px-6 py-4 text-sm text-blue-600 hover:underline">
                                        {business.website ? <a href={business.website} target="_blank" rel="noreferrer">Website</a> : '-'}
                                    </td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.phone_number || '-'}</td>
                                    <td className="px-6 py-4 text-sm font-semibold capitalize text-slate-700">{business.crawl_tier || 'unknown'}</td>
                                    <td className="px-6 py-4 text-sm font-medium text-slate-700">{business.business_role || '-'}</td>
                                    <td className="px-6 py-4 text-sm font-semibold capitalize text-slate-700">{business.llm_fallback_decision || '-'}</td>
                                    <td className="max-w-xs px-6 py-4 text-sm text-slate-600">{business.crawl_reason || '-'}</td>
                                    <td className="max-w-xs px-6 py-4 text-sm text-slate-600">{business.llm_fallback_reason || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.industry_type || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.crawl_score ?? '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.llm_fallback_status || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.llm_fallback_confidence ?? '-'}</td>
                                    <td className="max-w-sm px-6 py-4 text-sm text-slate-600">{formatEvidence(business.crawl_evidence)}</td>
                                    <td className="max-w-xs px-6 py-4 text-sm text-slate-600">{formatEvidence(business.positive_concepts)}</td>
                                    <td className="max-w-xs px-6 py-4 text-sm text-slate-600">{formatEvidence(business.negative_concepts)}</td>
                                    <td className="max-w-xs px-6 py-4 text-sm text-slate-600">{business.business_role_reason || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.detected_language || '-'}</td>
                                    <td className="max-w-xs px-6 py-4 text-sm text-slate-600">{business.source_query || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.source_query_language || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-slate-600">{business.website_signal || '-'}</td>
                                    <td className="px-6 py-4 text-sm text-blue-600 hover:underline">
                                        {business.maps_url ? <a href={business.maps_url} target="_blank" rel="noreferrer">Maps</a> : '-'}
                                    </td>
                                </tr>
                            ))}
                            {filteredBusinesses.length === 0 && (
                                <tr>
                                    <td colSpan={DEFAULT_COLUMNS.length} className="px-6 py-8 text-center text-slate-500">{t('results.noBusinesses')}</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {showExportPicker && (
                <div className="fixed inset-0 z-20 flex items-center justify-center bg-slate-950/50 px-4">
                    <div className="w-full max-w-xl rounded-[2rem] bg-white p-6 shadow-2xl">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <h3 className="text-xl font-semibold text-slate-900">{t('results.customizeColumns')}</h3>
                                <p className="mt-1 text-sm text-slate-500">{t('results.chooseFields')}</p>
                            </div>
                            <button onClick={() => setShowExportPicker(false)} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="mt-6 grid gap-3 sm:grid-cols-2">
                            {DEFAULT_COLUMNS.map(column => (
                                <label key={column.key} className="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-700">
                                    <input type="checkbox" checked={selectedColumns.includes(column.key)} onChange={() => toggleColumn(column.key)} className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                                    {column.label}
                                </label>
                            ))}
                        </div>

                        <div className="mt-6 flex flex-wrap justify-end gap-3 border-t border-slate-200 pt-5">
                            <button onClick={() => handleDownload('csv')} className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                                <Download className="h-4 w-4" />
                                {t('results.csv')}
                            </button>
                            <button onClick={() => handleDownload('xlsx')} className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
                                <Download className="h-4 w-4" />
                                {t('results.excel')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
