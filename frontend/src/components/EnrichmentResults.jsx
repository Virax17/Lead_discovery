import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Download, Database, ExternalLink, MapPin, Search as SearchIcon } from 'lucide-react';
import { CompetitorBadge, customerTypeLabel, isCompetitor } from './leadShared';

const CATEGORY_LABELS = { competitor: 'Competitor', distributor: 'Distributor', ECP: 'EPC / Contractor', end_user: 'End user' };
const CATEGORY_STYLES = {
    competitor: 'bg-rose-100 text-rose-700',
    distributor: 'bg-amber-100 text-amber-700',
    ECP: 'bg-violet-100 text-violet-700',
    end_user: 'bg-emerald-100 text-emerald-700',
};
const TIER_STYLES = {
    best: 'bg-emerald-100 text-emerald-700',
    strong: 'bg-blue-100 text-blue-700',
    weak: 'bg-amber-100 text-amber-700',
    reject: 'bg-rose-100 text-rose-700',
    unknown: 'bg-slate-100 text-slate-600',
};
const TIER_ORDER = { best: 0, strong: 1, weak: 2, unknown: 3, reject: 4 };
const ROLE_LABELS = {
    end_user_operator: 'End-user operator',
    industrial_service_contractor: 'Service contractor',
    epc_contractor: 'EPC contractor',
    supplier_distributor: 'Supplier / distributor',
    competitor_manufacturer: 'Competitor',
    generic_local_service: 'Generic service',
    unknown: 'Unknown role',
};

export function CategoryChip({ value }) {
    if (!value) return null;
    return (
        <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${CATEGORY_STYLES[value] || 'bg-slate-100 text-slate-600'}`}>
            {CATEGORY_LABELS[value] || value}
        </span>
    );
}

function TierChip({ r }) {
    const tier = r.crawl_tier || 'unknown';
    return (
        <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${TIER_STYLES[tier] || TIER_STYLES.unknown}`}>
            {tier}{r.crawl_score != null ? ` · ${r.crawl_score}` : ''}
        </span>
    );
}

function Section({ title, count, children }) {
    return (
        <section>
            <h4 className="mb-2 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500">
                {title}{count != null && <span className="ml-1.5 font-semibold text-slate-400">{count}</span>}
            </h4>
            {children}
        </section>
    );
}

// "Product — why it fits" -> bold product + reason
function RelevanceItem({ text }) {
    const [product, ...rest] = String(text).split(/\s[—–-]\s/);
    return rest.length ? (
        <li><span className="font-semibold text-slate-900">{product}</span><span className="text-slate-600"> — {rest.join(' — ')}</span></li>
    ) : <li className="text-slate-700">{text}</li>;
}

// "Project name (2026)" -> name + year badge
function ProjectItem({ text }) {
    const m = String(text).match(/^(.*?)\s*\(([^)]*\d{4}[^)]*)\)\s*$/);
    return (
        <li className="flex items-start justify-between gap-3">
            <span className="text-slate-700">{m ? m[1] : text}</span>
            {m && <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-500">{m[2]}</span>}
        </li>
    );
}

function Fact({ label, children }) {
    if (!children) return null;
    return (
        <div className="min-w-0">
            <dt className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">{label}</dt>
            <dd className="mt-0.5 break-words text-sm text-slate-800">{children}</dd>
        </div>
    );
}

