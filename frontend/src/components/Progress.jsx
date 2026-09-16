import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Loader2, StopCircle } from 'lucide-react';
import { cancelSearch, fetchSearch } from '../api';
import { useI18n } from '../i18n/I18nContext';
import { useShell } from '../context/ShellContext';

export default function Progress() {
    const { id } = useParams();
    const navigate = useNavigate();
    const { t, formatNumber } = useI18n();
    const { refreshQuota } = useShell();
    const [statusData, setStatusData] = useState(null);
    const [error, setError] = useState('');
    const [stopping, setStopping] = useState(false);
    const [stopError, setStopError] = useState('');

    const handleStop = async () => {
        setStopping(true);
        setStopError('');
        try {
            await cancelSearch(id);
            // The runner checks the flag between each location/keyword pair
            // rather than mid-business, so it may take a few poll cycles to
            // actually land on a terminal status — the button stays disabled
            // ("Stopping...") until then rather than implying it's instant.
        } catch {
            setStopError(t('progress.stopFailed'));
            setStopping(false);
        }
    };

    useEffect(() => {
        let interval;

        const poll = async () => {
            try {
                const data = await fetchSearch(id);
                setStatusData(data);

                if (['completed', 'completed_quota_limited', 'completed_rate_limited', 'failed'].includes(data.status)) {
                    clearInterval(interval);
                    await refreshQuota();
                    navigate(`/search/${id}/results`, { replace: true });
                }
            } catch {
                setError(t('progress.lostConnection'));
                clearInterval(interval);
            }
        };

        poll();
        interval = setInterval(poll, 3000);
        return () => clearInterval(interval);
    }, [id, navigate, refreshQuota, t]);

    if (error) {
        return (
            <div className="mx-auto max-w-md rounded-lg border border-red-200 bg-white p-6 shadow-sm">
                <h3 className="text-lg font-medium text-red-800">{t('progress.errorTitle')}</h3>
                <p className="mt-2 text-sm text-red-600">{error}</p>
                <button onClick={() => navigate('/')} className="mt-4 text-blue-600 hover:underline">
                    {t('progress.returnDashboard')}
                </button>
            </div>
        );
    }

    if (!statusData) {
        return (
            <div className="flex h-64 items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
            </div>
        );
    }

    const progressPercent = statusData.keywords_total > 0
        ? Math.round((statusData.keywords_completed / statusData.keywords_total) * 100)
        : 0;

    // Extrapolated from the actual observed rate so far (calls per
    // completed pair), not a pre-search guess — this self-corrects for
    // pairs the "already searched" log is skipping for free, which a
    // static formula can't know about in advance.
    const callsPerPair = statusData.keywords_completed > 0
        ? (statusData.place_details_calls_used || 0) / statusData.keywords_completed
        : 0;
    const projectedTotalCalls = Math.round(callsPerPair * statusData.keywords_total);

    const isStopping = stopping || statusData.cancel_requested;

    return (
        <div className="mx-auto max-w-2xl">
            <div className="rounded-lg border border-gray-200 bg-white p-8 text-center shadow-sm">
                <Loader2 className="mx-auto mb-6 h-12 w-12 animate-spin text-blue-600" />
                <h2 className="mb-2 text-2xl font-semibold text-gray-900">{t('progress.searching')}</h2>
                <p className="mb-8 text-gray-500">{t('progress.mayTake')}</p>

                <div className="mb-2 h-2.5 w-full rounded-full bg-gray-200">
                    <div className="h-2.5 rounded-full bg-blue-600 transition-all duration-500 ease-out" style={{ width: `${progressPercent}%` }} />
                </div>

                <div className="flex justify-between text-sm font-medium text-gray-600">
                    <span>{t('progress.keywords', { completed: formatNumber(statusData.keywords_completed), total: formatNumber(statusData.keywords_total) })}</span>
                    <span>{t('progress.found', { count: formatNumber(statusData.total_results) })}</span>
                </div>
                <p className="mt-3 text-sm text-gray-500">
                    {t('progress.creditsUsedSoFar', { count: formatNumber(statusData.place_details_calls_used || 0) })}
                </p>
                {statusData.keywords_completed > 0 && (
                    <p className="mt-1 text-sm font-medium text-gray-700">
                        {t('progress.projectedTotalCredits', { count: formatNumber(projectedTotalCalls) })}
                    </p>
                )}

                <div className="mt-6 border-t border-gray-100 pt-6">
                    <button
                        type="button"
                        onClick={handleStop}
                        disabled={isStopping}
                        className="inline-flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        <StopCircle className="h-4 w-4" />
                        {isStopping ? t('progress.stopping') : t('progress.stopSearch')}
                    </button>
                    <p className="mt-2 text-xs text-gray-400">{t('progress.stopNote')}</p>
                    {stopError && <p className="mt-2 text-sm text-red-600">{stopError}</p>}
                </div>
            </div>
        </div>
    );
}
