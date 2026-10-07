import React, { useEffect, useRef, useState } from 'react';
import { Sparkles, Upload, Square, Loader2, Database, RefreshCw, Search as SearchIcon } from 'lucide-react';
import EnrichmentResults, { Row, RowHeader } from './EnrichmentResults';
import { parseEnrichmentFile, streamEnrichment, fetchEnrichments, fetchEnrichmentProfiles, enrichSingle, downloadEnrichmentXlsx } from '../api';

const FALLBACK_PROFILES = [{ id: 'tritorc', name: 'Tritorc' }, { id: 'ozat', name: 'Ozat' }];
const PROFILE_KEY = 'enrichment_profile';
const readProfile = () => { try { return localStorage.getItem(PROFILE_KEY) || 'tritorc'; } catch { return 'tritorc'; } };

export default function Enrichment() {
    const [text, setText] = useState('');
    const [forceRefresh, setForceRefresh] = useState(false);
    const [running, setRunning] = useState(false);
    const [progress, setProgress] = useState(null); // {index,total,company}
    const [results, setResults] = useState([]);
    const [error, setError] = useState('');
    const [stored, setStored] = useState({ total: 0, items: [] });
    const [query, setQuery] = useState('');
    const [openStored, setOpenStored] = useState(null);
    const abortRef = useRef(null);
    const fileRef = useRef(null);
    const [profile, setProfile] = useState(readProfile);
    const [profiles, setProfiles] = useState(FALLBACK_PROFILES);
    const [judging, setJudging] = useState(null); // {done,total} while adding the other seller's companies
    const [candidates, setCandidates] = useState([]);
    const stopJudgingRef = useRef(false);
    const profileName = profiles.find((p) => p.id === profile)?.name || 'Tritorc';

    const storedSeq = useRef(0);
    const loadStored = async (q = query, p = profile) => {
        const seq = ++storedSeq.current;
        try {
            const data = await fetchEnrichments({ q, profile: p });
            if (seq === storedSeq.current) setStored(data); // a newer request (e.g. seller switched) wins
        } catch (e) {
            setError(e.message);
        }
    };

    useEffect(() => {
        fetchEnrichmentProfiles().then((r) => {
            if (r?.profiles?.length) {
                setProfiles(r.profiles);
                setProfile((cur) => (r.profiles.some((p) => p.id === cur) ? cur : r.default || r.profiles[0].id));
            }
        }).catch(() => {});
    }, []);

    // switching seller re-reads the stored list through that seller's eyes; the current run's rows belong to the old one
    useEffect(() => {
        setResults([]);
        setOpenStored(null);
        loadStored(query, profile);
        /* eslint-disable-next-line */
    }, [profile]);

    const switchProfile = (id) => {
        if (running || judging || id === profile) return;
        try { localStorage.setItem(PROFILE_KEY, id); } catch { /* private mode: just don't remember it */ }
        setProfile(id);
    };

    // Each seller keeps its own list. These are companies already in the other seller's list but not in this one;
    // adding them reuses each company's saved website crawl, so nothing is crawled again.
    const other = profiles.find((p) => p.id !== profile);
    const candSeq = useRef(0);
    const loadCandidates = async () => {
        const seq = ++candSeq.current;
        if (!other) { setCandidates([]); return; }
        try {
            const [mine, theirs] = await Promise.all([
                fetchEnrichments({ profile, limit: 200 }),
                fetchEnrichments({ profile: other.id, limit: 200 }),
            ]);
            const have = new Set(mine.items.map((i) => i.id));
            if (seq === candSeq.current) setCandidates(theirs.items.filter((i) => !have.has(i.id)));
        } catch {
            if (seq === candSeq.current) setCandidates([]);
        }
    };
    useEffect(() => { loadCandidates(); /* eslint-disable-next-line */ }, [profile, profiles, stored.total]);

    const addFromOther = async () => {
        stopJudgingRef.current = false;
        setError('');
        const todo = [...candidates];
        setJudging({ done: 0, total: todo.length });
        for (let i = 0; i < todo.length && !stopJudgingRef.current; i += 1) {
            const it = todo[i];
            try {
                await enrichSingle({ companyName: it.company_name, website: it.website || undefined, profile });
            } catch (e) {
                setError(`${it.company_name}: ${e.message}`);
                break; // don't keep hammering the AI service after a failure (e.g. a limit)
            }
            setJudging({ done: i + 1, total: todo.length });
        }
        setJudging(null);
        await loadStored();
        loadCandidates();
    };

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
                else if (ev.type === 'progress') {
                    setProgress({ index: ev.index, total: ev.total, company: ev.company, status: ev.status });
                    // each company shows up as soon as it is done, so Stop or a dropped connection keeps everything finished so far
                    if (ev.result) setResults((prev) => [...prev, ev.result]);
                }
            }, controller.signal, profile);
        } catch (err) {
            if (err.name !== 'AbortError') setError(err.message);
        } finally {
            setRunning(false);
            abortRef.current = null;
            loadStored();
        }
    };

    const stop = () => abortRef.current?.abort();

    // A row was retried, corrected ("wrong company?") or given the user's own decision.
    const updateResult = (oldRow, rec) => {
        setResults((prev) => prev.map((x) => (x === oldRow ? { ...rec, input: rec.input || oldRow.input } : x)));
        loadStored();
    };
    const updateStored = (oldRow, rec) => {
        setStored((prev) => ({ ...prev, items: prev.items.map((x) => (x === oldRow ? { ...x, ...rec } : x)) }));
        loadStored();
    };

    const pct = progress?.total ? Math.round(((progress.status === 'done' ? progress.index : progress.index - 1) / progress.total) * 100) : 0;

    return (
        <div className="space-y-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
                        <Sparkles className="h-6 w-6 text-blue-600" /> Company Enrichment
                    </h1>
                    <p className="mt-1 text-sm text-slate-500">
                        Paste company names, websites or work emails. Each is crawled once and profiled for {profileName} fit, then stored so it is never crawled twice.
                    </p>
                </div>
                <div className="flex flex-col items-start gap-1.5 sm:items-end">
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Judge leads for</span>
                    <div role="radiogroup" aria-label="Judge leads for" className="inline-flex rounded-xl bg-slate-100 p-1">
                        {profiles.map((p) => (
                            <button
                                key={p.id}
                                type="button"
                                role="radio"
                                aria-checked={p.id === profile}
                                disabled={running || !!judging}
                                onClick={() => switchProfile(p.id)}
                                className={`rounded-lg px-5 py-1.5 text-sm font-semibold transition disabled:cursor-not-allowed ${p.id === profile ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-600 hover:text-slate-900 disabled:opacity-60'}`}
                            >
                                {p.name}
                            </button>
                        ))}
                    </div>
                </div>
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

            <details className="group rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm text-slate-600 shadow-sm">
                <summary className="cursor-pointer select-none font-semibold text-slate-800">How to read the results</summary>
                <dl className="mt-3 grid gap-x-8 gap-y-2 sm:grid-cols-2">
                    <div><dt className="font-semibold text-slate-800">Judge leads for: Tritorc | Ozat</dt><dd>Each seller keeps its own list, decisions, notes, products, buyers and competitors. Only the website crawl is shared, so a company is never crawled twice. A company appears in a seller's list once you enrich it for that seller.</dd></div>
                    <div><dt className="font-semibold text-slate-800">LLM decision</dt><dd>The AI's call on whether Tritorc should pursue the company: <b className="text-emerald-700">Accept</b> (green row: includes distributors and resellers, who are channel partners), <b className="text-yellow-700">Review</b> (light yellow row: needs a human look, also used when a website couldn't be read), <b className="text-rose-700">Reject</b> (red row). A <b className="text-orange-700">light orange row</b> means only the keyword check has seen it and scored it Weak. "Not judged" (white row) means only the keyword check has seen it; enrich it again to get the AI's call.</dd></div>
                    <div><dt className="font-semibold text-slate-800">Crawl tier and score</dt><dd>A quick keyword check of the company's website, scored 0 to 100. It can disagree with the AI (it misses real leads when a site lists many project types). When they differ, follow the decision.</dd></div>
                    <div><dt className="font-semibold text-slate-800">Your decision</dt><dd>Open a row and press Accept, Review or Reject to record your own call. It is marked "you", wins over the AI, and is kept when the company is enriched again.</dd></div>
                    <div><dt className="font-semibold text-slate-800">Matched to / Wrong company?</dt><dd>When you type a name, we find its website. If it picked the wrong company, open the row, press "Wrong company?" and paste the right website.</dd></div>
                    <div><dt className="font-semibold text-slate-800">Low confidence</dt><dd>If a website couldn't be read, the AI is guessing, so the decision is capped at Review and the row says why.</dd></div>
                    <div><dt className="font-semibold text-slate-800">Turnover A / B / C</dt><dd>The company's size by annual turnover: A is US$100M or more, B is US$10M to under US$100M, C is under US$10M. Hover the letter to see whether it was stated on their site or estimated. Blank means there wasn't enough to say, and we don't guess.</dd></div>
                    <div><dt className="font-semibold text-slate-800">Customer type</dt><dd>What kind of buyer it is: End User, EPC, Distributor or Competitor.</dd></div>
                </dl>
            </details>

            {results.length > 0 && (
                <EnrichmentResults
                    results={results}
                    onExport={() => downloadEnrichmentXlsx(results).catch((e) => setError(e.message))}
                    onItemUpdate={updateResult}
                />
            )}

            <section className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
                        <Database className="h-5 w-5 text-slate-500" /> Stored for {profileName} ({stored.total})
                    </h2>
                    <form onSubmit={(e) => { e.preventDefault(); loadStored(query); }} className="relative">
                        <SearchIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name, domain, industry…" className="w-64 rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                    </form>
                </div>
                {other && candidates.length > 0 && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                        <span className="min-w-0 max-w-3xl">
                            {judging
                                ? `Adding to ${profileName}: ${judging.done} of ${judging.total}…`
                                : `${candidates.length} ${candidates.length === 1 ? 'company is' : 'companies are'} in the ${other.name} list but not in your ${profileName} list. ${profileName} and ${other.name} keep their own lists, decisions and notes. Adding reuses each saved website crawl, so nothing is crawled again.`}
                        </span>
                        {judging ? (
                            <button type="button" onClick={() => { stopJudgingRef.current = true; }} className="inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 font-semibold text-rose-700 hover:bg-rose-50">
                                <Square className="h-4 w-4" /> Stop
                            </button>
                        ) : (
                            <button type="button" onClick={addFromOther} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 font-semibold text-white hover:bg-blue-700">
                                <Sparkles className="h-4 w-4" /> Add them to {profileName}
                            </button>
                        )}
                    </div>
                )}
                {stored.items.length > 0 && <RowHeader />}
                <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                    {stored.items.length === 0 ? (
                        <div className="px-6 py-10 text-center text-sm text-slate-500">Nothing stored for {profileName} yet.</div>
                    ) : (
                        <ul className="divide-y divide-slate-200">
                            {stored.items.map((it) => (
                                <Row key={it.id} r={it} open={openStored === it.id} onToggle={() => setOpenStored(openStored === it.id ? null : it.id)} onUpdate={(rec) => updateStored(it, rec)} />
                            ))}
                        </ul>
                    )}
                </div>
            </section>
        </div>
    );
}