function Detail({ r }) {
    const [showAll, setShowAll] = useState(false);
    const desc = r.business_description || '';
    const long = desc.length > 260;
    const loc = [r.hq_city, r.country].filter(Boolean).join(', ');
    const socials = Object.entries(r.social_links || {});

    return (
        <div className="space-y-6 border-t border-slate-100 bg-slate-50/60 px-5 py-5">
            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
                <Fact label="Headquarters">{r.hq_address || loc}</Fact>
                <Fact label="Industry">{r.industry}</Fact>
                <Fact label="Employees">{r.employee_count ? `~${r.employee_count.toLocaleString()}` : null}</Fact>
                <Fact label="Email">{r.contact_emails?.join(', ')}</Fact>
                <Fact label="Phone">{r.contact_phones?.join(', ')}</Fact>
            </dl>

            {r.tritorc_relevance?.length > 0 && (
                <Section title="Why it fits Tritorc" count={r.tritorc_relevance.length}>
                    <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed marker:text-blue-400">
                        {r.tritorc_relevance.map((t, i) => <RelevanceItem key={i} text={t} />)}
                    </ul>
                </Section>
            )}

            {desc && (
                <Section title="About">
                    <p className={`max-w-3xl text-sm leading-relaxed text-slate-700 ${long && !showAll ? 'line-clamp-3' : ''}`}>{desc}</p>
                    {long && (
                        <button onClick={() => setShowAll((v) => !v)} className="mt-1 text-xs font-semibold text-blue-600 hover:underline">
                            {showAll ? 'Show less' : 'Show more'}
                        </button>
                    )}
                </Section>
            )}

            {r.key_operations?.length > 0 && (
                <Section title="Operations" count={r.key_operations.length}>
                    <div className="flex flex-wrap gap-2">
                        {r.key_operations.map((o, i) => (
                            <span key={i} className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700">{o}</span>
                        ))}
                    </div>
                </Section>
            )}

            {r.projects_or_recent_activity?.length > 0 && (
                <Section title="Recent activity" count={r.projects_or_recent_activity.length}>
                    <ul className="space-y-2 text-sm">
                        {r.projects_or_recent_activity.map((p, i) => <ProjectItem key={i} text={p} />)}
                    </ul>
                </Section>
            )}

            {r.crawl_tier && (
                <Section title="Fit assessment">
                    {r.business_role && <span className="mb-2 inline-flex rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-700">{ROLE_LABELS[r.business_role] || r.business_role}</span>}
                    <p className="text-sm text-slate-600">{r.business_role_reason || r.crawl_reason}</p>
                    {r.crawl_evidence?.length > 0 && (
                        <details className="mt-2 text-sm text-slate-600">
                            <summary className="cursor-pointer text-xs font-semibold text-blue-600">Evidence ({r.crawl_evidence.length})</summary>
                            <ul className="mt-2 list-disc space-y-1 pl-5">
                                {r.crawl_evidence.map((ev, i) => (
                                    <li key={i}>{ev}{r.crawl_evidence_urls?.[i] && <> <a href={r.crawl_evidence_urls[i]} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">source</a></>}</li>
                                ))}
                            </ul>
                        </details>
                    )}
                </Section>
            )}

            {socials.length > 0 && (
                <Section title="Links">
                    <div className="flex flex-wrap gap-4 text-sm">
                        {r.website && <a href={r.website} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:underline">Website <ExternalLink className="h-3 w-3" /></a>}
                        {socials.map(([k, v]) => <a key={k} href={v} target="_blank" rel="noreferrer" className="capitalize text-blue-600 hover:underline">{k}</a>)}
                    </div>
                </Section>
            )}
        </div>
    );
}

const ROW_GRID = 'md:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_116px_96px_120px_116px]';

export function RowHeader() {
    return (
        <div className={`hidden gap-x-4 px-5 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400 md:grid ${ROW_GRID}`}>
            <span className="pl-7">Company · Source</span><span>Address</span><span>Phone</span><span>Crawl tier</span><span>LLM decision</span><span>Customer type</span>
        </div>
    );
}

export function Row({ r, open, onToggle }) {
    const loc = [r.hq_city, r.country].filter(Boolean).join(', ');
    const address = r.hq_address || loc;
    const firstFit = r.tritorc_relevance?.[0];
    const [fitProduct] = firstFit ? String(firstFit).split(/\s[—–-]\s/) : [];
    const firstProject = r.projects_or_recent_activity?.[0];
    const competitor = isCompetitor(r);
    return (
        <li className={competitor ? 'bg-rose-50/60' : 'bg-white'}>
            <button
                onClick={onToggle}
                aria-expanded={open}
                className={`grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 px-5 py-3.5 text-left transition-colors hover:bg-slate-50 ${ROW_GRID}`}
            >
                <div className="flex min-w-0 items-center gap-3">
                    {open ? <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />}
                    <div className="min-w-0">
                        <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-slate-900">{r.company_name || r.input}</span>
                            <CompetitorBadge r={r} />
                            {r.cache_hit && <span title="Served from the stored crawl — no re-crawl"><Database className="h-3.5 w-3.5 shrink-0 text-blue-500" /></span>}
                        </div>
                        {r.error ? (
                            <div className="truncate text-xs text-rose-600" title={r.business_description}>{r.business_description}</div>
                        ) : (
                            <div className="truncate text-xs text-slate-500">
                                Enrichment · {r.domain || r.website || '—'}{r.industry ? ` · ${r.industry}` : ''}
                                {r.crawl_status && r.crawl_status !== 'ok' && <span className="text-amber-600"> · site could not be crawled</span>}
                            </div>
                        )}
                    </div>
                </div>
                <div className="hidden min-w-0 items-center justify-self-start gap-1 text-sm text-slate-600 md:flex" title={address}>
                    {address && <><MapPin className="h-3.5 w-3.5 shrink-0 text-slate-400" /><span className="truncate">{address}</span></>}
                </div>
                <div className="hidden min-w-0 truncate text-sm text-slate-600 md:block" title={r.contact_phones?.join(', ')}>
                    {r.contact_phones?.[0] || <span className="text-slate-300">—</span>}
                </div>
                <div className="flex items-center gap-2 justify-self-end md:justify-self-auto">
                    <TierChip r={r} />
                </div>
                <div className="hidden md:block"><CategoryChip value={r.company_category} /></div>
                <div className="hidden truncate text-sm text-slate-700 md:block">{customerTypeLabel(r.business_role)}</div>
                {(fitProduct || firstProject) && (
                    <div className="col-span-full grid gap-x-6 gap-y-0.5 pl-7 text-xs text-slate-500 md:grid-cols-2">
                        {fitProduct && <div className="truncate"><span className="font-semibold text-slate-600">Fits: </span>{fitProduct}</div>}
                        {firstProject && <div className="truncate"><span className="font-semibold text-slate-600">Recent: </span>{firstProject}</div>}
                    </div>
                )}
            </button>
            {open && <Detail r={r} />}
        </li>
    );
}

const FILTERS = ['all', 'best', 'strong', 'weak', 'unknown', 'reject'];
const SORTS = {
    fit: { label: 'Best fit first', fn: (a, b) => (TIER_ORDER[a.crawl_tier ?? 'unknown'] - TIER_ORDER[b.crawl_tier ?? 'unknown']) || ((b.crawl_score ?? -1) - (a.crawl_score ?? -1)) },
    name: { label: 'Name A–Z', fn: (a, b) => String(a.company_name || a.input).localeCompare(String(b.company_name || b.input)) },
    country: { label: 'Country', fn: (a, b) => String(a.country || '~').localeCompare(String(b.country || '~')) },
};

export default function EnrichmentResults({ results, onExport }) {
    const [filter, setFilter] = useState('all');
    const [sort, setSort] = useState('fit');
    const [q, setQ] = useState('');
    const [openKeys, setOpenKeys] = useState(() => new Set());

    const keyOf = (r, i) => `${r.input}-${i}`;
    const indexed = useMemo(() => results.map((r, i) => ({ r, k: keyOf(r, i) })), [results]);

    const counts = useMemo(() => {
        const c = { all: results.length };
        results.forEach((r) => { const t = r.crawl_tier || 'unknown'; c[t] = (c[t] || 0) + 1; });
        return c;
    }, [results]);

    const visible = useMemo(() => {
        const needle = q.trim().toLowerCase();
        return indexed
            .filter(({ r }) => filter === 'all' || (r.crawl_tier || 'unknown') === filter)
            .filter(({ r }) => !needle || [r.company_name, r.domain, r.country, r.industry, r.input].some((v) => String(v || '').toLowerCase().includes(needle)))
            .sort((a, b) => SORTS[sort].fn(a.r, b.r));
    }, [indexed, filter, sort, q]);

    const toggle = (k) => setOpenKeys((prev) => {
        const next = new Set(prev);
        if (next.has(k)) next.delete(k); else next.add(k);
        return next;
    });
    const allOpen = visible.length > 0 && visible.every(({ k }) => openKeys.has(k));

    return (
        <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold text-slate-900">Results <span className="text-slate-400">({results.length})</span></h2>
                <button onClick={onExport} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
                    <Download className="h-4 w-4" /> Excel
                </button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
                {FILTERS.filter((f) => f === 'all' || counts[f]).map((f) => (
                    <button
                        key={f}
                        onClick={() => setFilter(f)}
                        className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize transition-colors ${filter === f ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}
                    >
                        {f} <span className={filter === f ? 'text-blue-100' : 'text-slate-400'}>{counts[f] || 0}</span>
                    </button>
                ))}
                <div className="ml-auto flex flex-wrap items-center gap-2">
                    <div className="relative">
                        <SearchIcon className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
                        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className="w-36 rounded-lg border border-slate-300 py-1.5 pl-8 pr-2 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                    </div>
                    <select value={sort} onChange={(e) => setSort(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700">
                        {Object.entries(SORTS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
                    </select>
                    <button
                        onClick={() => setOpenKeys(allOpen ? new Set() : new Set(visible.map(({ k }) => k)))}
                        className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                        {allOpen ? 'Collapse all' : 'Expand all'}
                    </button>
                </div>
            </div>

            <RowHeader />
            <ul className="divide-y divide-slate-200 overflow-hidden rounded-2xl border border-slate-200 shadow-sm">
                {visible.map(({ r, k }) => <Row key={k} r={r} open={openKeys.has(k)} onToggle={() => toggle(k)} />)}
                {visible.length === 0 && <li className="bg-white px-5 py-8 text-center text-sm text-slate-500">No companies match this filter.</li>}
            </ul>
        </section>
    );
}
