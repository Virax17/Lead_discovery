import React, { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, ChevronDown, History as HistoryIcon, Loader2, RotateCcw } from 'lucide-react';
import EnrichmentResults from './EnrichmentResults';
import { downloadEnrichmentXlsx, fetchEnrichmentRun, fetchEnrichmentRuns } from '../api';

const PAGE_SIZE = 15;

const STATUS = {
    running: { label: 'Running', cls: 'bg-blue-100 text-blue-800' },
    completed: { label: 'Completed', cls: 'bg-emerald-100 text-emerald-800' },
    stopped: { label: 'Stopped', cls: 'bg-amber-100 text-amber-800' },
    failed: { label: 'Failed', cls: 'bg-rose-100 text-rose-800' },
};

const when = (iso) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });
};

const took = (run) => {
    if (!run.finished_at || !run.started_at) return '';
    const secs = Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000);
    if (!(secs >= 0)) return '';
    return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
};

function Count({ n, label, cls }) {
    if (!n) return null;
    return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{n} {label}</span>;
}

function RunRow({ run, open, onToggle, onRunAgain, showUser }) {
    const [detail, setDetail] = useState(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const st = STATUS[run.status] || STATUS.stopped;
    const c = run.counts || {};

    useEffect(() => {
        if (!open || detail || loading) return;
        setLoading(true);
        setError('');
        fetchEnrichmentRun(run.id).then(setDetail).catch((e) => setError(e.message)).finally(() => setLoading(false));
        /* eslint-disable-next-line */
    }, [open]);

    const names = run.names || [];
    const more = Math.max(0, (run.total || names.length) - (run.preview?.length || 0));

    return (
        <li>
            <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 px-5 py-4 text-left hover:bg-slate-50">
                <ChevronDown className={`mt-1 h-4 w-4 flex-shrink-0 text-slate-400 transition-transform ${open ? '' : '-rotate-90'}`} />
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="text-sm font-semibold text-slate-900">{when(run.started_at)}</span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${st.cls}`}>{st.label}</span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">{run.profile_name || run.profile}</span>
                        {showUser && run.created_by && <span className="text-xs text-slate-500">by {run.created_by}</span>}
                        {took(run) && <span className="text-xs text-slate-400">took {took(run)}</span>}
                    </div>
                    <p className="mt-1 truncate text-sm text-slate-600">
                        {(run.preview || []).filter(Boolean).join(', ')}{more > 0 ? ` and ${more} more` : ''}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <span className="mr-1 text-xs text-slate-500">{run.done || 0} of {run.total} companies</span>
                        <Count n={c.accept} label="accept" cls="bg-emerald-100 text-emerald-800" />
                        <Count n={c.review} label="review" cls="bg-yellow-100 text-yellow-800" />
                        <Count n={c.reject} label="reject" cls="bg-rose-100 text-rose-800" />
                        <Count n={c.not_judged} label="not judged" cls="bg-slate-100 text-slate-700" />
                        <Count n={c.error} label="failed" cls="bg-rose-50 text-rose-700" />
                        {c.from_saved > 0 && <span className="text-xs text-slate-400">{c.from_saved} reused from saved</span>}
                    </div>
                </div>
            </button>

            {open && (
                <div className="border-t border-slate-100 bg-slate-50/50 px-5 py-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs text-slate-500">
                            Verdicts are as they stand now, so anything you retried or overrode since shows here too.
                        </p>
                        <button type="button" onClick={() => onRunAgain(names, run.profile)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
                            <RotateCcw className="h-4 w-4" /> Run these again
                        </button>
                    </div>
                    {loading && <div className="flex items-center gap-2 py-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>}
                    {error && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
                    {detail && detail.results.length === 0 && <p className="py-4 text-sm text-slate-500">No company finished in this session.</p>}
                    {detail && detail.results.length > 0 && (
                        <EnrichmentResults
                            results={detail.results}
                            onExport={() => downloadEnrichmentXlsx(detail.results).catch((e) => setError(e.message))}
                            onItemUpdate={(oldRow, rec) => setDetail((d) => ({ ...d, results: d.results.map((x) => (x === oldRow ? { ...rec, input: rec.input || oldRow.input } : x)) }))}
                        />
                    )}
                </div>
            )}
        </li>
    );
}

export default function EnrichmentHistory({ onRunAgain, isAdmin }) {
    const [page, setPage] = useState(1);
    const [data, setData] = useState({ items: [], total: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [openId, setOpenId] = useState(null);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        fetchEnrichmentRuns(page, PAGE_SIZE)
            .then((d) => { if (active) setData(d); })
            .catch((e) => { if (active) setError(e.message); })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [page]);

    const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
    const users = new Set(data.items.map((r) => r.created_by));

    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-3">
                <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
                    <HistoryIcon className="h-5 w-5 text-slate-500" /> Past sessions ({data.total})
                </h2>
                <p className="text-sm text-slate-500">Page {page} of {totalPages}</p>
            </div>
            {error && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                {loading ? (
                    <div className="flex items-center justify-center gap-2 px-6 py-10 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
                ) : data.items.length === 0 ? (
                    <div className="px-6 py-10 text-center text-sm text-slate-500">No sessions yet. Each time you press Enrich it is listed here with the time and what you searched.</div>
                ) : (
                    <ul className="divide-y divide-slate-200">
                        {data.items.map((run) => (
                            <RunRow key={run.id} run={run} open={openId === run.id} onToggle={() => setOpenId(openId === run.id ? null : run.id)} onRunAgain={onRunAgain} showUser={isAdmin || users.size > 1} />
                        ))}
                    </ul>
                )}
            </div>
            <div className="flex items-center justify-between">
                <button type="button" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">
                    <ChevronLeft className="h-4 w-4" /> Previous
                </button>
                <button type="button" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))} className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">
                    Next <ChevronRight className="h-4 w-4" />
                </button>
            </div>
        </section>
    );
}
