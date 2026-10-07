import React, { useMemo, useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight, Download, Database, ExternalLink, Loader2, MapPin, RefreshCw, Search as SearchIcon } from 'lucide-react';
import { CompetitorBadge, TurnoverChip, VerdictChip, crawlProblem, customerTypeLabel, llmVerdict } from './leadShared';
import { correctEnrichment, enrichSingle, setEnrichmentOverride } from '../api';

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
    weak: 'bg-orange-100 text-orange-700',
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
        <div className="flex flex-col items-start gap-0.5">
            <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${TIER_STYLES[tier] || TIER_STYLES.unknown}`}>
                {tier}
            </span>
            {r.crawl_score != null && <span className="pl-1 text-[11px] text-slate-400" title="Crawler fit score, 0 to 100"><span className="md:hidden">Crawler s</span><span className="hidden md:inline">S</span>core {r.crawl_score}</span>}
        </div>
    );
}

function Section({ title, hint, children }) {
    return (
        <section>
            <h4 className="mb-3 flex items-baseline gap-2 text-base font-semibold text-slate-900">
                {title}{hint != null && <span className="text-sm font-normal text-slate-400">{hint}</span>}
            </h4>
            {children}
        </section>
    );
}

// "Product — why it fits" -> a small card: bold product, plain-language reason underneath
function FitCard({ text }) {
    const [product, ...rest] = String(text).split(/\s[—–-]\s/);
    return (
        <li className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="text-[15px] font-semibold text-slate-900">{product}</div>
            {rest.length > 0 && <div className="mt-0.5 text-sm leading-relaxed text-slate-600">{rest.join(' — ')}</div>}
        </li>
    );
}

// "Project name (2026)" -> year on the left, project on the right
function ProjectItem({ text }) {
    const m = String(text).match(/^(.*?)\s*\(([^)]*\d{4}[^)]*)\)\s*$/);
    const year = m ? m[2].match(/\d{4}/)?.[0] : null;
    return (
        <li className="flex gap-4">
            <span className="w-11 shrink-0 pt-0.5 text-sm font-semibold tabular-nums text-slate-400">{year || '—'}</span>
            <span className="text-[15px] leading-relaxed text-slate-700">{m ? m[1] : text}</span>
        </li>
    );
}

function FactRow({ label, children }) {
    if (!children) return null;
    return (
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 py-2.5 text-sm first:pt-0 last:pb-0">
            <dt className="text-slate-500">{label}</dt>
            <dd className="min-w-0 break-words font-medium text-slate-900">{children}</dd>
        </div>
    );
}

const linkCls = 'text-blue-600 hover:underline';

function FactsCard({ r }) {
    const loc = [r.hq_city, r.country].filter(Boolean).join(', ');
    const socials = Object.entries(r.social_links || {});
    const turnover = r.turnover_class
        ? `Class ${r.turnover_class}${r.annual_turnover ? ` (${r.annual_turnover})` : ''}${r.turnover_basis === 'stated' ? '' : ` · estimated from ${String(r.turnover_basis || 'size').replace('estimated from ', '')}`}`
        : null;
    return (
        <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white p-4">
            <FactRow label="Headquarters">{r.hq_address || loc}</FactRow>
            <FactRow label="Industry">{r.industry}</FactRow>
            <FactRow label="Customer type">{customerTypeLabel(r.business_role, r.company_category)}</FactRow>
            <FactRow label="Turnover">{turnover}</FactRow>
            <FactRow label="Employees">{r.employee_count ? `About ${r.employee_count.toLocaleString()}` : null}</FactRow>
            <FactRow label="Email">
                {r.contact_emails?.length ? <div className="space-y-0.5">{r.contact_emails.map((e) => <div key={e}><a href={`mailto:${e}`} className={linkCls}>{e}</a></div>)}</div> : null}
            </FactRow>
            <FactRow label="Phone">
                {r.contact_phones?.length ? <div className="space-y-0.5">{r.contact_phones.map((p) => <div key={p}><a href={`tel:${p.replace(/\s+/g, '')}`} className={linkCls}>{p}</a></div>)}</div> : null}
            </FactRow>
            <FactRow label="Website">
                {r.website ? <a href={r.website} target="_blank" rel="noreferrer" className={`inline-flex items-center gap-1 ${linkCls}`}>{r.domain || r.website} <ExternalLink className="h-3 w-3" /></a> : null}
            </FactRow>
            <FactRow label="Social">
                {socials.length ? <div className="flex flex-wrap gap-x-3">{socials.map(([k, v]) => <a key={k} href={v} target="_blank" rel="noreferrer" className={`capitalize ${linkCls}`}>{k}</a>)}</div> : null}
            </FactRow>
        </dl>
    );
}

const BANNERS = {
    accept: { box: 'border-emerald-300 bg-emerald-50', text: 'text-emerald-800', label: 'Accept', sub: 'Worth pursuing' },
    review: { box: 'border-yellow-300 bg-yellow-50', text: 'text-yellow-800', label: 'Review', sub: 'Needs a human look' },
    reject: { box: 'border-rose-300 bg-rose-50', text: 'text-rose-800', label: 'Reject', sub: 'Not a fit' },
    unjudged: { box: 'border-slate-300 bg-slate-50', text: 'text-slate-700', label: 'Not judged yet', sub: 'Only the keyword check has looked at this' },
};

// The answer first: decision, the reason in one sentence, and the two facts people ask next.
function VerdictBanner({ r, onUpdate }) {
    const v = llmVerdict(r);
    if (!v) return null;
    const b = BANNERS[v.key];
    const reason = v.override
        ? (r.override_note || 'You made this decision yourself.')
        : r.llm_decision_reason || (v.key === 'unjudged' ? `The AI hasn't judged this company for ${r.profile_name || 'Tritorc'} yet. It reuses the saved crawl, so it only takes a moment.` : null);
    return (
        <div className={`rounded-xl border p-4 ${b.box}`}>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span className={`text-xl font-semibold ${b.text}`}>{b.label}</span>
                <span className={`text-sm font-medium opacity-80 ${b.text}`}>{v.override ? 'Your decision' : b.sub}</span>
            </div>
            {reason && <p className="mt-2 text-[15px] leading-relaxed text-slate-800">{reason}</p>}
            {v.key === 'unjudged' && r.profile_name && onUpdate && (
                <div className="mt-3"><RetryButton r={r} onUpdate={onUpdate} label={`Get the ${r.profile_name} decision`} /></div>
            )}
            <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-slate-600">
                <span>Customer type <b className="font-semibold text-slate-800">{customerTypeLabel(r.business_role, r.company_category)}</b></span>
                {r.turnover_class && <span>Turnover class <b className="font-semibold text-slate-800">{r.turnover_class}</b></span>}
                {r.industry && <span>Industry <b className="font-semibold text-slate-800">{r.industry}</b></span>}
            </div>
        </div>
    );
}

