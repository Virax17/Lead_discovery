import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { fetchSearch } from '../api';
import { useI18n } from '../i18n/I18nContext';
import { useShell } from '../context/ShellContext';

export default function Progress() {
    const { id } = useParams();
    const navigate = useNavigate();
    const { t, formatNumber } = useI18n();
    const { refreshQuota } = useShell();
    const [statusData, setStatusData] = useState(null);
    const [error, setError] = useState('');

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
            </div>
        </div>
    );
}
