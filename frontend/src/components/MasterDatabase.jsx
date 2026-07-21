import React, { useEffect, useMemo, useState } from 'react';
import { Download, Database, SlidersHorizontal, X, ChevronLeft, ChevronRight } from 'lucide-react';
import { downloadCountryExport, fetchCountryBusinesses, fetchPopulatedCountries } from '../api';
import { useI18n } from '../i18n/I18nContext';

const DEFAULT_COLUMNS = [
    { key: 'source', label: 'Source' },
    { key: 'name', label: 'Company Name' },
    { key: 'address', label: 'Address' },
    { key: 'website', label: 'Website' },
    { key: 'phone_number', label: 'Phone Number' },
    { key: 'industry_type', label: 'Industry Type' },
    { key: 'maps_url', label: 'Google Maps URL' },
    { key: 'first_found_at', label: 'First Found' },
    { key: 'last_seen_at', label: 'Last Seen' }
];

function formatDate(value, locale) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '-' : new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date);
}

export default function MasterDatabase() {
    const { t, locale, formatNumber } = useI18n();
    const [country, setCountry] = useState('');
    const [page, setPage] = useState(1);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [showExportPicker, setShowExportPicker] = useState(false);
    const [selectedColumns, setSelectedColumns] = useState(DEFAULT_COLUMNS.map(column => column.key));
    const [downloading, setDownloading] = useState(false);
    const [populatedCountries, setPopulatedCountries] = useState([]);
    const [populatedLoading, setPopulatedLoading] = useState(true);

    useEffect(() => {
        let active = true;
        fetchPopulatedCountries().then(items => {
            if (active) setPopulatedCountries(items || []);
        }).catch(() => {
            if (active) setPopulatedCountries([]);
        }).finally(() => {
            if (active) setPopulatedLoading(false);
        });
        return () => {
            active = false;
        };
    }, []);

    useEffect(() => {
        if (!country) {
            setData(null);
            return;
        }
        setLoading(true);
        setError('');
        fetchCountryBusinesses(country, page)
            .then(setData)
            .catch(() => setError('Failed to load businesses for this country.'))
            .finally(() => setLoading(false));
    }, [country, page]);

    const businesses = data?.businesses || [];
    const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
    const exportColumns = useMemo(() => DEFAULT_COLUMNS.filter(column => selectedColumns.includes(column.key)), [selectedColumns]);

    const toggleColumn = (key) => {
        setSelectedColumns(prev => prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]);
    };

    const handleCountryChange = (value) => {
        setCountry(value);
        setPage(1);
    };

    const handleDownload = async (format) => {
        setDownloading(true);
        try {
            await downloadCountryExport(country, format, exportColumns.map(column => column.label));
            setShowExportPicker(false);
        } catch {
            setError('Download failed. Please try again.');
        } finally {
            setDownloading(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_20px_80px_rgba(15,23,42,0.08)]">
                <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_55%,#38bdf8_100%)] px-8 py-8 text-white">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                            <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-white/90">
                                <Database className="h-3 w-3" />
                                {t('masterDatabase.title')}
                            </p>
                            <h2 className="text-3xl font-semibold tracking-tight">{t('masterDatabase.title')}</h2>
                            <p className="mt-2 text-sm text-slate-100/90">{t('masterDatabase.subtitle')}</p>
                        </div>
                        {country && (
                            <button
                                onClick={() => setShowExportPicker(true)}
                                className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-2 text-sm font-medium text-white backdrop-blur hover:bg-white/20"
                            >
                                <SlidersHorizontal className="h-4 w-4" />
                                {t('masterDatabase.customizeExport')}
                            </button>
                        )}
                    </div>
                </div>

                <div className="p-8 space-y-6">
                    <div className="max-w-sm">
                        <label className="block text-sm font-medium text-slate-700">{t('masterDatabase.country')}</label>
                        <select
                            value={country}
                            onChange={e => handleCountryChange(e.target.value)}
                            className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:bg-white"
                        >
                            <option value="">{populatedLoading ? t('common.loading') : t('masterDatabase.selectCountry')}</option>
                            {populatedCountries.map(c => (
                                <option key={c.country} value={c.country}>{c.country} ({formatNumber(c.count)})</option>
                            ))}
                        </select>
                    </div>

                    {error && (
                        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                            {error}
                        </div>
                    )}

                    {!country && !populatedLoading && populatedCountries.length > 0 && (
                        <div>
                            <p className="mb-2 text-sm font-medium text-slate-700">{t('masterDatabase.countriesWithData')}</p>
                            <div className="flex flex-wrap gap-2">
                                {populatedCountries.map(c => (
                                    <button
                                        key={c.country}
                                        type="button"
                                        onClick={() => handleCountryChange(c.country)}
                                        className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 transition hover:border-blue-300 hover:text-blue-600"
                                    >
                                        {c.country}
                                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">{formatNumber(c.count)}</span>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {!country && !populatedLoading && populatedCountries.length === 0 && (
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">
                            {t('masterDatabase.noDataYet')}
                        </div>
                    )}

                    {country && loading && (
                        <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-600">{t('masterDatabase.loading')}</div>
                    )}

                    {country && !loading && data && (
                        <>
                            <p className="text-sm text-slate-500">
                                {t('masterDatabase.count', { count: formatNumber(data.total), country })}
                            </p>
                            <div className="overflow-x-auto">
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
                                        {businesses.map((business) => (
                                            <tr key={business.id} className="hover:bg-slate-50">
                                                <td className="px-6 py-4 text-sm text-slate-600">LeadDiscovery</td>
                                                <td className="px-6 py-4 text-sm font-medium text-slate-900">{business.name}</td>
                                                <td className="px-6 py-4 text-sm text-slate-600">{business.address}</td>
                                                <td className="px-6 py-4 text-sm text-blue-600 hover:underline">
                                                    {business.website ? <a href={business.website} target="_blank" rel="noreferrer">Website</a> : '-'}
                                                </td>
                                                <td className="px-6 py-4 text-sm text-slate-600">{business.phone_number || '-'}</td>
                                                <td className="px-6 py-4 text-sm text-slate-600">{business.industry_type || '-'}</td>
                                                <td className="px-6 py-4 text-sm text-blue-600 hover:underline">
                                                    {business.maps_url ? <a href={business.maps_url} target="_blank" rel="noreferrer">Maps</a> : '-'}
                                                </td>
                                                <td className="px-6 py-4 text-sm text-slate-600">{formatDate(business.first_found_at, locale)}</td>
                                                <td className="px-6 py-4 text-sm text-slate-600">{formatDate(business.last_seen_at, locale)}</td>
                                            </tr>
                                        ))}
                                        {businesses.length === 0 && (
                                            <tr>
                                                <td colSpan={DEFAULT_COLUMNS.length} className="px-6 py-8 text-center text-slate-500">{t('masterDatabase.noBusinesses')}</td>
                                            </tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>

                            {data.total > data.page_size && (
                                <div className="flex items-center justify-between border-t border-slate-200 pt-4">
                                    <button
                                        type="button"
                                        disabled={page <= 1}
                                        onClick={() => setPage(p => Math.max(1, p - 1))}
                                        className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        <ChevronLeft className="h-4 w-4" />
                                        {t('history.previous')}
                                    </button>
                                    <span className="text-sm text-slate-500">{t('common.pageOf', { page, total: totalPages })}</span>
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
                            )}
                        </>
                    )}
                </div>
            </div>

            {showExportPicker && (
                <div className="fixed inset-0 z-20 flex items-center justify-center bg-slate-950/50 px-4">
                    <div className="w-full max-w-xl rounded-[2rem] bg-white p-6 shadow-2xl">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <h3 className="text-xl font-semibold text-slate-900">{t('masterDatabase.customizeColumns')}</h3>
                                <p className="mt-1 text-sm text-slate-500">{t('masterDatabase.chooseFields', { country })}</p>
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
                            <button disabled={downloading} onClick={() => handleDownload('csv')} className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60">
                                <Download className="h-4 w-4" />
                                {t('masterDatabase.csv')}
                            </button>
                            <button disabled={downloading} onClick={() => handleDownload('xlsx')} className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60">
                                <Download className="h-4 w-4" />
                                {t('masterDatabase.excel')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