// The keyword check's working, kept out of the way for people who want it.
function CrawlerDetails({ r }) {
    if (!r.crawl_tier) return null;
    return (
        <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
            <summary className="cursor-pointer select-none font-semibold text-slate-700">
                Keyword check details <span className="font-normal text-slate-400">score {r.crawl_score ?? '–'} / 100, {r.crawl_tier}</span>
            </summary>
            <div className="mt-3 space-y-2 leading-relaxed">
                <p>The crawler scores a company by matching keywords on its website. It can miss real leads, so the decision above is what counts.</p>
                {r.business_role && <p>Role it guessed: <b className="font-semibold text-slate-800">{ROLE_LABELS[r.business_role] || r.business_role}</b>. {r.business_role_reason || ''}</p>}
                {r.crawl_reason && <p>{r.crawl_reason}</p>}
                {r.crawl_evidence?.length > 0 && (
                    <ul className="list-disc space-y-1 pl-5">
                        {r.crawl_evidence.map((ev, i) => (
                            <li key={i}>{ev}{r.crawl_evidence_urls?.[i] && <> <a href={r.crawl_evidence_urls[i]} target="_blank" rel="noreferrer" className={linkCls}>source</a></>}</li>
                        ))}
                    </ul>
                )}
            </div>
        </details>
    );
}

const OVERRIDE_BUTTONS = [
    { key: 'accept', label: 'Accept', on: 'border-emerald-600 bg-emerald-600 text-white', off: 'border-emerald-200 text-emerald-700 hover:bg-emerald-50' },
    { key: 'review', label: 'Review', on: 'border-yellow-500 bg-yellow-400 text-yellow-950', off: 'border-yellow-200 text-yellow-800 hover:bg-yellow-50' },
    { key: 'reject', label: 'Reject', on: 'border-rose-600 bg-rose-600 text-white', off: 'border-rose-200 text-rose-700 hover:bg-rose-50' },
];

