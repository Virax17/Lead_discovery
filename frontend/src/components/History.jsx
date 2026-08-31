import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { downloadFile, fetchHistory } from '../api';
import { useI18n } from '../i18n/I18nContext';

const PAGE_SIZE = 20;
const TERMINAL_STATUSES = new Set(['completed', 'completed_quota_limited', 'completed_rate_limited', 'failed']);

function statusClass(status) {
    if (status === 'completed') return 'bg-emerald-100 text-emerald-800';
    if (status === 'completed_quota_limited') return 'bg-amber-100 text-amber-800';
    if (status === 'failed' || status === 'completed_rate_limited') return 'bg-rose-100 text-rose-800';
    return 'bg-slate-100 text-slate-800';
}

export default function History() {
    const { t, formatDate, formatNumber } = useI18n();
    const [history, setHistory] = useState([]);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(PAGE_SIZE);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let active = true;
        setLoading(true);

        fetchHistory(page, pageSize).then(data => {
            if (!active) return;
            setHistory(data.items || []);
            setTotal(data.total || 0);
        }).catch(() => {
            if (!active) return;
            setHistory([]);
            setTotal(0);
        }).finally(() => {
            if (active) setLoading(false);
        });

        return () => {
            active = false;
        };
    }, [page, pageSize]);

    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    if (loading) {
        return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-600">{t('history.loading')}</div>;
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between gap-4">
                <h2 className="text-2xl font-bold text-slate-900">{t('history.title')}</h2>
                <p className="text-sm text-slate-500">{t('common.pageOf', { page, total: totalPages })}</p>
            </div>

            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <ul className="divide-y divide-slate-200">
                    {history.map((search) => {
                        const isFinished = TERMINAL_STATUSES.has(search.status);
                        const hasResults = Number(search.total_results || 0) > 0;
                        const statusLabel = t(`status.${search.status}`) || search.status;

                        return (
                            <li key={search.id} className="transition-colors hover:bg-slate-50">
                                <div className="flex items-center justify-between gap-4 px-6 py-4">
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center justify-between gap-4">
                                            <p className="truncate text-sm font-medium text-blue-600">
                                                {search.country} {search.state ? `/ ${search.state}` : ''} {search.city ? `/ ${search.city}` : ''}
                                            </p>
                                            <p className={`ml-2 inline-flex flex-shrink-0 rounded-full px-2 text-xs font-semibold leading-5 ${statusClass(search.status)}`}>
                                                {statusLabel}
                                            </p>
                                        </div>

                                        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                                            <p className="text-sm text-slate-500">
                                                {t('history.results', { count: formatNumber(search.total_results || 0) })} · {t('history.credits', { count: formatNumber(search.place_details_calls_used || 0) })} · {formatDate(search.created_at)}
                                            </p>

                                            <div className="flex items-center gap-4">
                                                {isFinished && hasResults && (
                                                    <>
                                                        <button
                                                            onClick={() => downloadFile(search.id, 'xlsx')}
                                                            className="text-slate-500 transition-colors hover:text-blue-600"
                                                            title={t('history.downloadExcel')}
                                                        >
                                                            <Download className="h-4 w-4" />
                                                        </button>
                                                        <Link to={`/search/${search.id}/results`} className="text-slate-500 transition-colors hover:text-blue-600">
                                                            <ChevronRight className="h-5 w-5" />
                                                        </Link>
                                                    </>
                                                )}
                                                {isFinished && !hasResults && (
                                                    <Link to={`/search/${search.id}/results`} className="text-xs font-medium text-slate-500 hover:text-blue-600">
                                                        View details
                                                    </Link>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </li>
                        );
                    })}
                    {history.length === 0 && (
                        <li className="px-6 py-8 text-center text-slate-500">{t('history.noPastSearches')}</li>
                    )}
                </ul>
            </div>

            <div className="flex items-center justify-between">
                <button
                    type="button"
                    disabled={page <= 1}
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    <ChevronLeft className="h-4 w-4" />
                    {t('history.previous')}
                </button>
                <span className="text-sm text-slate-500">{t('history.page', { page, total: totalPages })}</span>
                <button
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {t('history.next')}
                    <ChevronRight className="h-4 w-4" />
                </button>
            </div>
        </div>
    );
}
