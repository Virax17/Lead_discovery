import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createSearch, fetchQuota } from '../api';
import { ChevronRight, Plus, X, Sparkles, ShieldAlert } from 'lucide-react';

const DEFAULT_KEYWORDS = [
    'Shutdown contractor',
    'Mechanical specialist contractor',
    'Maintenance contractor',
    'Hydraulic torque wrench supplier',
    'Hydraulic bolt tensioner supplier',
    'Torque test service',
    'Nipple up nipple down service',
    'BOP service',
    'Artificial lift service',
    'Drilling contractor',
    'Pipeline integrity contractor'
];

const DEFAULT_INDUSTRIES = [
    'Oil and gas',
    'Wind energy',
    'Power',
    'Heavy engineering',
    'Turbine manufacturing',
    'Construction'
];

function TagEditor({ label, items, setItems, placeholder }) {
    const [draft, setDraft] = useState('');

    const addItem = () => {
        const value = draft.trim();
        if (!value) return;
        if (items.some(item => item.toLowerCase() === value.toLowerCase())) {
            setDraft('');
            return;
        }
        setItems([...items, value]);
        setDraft('');
    };

    return (
        <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-700">{label}</label>
            <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
                {items.map(item => (
                    <span key={item} className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-1 text-sm text-white">
                        {item}
                        <button type="button" onClick={() => setItems(items.filter(existing => existing !== item))} className="text-white/70 hover:text-white">
                            <X className="h-3 w-3" />
                        </button>
                    </span>
                ))}
                <input
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            addItem();
                        }
                    }}
                    placeholder={placeholder}
                    className="min-w-[220px] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-slate-400"
                />
                <button
                    type="button"
                    onClick={addItem}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-sm font-medium text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                >
                    <Plus className="h-3 w-3" />
                    Add
                </button>
            </div>
        </div>
    );
}