// "Matched to X. Wrong company?" - lets a casual user fix a bad name-to-website match.
function MatchPanel({ r, onUpdate }) {
    const [open, setOpen] = useState(false);
    const [site, setSite] = useState('');
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    if (!r.domain) return null;
    const fix = async () => {
        if (!site.trim()) { setErr('Paste the right website first.'); return; }
        setBusy(true);
        setErr('');
        try {
            const rec = await correctEnrichment({ input: r.input || r.input_aliases?.[0] || r.company_name, website: site.trim(), wrongId: r.id, profile: r.profile });
            onUpdate?.({ ...rec, cache_hit: false });
        } catch (e) {
            setErr(e.message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>Matched to <a href={r.website} target="_blank" rel="noreferrer" className="font-semibold text-blue-600 hover:underline">{r.domain}</a></span>
                {!open && <button type="button" onClick={() => setOpen(true)} className="text-xs font-semibold text-slate-500 underline hover:text-slate-800">Wrong company?</button>}
            </div>
            {open && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                        value={site}
                        onChange={(e) => { setSite(e.target.value); setErr(''); }}
                        placeholder="Paste the right website, e.g. example.com"
                        className="min-w-[14rem] flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <button type="button" onClick={fix} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60">
                        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{busy ? 'Reading the site…' : 'Use this website'}
                    </button>
                    <button type="button" onClick={() => { setOpen(false); setErr(''); }} className="text-xs text-slate-500 hover:text-slate-800">Cancel</button>
                </div>
            )}
            {err && <div className="mt-2 text-xs text-rose-600">{err}</div>}
        </div>
    );
}

// The user's own accept / review / reject call. Saved separately, so re-enriching never overwrites it.
function DecisionPanel({ r, onUpdate }) {
    const [note, setNote] = useState(r.override_note || '');
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    if (!r.id) return null;
    const save = async (decision) => {
        setBusy(true);
        setErr('');
        try {
            const rec = await setEnrichmentOverride({ id: r.id, decision, note, profile: r.profile });
            if (!decision) setNote('');
            onUpdate?.({ ...r, ...rec });
        } catch (e) {
            setErr(e.message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-800">Your decision</span>
                {OVERRIDE_BUTTONS.map((b) => (
                    <button
                        key={b.key}
                        type="button"
                        disabled={busy}
                        onClick={() => save(b.key)}
                        className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors disabled:opacity-60 ${r.override_decision === b.key ? b.on : b.off}`}
                    >
                        {b.label}
                    </button>
                ))}
                {r.override_decision && (
                    <button type="button" disabled={busy} onClick={() => save(null)} className="text-xs text-slate-500 underline hover:text-slate-800">Use the AI's decision again</button>
                )}
            </div>
            <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why? (optional, saved with your decision)"
                className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            {err && <div className="mt-2 text-xs text-rose-600">{err}</div>}
        </div>
    );
}

function RetryButton({ r, onUpdate, label = 'Retry' }) {
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    const retry = async () => {
        setBusy(true);
        setErr('');
        try {
            const rec = await enrichSingle({ companyName: r.input || r.company_name, website: r.error ? undefined : r.website, profile: r.profile });
            onUpdate?.(rec);
        } catch (e) {
            setErr(e.message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="flex flex-col items-end gap-1">
            <button type="button" onClick={retry} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-60">
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{busy ? 'Working…' : label}
            </button>
            {err && <span className="max-w-xs text-right text-xs text-rose-600">{err}</span>}
        </div>
    );
}

function Detail({ r, onUpdate }) {
    const [showAll, setShowAll] = useState(false);
    const desc = r.business_description || '';
    const long = desc.length > 330;
    const fit = r.fit_products || r.tritorc_relevance || [];

    return (
        <div className="border-t border-black/10 bg-white px-5 py-6">
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
                <div className="min-w-0 space-y-8">
                    <VerdictBanner r={r} onUpdate={onUpdate} />

                    {fit.length > 0 && (
                        <Section title={`Why it fits ${r.profile_name || 'Tritorc'}`} hint={`${fit.length} product${fit.length > 1 ? 's' : ''}`}>
                            <ul className="space-y-2">
                                {fit.map((t, i) => <FitCard key={i} text={t} />)}
                            </ul>
                        </Section>
                    )}

                    {desc && (
                        <Section title="About the company">
                            <p className={`max-w-prose text-[15px] leading-7 text-slate-700 ${long && !showAll ? 'line-clamp-4' : ''}`}>{desc}</p>
                            {long && (
                                <button onClick={() => setShowAll((v) => !v)} className="mt-1.5 text-sm font-semibold text-blue-600 hover:underline">
                                    {showAll ? 'Show less' : 'Read more'}
                                </button>
                            )}
                        </Section>
                    )}

                    {r.projects_or_recent_activity?.length > 0 && (
                        <Section title="Recent projects" hint={`${r.projects_or_recent_activity.length}`}>
                            <ul className="space-y-3 border-l-2 border-slate-100 pl-4">
                                {r.projects_or_recent_activity.map((p, i) => <ProjectItem key={i} text={p} />)}
                            </ul>
                        </Section>
                    )}

                    {r.key_operations?.length > 0 && (
                        <Section title="What they do">
                            <div className="flex flex-wrap gap-2">
                                {r.key_operations.map((o, i) => (
                                    <span key={i} className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-700">{o}</span>
                                ))}
                            </div>
                        </Section>
                    )}

                    <CrawlerDetails r={r} />
                </div>

                <aside className="min-w-0 space-y-4">
                    <FactsCard r={r} />
                    <MatchPanel r={r} onUpdate={onUpdate} />
                    <DecisionPanel key={`${r.id}-${r.override_decision || ''}`} r={r} onUpdate={onUpdate} />
                </aside>
            </div>
        </div>
    );
}

// Whole-row tint: green = accept, red = reject, light yellow = review / low confidence,
// light orange = only the keyword check has looked at it and it scored Weak, white = nothing to say yet.
const ROW_TONES = {
    accept: { box: 'border-emerald-500 bg-emerald-50', hover: 'hover:bg-emerald-100/70' },
    reject: { box: 'border-rose-500 bg-rose-50', hover: 'hover:bg-rose-100/70' },
    review: { box: 'border-yellow-400 bg-yellow-50', hover: 'hover:bg-yellow-100/70' },
    weak: { box: 'border-orange-400 bg-orange-50', hover: 'hover:bg-orange-100/70' },
    none: { box: 'border-transparent bg-white', hover: 'hover:bg-slate-50' },
};

function rowTone(r) {
    const v = llmVerdict(r);
    if (!v) return ROW_TONES.none;
    if (v.key === 'review') return v.derived && r.crawl_tier === 'weak' ? ROW_TONES.weak : ROW_TONES.review;
    return ROW_TONES[v.key] || ROW_TONES.none;
}

const ROW_GRID = 'md:grid-cols-[minmax(0,1.7fr)_minmax(0,1.1fr)_104px_84px_92px_minmax(0,1fr)_96px_64px]';

export function RowHeader() {
    return (
        <div className={`hidden gap-x-4 px-5 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400 md:grid ${ROW_GRID}`}>
            <span className="pl-7">Company · Source</span><span>Address</span><span>Phone</span><span>Crawl tier</span><span>LLM decision</span><span>Industry type</span><span>Customer type</span><span>Turnover</span>
        </div>
    );
}

export function Row({ r, open, onToggle, onUpdate }) {
    if (r.error) {
        return (
            <li className="border-l-4 border-amber-400 bg-amber-50">
                <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
                    <div className="flex min-w-0 items-start gap-3">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                        <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-slate-900">{r.input || r.company_name}</div>
                            <div className="text-xs text-amber-800">{r.error_message || "Something went wrong with this company. Press Retry."}</div>
                        </div>
                    </div>
                    <RetryButton r={r} onUpdate={onUpdate} />
                </div>
            </li>
        );
    }
    const loc = [r.hq_city, r.country].filter(Boolean).join(', ');
    const address = r.hq_address || loc;
    const firstFit = (r.fit_products || r.tritorc_relevance)?.[0];
    const [fitProduct] = firstFit ? String(firstFit).split(/\s[—–-]\s/) : [];
    const firstProject = r.projects_or_recent_activity?.[0];
    const tone = rowTone(r);
    const problem = crawlProblem(r);
    const nameBased = !!r.input && !/[./@]/.test(r.input);
    return (
        <li className={`border-l-4 ${tone.box}`}>
            <button
                onClick={onToggle}
                aria-expanded={open}
                className={`grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 px-5 py-3.5 text-left transition-colors ${tone.hover} ${ROW_GRID}`}
            >
                <div className="flex min-w-0 items-center gap-3">
                    {open ? <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />}
                    <div className="min-w-0">
                        <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-slate-900">{r.company_name || r.input}</span>
                            <CompetitorBadge r={r} />
                            {r.cache_hit && <span title="Served from the stored crawl — no re-crawl"><Database className="h-3.5 w-3.5 shrink-0 text-blue-500" /></span>}
                        </div>
                        <div className="truncate text-xs text-slate-500">
                            Enrichment · {nameBased ? 'Matched to ' : ''}{r.domain || r.website || '—'}
                        </div>
                        {problem && (
                            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs leading-snug">
                                <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[11px] font-semibold text-yellow-800">Low confidence</span>
                                <span className="text-slate-500">{problem}</span>
                            </div>
                        )}
                    </div>
                </div>
                <div className="hidden min-w-0 items-center gap-1 overflow-hidden text-sm text-slate-600 md:flex" title={address}>
                    {address
                        ? <><MapPin className="h-3.5 w-3.5 shrink-0 text-slate-400" /><span className="min-w-0 truncate">{address}</span></>
                        : <span className="text-slate-300">—</span>}
                </div>
                <div className="hidden min-w-0 truncate text-sm text-slate-600 md:block" title={r.contact_phones?.join(', ')}>
                    {r.contact_phones?.[0] || <span className="text-slate-300">—</span>}
                </div>
                <div className="flex flex-col items-end gap-1.5 justify-self-end md:flex-row md:items-center md:gap-2 md:justify-self-auto">
                    <div className="md:hidden"><VerdictChip r={r} /></div>
                    <TierChip r={r} />
                </div>
                <div className="hidden md:block"><VerdictChip r={r} /></div>
                <div className="hidden min-w-0 truncate text-sm text-slate-600 md:block" title={r.industry}>
                    {r.industry || <span className="text-slate-300">—</span>}
                </div>
                <div className="hidden truncate text-sm font-medium text-slate-700 md:block">{customerTypeLabel(r.business_role, r.company_category)}</div>
                <div className="hidden md:block"><TurnoverChip r={r} /></div>
                {(fitProduct || firstProject) && (
                    <div className="col-span-full min-w-0 truncate pl-7 text-xs text-slate-500">
                        {fitProduct && <><span className="font-semibold text-slate-600">Fits: </span>{fitProduct}</>}
                        {fitProduct && firstProject && <span className="px-2 text-slate-300">|</span>}
                        {firstProject && <><span className="font-semibold text-slate-600">Recent: </span>{firstProject}</>}
                    </div>
                )}
            </button>
            {open && <Detail r={r} onUpdate={onUpdate} />}
        </li>
    );
}

const FILTERS = ['all', 'best', 'strong', 'weak', 'unknown', 'reject'];
const SORTS = {
    fit: { label: 'Best fit first', fn: (a, b) => (TIER_ORDER[a.crawl_tier ?? 'unknown'] - TIER_ORDER[b.crawl_tier ?? 'unknown']) || ((b.crawl_score ?? -1) - (a.crawl_score ?? -1)) },
    name: { label: 'Name A–Z', fn: (a, b) => String(a.company_name || a.input).localeCompare(String(b.company_name || b.input)) },
    country: { label: 'Country', fn: (a, b) => String(a.country || '~').localeCompare(String(b.country || '~')) },
};

export default function EnrichmentResults({ results, onExport, onItemUpdate }) {
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
                {visible.map(({ r, k }) => <Row key={k} r={r} open={openKeys.has(k)} onToggle={() => toggle(k)} onUpdate={(rec) => onItemUpdate?.(r, rec)} />)}
                {visible.length === 0 && <li className="bg-white px-5 py-8 text-center text-sm text-slate-500">No companies match this filter.</li>}
            </ul>
        </section>
    );
}
