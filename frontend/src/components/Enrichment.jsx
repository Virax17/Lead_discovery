import React, { useEffect, useRef, useState } from 'react';
import { Sparkles, Upload, Download, Square, Loader2, Database, ExternalLink, RefreshCw, Search as SearchIcon } from 'lucide-react';
import { parseEnrichmentFile, streamEnrichment, fetchEnrichments, downloadEnrichmentXlsx } from '../api';

const CATEGORY_LABELS = { distributor: 'Distributor', ECP: 'EPC / Contractor', end_user: 'End user' };
const CATEGORY_STYLES = {
    distributor: 'bg-amber-100 text-amber-700',
    ECP: 'bg-violet-100 text-violet-700',
    end_user: 'bg-emerald-100 text-emerald-700',
};

function CategoryChip({ value }) {
    if (!value) return null;
    return (
        <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${CATEGORY_STYLES[value] || 'bg-slate-100 text-slate-600'}`}>
            {CATEGORY_LABELS[value] || value}
        </span>
    );
}

const TIER_STYLES = {
    best: 'bg-emerald-100 text-emerald-700',
    strong: 'bg-blue-100 text-blue-700',
    weak: 'bg-amber-100 text-amber-700',
    reject: 'bg-rose-100 text-rose-700',
    unknown: 'bg-slate-100 text-slate-600',
};

const ROLE_LABELS = {
    end_user_operator: 'End-user operator',
    industrial_service_contractor: 'Service contractor',
    epc_contractor: 'EPC contractor',
    supplier_distributor: 'Supplier / distributor',
    competitor_manufacturer: 'Competitor',
    generic_local_service: 'Generic service',
    unknown: 'Unknown role',
};

function ListBlock({ title, items }) {
    if (!items?.length) return null;
    return (
        <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
                {items.map((it, i) => <li key={i}>{it}</li>)}
            </ul>
        </div>
    );
}

function CompanyCard({ r }) {
    return (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold text-slate-900">{r.company_name || r.input}</h3>
                    {r.website && (
                        <a href={r.website} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline">
                            {r.domain || r.website} <ExternalLink className="h-3 w-3" />
                        </a>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {r.cache_hit && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700" title="Served from the stored crawl — no re-crawl">
                            <Database className="h-3 w-3" /> Stored
                        </span>
                    )}
                    <CategoryChip value={r.company_category} />
                </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                {(r.hq_city || r.country) && <span>{[r.hq_city, r.country].filter(Boolean).join(', ')}</span>}
                {r.industry && <span>{r.industry}</span>}
            </div>
            {r.crawl_tier && (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <span className={`inline-flex rounded-full px-2.5 py-0.5 font-semibold capitalize ${TIER_STYLES[r.crawl_tier] || TIER_STYLES.unknown}`}>
                        Fit: {r.crawl_tier}{r.crawl_score != null ? ` · ${r.crawl_score}` : ''}
                    </span>
                    {r.business_role && <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-semibold text-slate-600">{ROLE_LABELS[r.business_role] || r.business_role}</span>}
                    {r.business_role_reason && <span className="text-slate-500">{r.business_role_reason}</span>}
                </div>
            )}
            {r.business_description && <p className="mt-3 text-sm text-slate-700">{r.business_description}</p>}
            <div className="mt-4 grid gap-4 md:grid-cols-3">
                <ListBlock title="Key operations" items={r.key_operations} />
                <ListBlock title="Projects & activity" items={r.projects_or_recent_activity} />
                <ListBlock title="Tritorc relevance" items={r.tritorc_relevance} />
            </div>
            {(r.contact_emails?.length > 0 || r.contact_phones?.length > 0 || r.hq_address || Object.keys(r.social_links || {}).length > 0) && (
                <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Contact</div>
                    <div className="mt-1 space-y-0.5">
                        {r.hq_address && <div>{r.hq_address}</div>}
                        {r.contact_emails?.length > 0 && <div>{r.contact_emails.join(', ')}</div>}
                        {r.contact_phones?.length > 0 && <div>{r.contact_phones.join(', ')}</div>}
                        {Object.keys(r.social_links || {}).length > 0 && (
                            <div className="flex flex-wrap gap-3">
                                {Object.entries(r.social_links).map(([k, v]) => (
                                    <a key={k} href={v} target="_blank" rel="noreferrer" className="capitalize text-blue-600 hover:underline">{k}</a>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
            {r.crawl_evidence?.length > 0 && (
                <details className="mt-3 text-sm text-slate-600">
                    <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">Fit evidence ({r.crawl_evidence.length})</summary>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        {r.crawl_evidence.map((ev, i) => (
                            <li key={i}>{ev}{r.crawl_evidence_urls?.[i] && <> <a href={r.crawl_evidence_urls[i]} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">source</a></>}</li>
                        ))}
                    </ul>
                </details>
            )}
        </div>
    );
}

export default function Enrichment() {
    const [text, setText] = useState('');
    const [forceRefresh, setForceRefresh] = useState(false);
    const [running, setRunning] = useState(false);
    const [progress, setProgress] = useState(null); // {index,total,company}
    const [results, setResults] = useState([]);
    const [error, setError] = useState('');
    const [stored, setStored] = useState({ total: 0, items: [] });
    const [query, setQuery] = useState('');
    const abortRef = useRef(null);
    const fileRef = useRef(null);

    const loadStored = async (q = query) => {
        try {
            setStored(await fetchEnrichments({ q }));
        } catch (e) {
            setError(e.message);
        }
    };

    useEffect(() => { loadStored(''); /* eslint-disable-next-line */ }, []);

    const handleFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        try {
            const names = await parseEnrichmentFile(file);
            setText((prev) => [prev.trim(), ...names].filter(Boolean).join('\n'));
        } catch (err) {
            setError(err.message);
        }
    };

    const start = async () => {
        const companies = text.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
        if (!companies.length) return;
        setError('');
        setResults([]);
        setRunning(true);
        setProgress({ index: 0, total: companies.length, company: '' });
        const controller = new AbortController();
        abortRef.current = controller;
        try {
            await streamEnrichment(companies, forceRefresh, (ev) => {
                if (ev.type === 'error') setError(ev.message);
                else if (ev.type === 'progress') setProgress({ index: ev.index, total: ev.total, company: ev.company, status: ev.status });
                else if (ev.type === 'complete') setResults(ev.results);
            }, controller.signal);
        } catch (err) {
            if (err.name !== 'AbortError') setError(err.message);
        } finally {
            setRunning(false);
            abortRef.current = null;
            loadStored();
        }
    };

    const stop = () => abortRef.current?.abort();

    const pct = progress?.total ? Math.round(((progress.status === 'done' ? progress.index : progress.index - 1) / progress.total) * 100) : 0;

    return (
        <div className="space-y-8">
            <div>
                <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
                    <Sparkles className="h-6 w-6 text-blue-600" /> Company Enrichment
                </h1>
                <p className="mt-1 text-sm text-slate-500">
                    Paste company names, websites or work emails. Each is crawled and profiled for Tritorc fit, then stored so it is never crawled twice.
                </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                    <label htmlFor="companies" className="text-sm font-semibold text-slate-800">Companies (one per line)</label>
                    <div>
                        <input ref={fileRef} type="file" accept=".txt,.csv,.xlsx,.xlsm,.json" onChange={handleFile} className="hidden" />
                        <button onClick={() => fileRef.current?.click()} disabled={running} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                            <Upload className="h-4 w-4" /> Upload CSV / XLSX / JSON
                        </button>
                    </div>
                </div>
                <textarea
                    id="companies"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    disabled={running}
                    rows={6}
                    placeholder={'Bilfinger SE\nshell.com\nprocurement@aramco.com'}
                    className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <label className="inline-flex items-center gap-2 text-sm text-slate-600">
                        <input type="checkbox" checked={forceRefresh} onChange={(e) => setForceRefresh(e.target.checked)} disabled={running} className="h-4 w-4 rounded border-slate-300 text-blue-600" />
                        <RefreshCw className="h-3.5 w-3.5" /> Re-crawl even if already stored
                    </label>
                    {running ? (
                        <button onClick={stop} className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700">
                            <Square className="h-4 w-4" /> Stop
                        </button>
                    ) : (
                        <button onClick={start} disabled={!text.trim()} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50">
                            <Sparkles className="h-4 w-4" /> Enrich
                        </button>
                    )}
                </div>

                {running && progress && (
                    <div className="mt-5">
                        <div className="flex items-center justify-between text-sm text-slate-600">
                            <span className="inline-flex items-center gap-2 truncate"><Loader2 className="h-4 w-4 animate-spin text-blue-600" /> {progress.company || 'Starting…'}</span>
                            <span>{progress.index} / {progress.total}</span>
                        </div>
                        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                            <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${pct}%` }} />
                        </div>
                    </div>
                )}
                {error && <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
            </div>

            {results.length > 0 && (
                <section className="space-y-4">
                    <div className="flex items-center justify-between">
                        <h2 className="text-lg font-semibold text-slate-900">Results ({results.length})</h2>
                        <button onClick={() => downloadEnrichmentXlsx(results).catch((e) => setError(e.message))} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
                            <Download className="h-4 w-4" /> Excel
                        </button>
                    </div>
                    {results.map((r, i) => <CompanyCard key={`${r.input}-${i}`} r={r} />)}
                </section>
            )}

            <section className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
                        <Database className="h-5 w-5 text-slate-500" /> Stored enrichments ({stored.total})
                    </h2>
                    <form onSubmit={(e) => { e.preventDefault(); loadStored(query); }} className="relative">
                        <SearchIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name, domain, industry…" className="w-64 rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                    </form>
                </div>
                <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                    {stored.items.length === 0 ? (
                        <div className="px-6 py-10 text-center text-sm text-slate-500">Nothing stored yet.</div>
                    ) : (
                        <ul className="divide-y divide-slate-200">
                            {stored.items.map((it) => (
                                <li key={it.id} className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 hover:bg-slate-50">
                                    <div className="min-w-0">
                                        <div className="truncate text-sm font-medium text-slate-900">{it.company_name}</div>
                                        <div className="truncate text-xs text-slate-500">{[it.domain, it.country, it.industry].filter(Boolean).join(' · ')}</div>
                                    </div>
                                    <div className="flex items-center gap-3 text-xs text-slate-500">
                                        <CategoryChip value={it.company_category} />
                                        <span>{it.pages_crawled} pages</span>
                                        <span>{it.last_crawled_at ? new Date(it.last_crawled_at).toLocaleDateString() : ''}</span>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </section>
        </div>
    );
}