export default function Dashboard() {
    const navigate = useNavigate();
    const [step, setStep] = useState('setup');
    const [country, setCountry] = useState('India');
    const [countryCode, setCountryCode] = useState('IN');
    const [state, setState] = useState('');
    const [city, setCity] = useState('');
    const [maxResults, setMaxResults] = useState(100);
    const [websiteOnly, setWebsiteOnly] = useState(true);
    const [keywords, setKeywords] = useState(DEFAULT_KEYWORDS);
    const [industries, setIndustries] = useState(DEFAULT_INDUSTRIES);
    const [quota, setQuota] = useState(null);
    const [loading, setLoading] = useState(false);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        fetchQuota().then(setQuota).catch(() => setQuota(null));
    }, []);

    const quotaPlan = String(quota?.active_plan || 'free').replace(/_/g, ' ');
    const quotaUsed = quota?.calls_used ?? 0;
    const quotaLimit = quota?.quota_block_threshold ?? 1000;
    const quotaOverage = quota?.overage_cost_estimate ?? 0;
    const estimatedCalls = useMemo(() => keywords.length * Number(maxResults || 0), [keywords.length, maxResults]);
    const projectedUsage = (quota?.calls_used ?? 0) + estimatedCalls;
    const projectedOverage = quota ? Math.max(0, projectedUsage - quotaLimit) : 0;
    const searchWouldBlock = quota ? !quota.allow_paid_overage && projectedUsage > quotaLimit : false;

    const payload = {
        country,
        country_code: countryCode.trim().toUpperCase(),
        state: state || null,
        city: city || null,
        max_results: Number(maxResults),
        keywords,
        industries,
        website_only: websiteOnly
    };

    const reviewSearch = (e) => {
        e.preventDefault();
        setError('');
        if (!countryCode.trim() || countryCode.trim().length !== 2) {
            setError('Country code must be a 2-letter ISO code.');
            return;
        }
        if (keywords.length === 0) {
            setError('Add at least one keyword.');
            return;
        }
        if (industries.length === 0) {
            setError('Add at least one industry type.');
            return;
        }
        setPreviewLoading(true);
        setStep('preview');
        setPreviewLoading(false);
    };

    const startSearch = async () => {
        setError('');
        setLoading(true);
        try {
            const data = await createSearch(payload);
            navigate(`/search/${data.search_id}/progress`);
        } catch (err) {
            setError(err.message || 'Failed to start search');
            setLoading(false);
        }
    };

    return (
        <div className="mx-auto max-w-6xl space-y-6">
            <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_20px_80px_rgba(15,23,42,0.08)]">
                <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_55%,#38bdf8_100%)] px-8 py-10 text-white">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                            <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-white/90">
                                <Sparkles className="h-3 w-3" />
                                Lead Discovery Setup
                            </p>
                            <h2 className="text-4xl font-semibold tracking-tight">Build a regional search in two steps.</h2>
                            <p className="mt-3 max-w-2xl text-sm text-slate-100/90">
                                Define the search scope, review the estimated quota impact, then confirm the run.
                            </p>
                        </div>
                        <div className="rounded-3xl border border-white/20 bg-white/10 p-5 backdrop-blur">
                            <p className="text-xs uppercase tracking-[0.2em] text-white/70">Quota snapshot</p>
                            {quota ? (
                                <div className="mt-3 space-y-2 text-sm text-white">
                                    <div className="flex items-center justify-between gap-6">
                                        <span>Plan</span>
                                        <span className="font-semibold capitalize">{quotaPlan}</span>
                                    </div>
                                    <div className="flex items-center justify-between gap-6">
                                        <span>Used</span>
                                        <span className="font-semibold">{quotaUsed} / {quotaLimit}</span>
                                    </div>
                                    <div className="flex items-center justify-between gap-6">
                                        <span>Overage</span>
                                        <span className="font-semibold">${quotaOverage.toFixed(2)} est.</span>
                                    </div>
                                </div>
                            ) : (
                                <p className="mt-3 text-sm text-white/80">Loading quota snapshot...</p>
                            )}
                        </div>
                    </div>
                </div>

                <div className="grid gap-0 xl:grid-cols-[1.3fr_0.9fr]">
                    <div className="p-8">
                        {error && (
                            <div className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                                {error}
                            </div>
                        )}

                        {step === 'setup' ? (
                            <form onSubmit={reviewSearch} className="space-y-6">
                                <div className="grid gap-4 sm:grid-cols-2">
                                    <div>
                                        <label className="block text-sm font-medium text-slate-700">Country *</label>
                                        <input required type="text" value={country} onChange={e => setCountry(e.target.value)} className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:bg-white" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-700">Country code *</label>
                                        <input required maxLength={2} value={countryCode} onChange={e => setCountryCode(e.target.value.toUpperCase())} className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm uppercase outline-none transition focus:border-blue-500 focus:bg-white" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-700">State / Region</label>
                                        <input type="text" value={state} onChange={e => setState(e.target.value)} className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:bg-white" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-700">City</label>
                                        <input type="text" value={city} onChange={e => setCity(e.target.value)} className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:bg-white" />
                                    </div>
                                </div>

                                <div className="grid gap-4 sm:grid-cols-2">
                                    <div>
                                        <label className="block text-sm font-medium text-slate-700">Max Results per keyword</label>
                                        <input type="number" min="1" max="500" value={maxResults} onChange={e => setMaxResults(parseInt(e.target.value || '0', 10))} className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:bg-white" />
                                    </div>
                                    <div className="flex items-end">
                                        <label className="flex w-full items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700">
                                            <span>Website only</span>
                                            <input type="checkbox" checked={websiteOnly} onChange={e => setWebsiteOnly(e.target.checked)} className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                                        </label>
                                    </div>
                                </div>

                                <TagEditor
                                    label="Keywords"
                                    items={keywords}
                                    setItems={setKeywords}
                                    placeholder="Add a keyword and press Enter"
                                />

                                <TagEditor
                                    label="Industry Types"
                                    items={industries}
                                    setItems={setIndustries}
                                    placeholder="Add an industry and press Enter"
                                />

                                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                                    Estimated place details calls: <span className="font-semibold text-slate-900">{estimatedCalls.toLocaleString()}</span>
                                    {quota && (
                                        <span className="ml-3">
                                            Projected overage: <span className="font-semibold text-slate-900">{projectedOverage.toLocaleString()}</span>
                                        </span>
                                    )}
                                </div>

                                <div className="flex items-center justify-between gap-4 border-t border-slate-200 pt-6">
                                    <p className="text-sm text-slate-500">Step 1 of 2: review the search scope before starting.</p>
                                    <button type="submit" disabled={previewLoading} className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60">
                                        Review Summary
                                        <ChevronRight className="h-4 w-4" />
                                    </button>
                                </div>
                            </form>
                        ) : (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between gap-4">
                                    <div>
                                        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Preview Summary</p>
                                        <h3 className="mt-2 text-2xl font-semibold text-slate-900">Confirm the search before launch</h3>
                                    </div>
                                    <button type="button" onClick={() => setStep('setup')} className="rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                                        Back to Setup
                                    </button>
                                </div>

                                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                                    <SummaryCard label="Region" value={`${country}${countryCode ? ` (${countryCode})` : ''}`} />
                                    <SummaryCard label="Scope" value={`${state || 'Any state'} · ${city || 'Any city'}`} />
                                    <SummaryCard label="Website filter" value={websiteOnly ? 'Enabled' : 'Disabled'} />
                                    <SummaryCard label="Keywords" value={`${keywords.length} selected`} />
                                    <SummaryCard label="Industry types" value={`${industries.length} selected`} />
                                    <SummaryCard label="Max results" value={`${maxResults} per keyword`} />
                                </div>

                                <div className="grid gap-4 rounded-3xl border border-slate-200 bg-slate-50 p-5 sm:grid-cols-2">
                                    <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Quota impact</p>
                                        <p className="mt-2 text-lg font-semibold text-slate-900">{estimatedCalls.toLocaleString()} estimated place details calls</p>
                                        <p className="mt-1 text-sm text-slate-600">This is based on {keywords.length} keywords multiplied by {maxResults} max results each.</p>
                                    </div>
                                    <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Projected usage</p>
                                        <p className="mt-2 text-lg font-semibold text-slate-900">{projectedUsage.toLocaleString()} / {quota ? quota.quota_block_threshold.toLocaleString() : '1,000'}</p>
                                        <p className={`mt-1 text-sm ${searchWouldBlock ? 'text-rose-700' : 'text-slate-600'}`}>
                                            {searchWouldBlock ? 'This run would exceed the free limit with overage disabled.' : 'The run fits within the current quota settings.'}
                                        </p>
                                    </div>
                                </div>

                                <div className="rounded-3xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
                                    <div className="flex items-start gap-3">
                                        <ShieldAlert className="mt-0.5 h-5 w-5 text-amber-700" />
                                        <div>
                                            <p className="font-semibold">Before starting</p>
                                            <p className="mt-1 text-amber-800">The backend will stop on quota block when paid overage is disabled, and website-only searches will skip businesses without a website.</p>
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between gap-4 border-t border-slate-200 pt-6">
                                    <p className="text-sm text-slate-500">Step 2 of 2: confirm the search and launch it.</p>
                                    <button type="button" onClick={startSearch} disabled={loading} className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60">
                                        {loading ? 'Starting Search...' : 'Confirm and Start'}
                                        <ChevronRight className="h-4 w-4" />
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>

                    <aside className="border-t border-slate-200 bg-slate-50/80 p-8 xl:border-l xl:border-t-0">
                        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Search Defaults</p>
                        <div className="mt-4 space-y-3 text-sm text-slate-600">
                            <p>11 heavy industrial keywords are preloaded so the search starts from the new brief.</p>
                            <p>6 industry types are available as chips and can be edited inline before launch.</p>
                            <p>Exports can be customized later from the results screen with a column selector.</p>
                        </div>
                    </aside>
                </div>
            </div>
        </div>
    );
}

function SummaryCard({ label, value }) {
    return (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{label}</p>
            <p className="mt-2 text-sm font-medium text-slate-900">{value}</p>
        </div>
    );
}
