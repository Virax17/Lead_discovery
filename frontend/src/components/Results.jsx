import React, { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { fetchSearch, downloadFile } from '../api';
import { Download, AlertTriangle, SlidersHorizontal, X } from 'lucide-react';

const DEFAULT_COLUMNS = [
    { key: 'name', label: 'Company' },
    { key: 'address', label: 'Address' },
    { key: 'website', label: 'Website' },
    { key: 'phone_number', label: 'Phone Number' },
    { key: 'industry_type', label: 'Industry Type' },
    { key: 'maps_url', label: 'Maps Link' }
];

export default function Results() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [searchData, setSearchData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showExportPicker, setShowExportPicker] = useState(false);
    const [selectedColumns, setSelectedColumns] = useState(DEFAULT_COLUMNS.map(column => column.key));

    React.useEffect(() => {
        fetchSearch(id).then(data => {
            setSearchData(data);
            setLoading(false);
        }).catch(() => {
            navigate('/');
        });
    }, [id, navigate]);

    const businesses = searchData?.businesses || [];
    const quotaLimited = searchData?.status === 'completed_quota_limited';
    const exportColumns = useMemo(() => DEFAULT_COLUMNS.filter(column => selectedColumns.includes(column.key)), [selectedColumns]);

    const toggleColumn = (key) => {
        setSelectedColumns(prev => prev.includes(key) ? prev.filter(value => value !== key) : [...prev, key]);
    };

    const handleDownload = async (format) => {
        await downloadFile(id, format, exportColumns.map(column => column.label));
        setShowExportPicker(false);
    };

    if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-600">Loading results...</div>;
    if (!searchData) return null;

    return (
        <div className="space-y-6">
            <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_20px_80px_rgba(15,23,42,0.08)]">
                <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_55%,#38bdf8_100%)] px-8 py-8 text-white">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                            <h2 className="text-3xl font-semibold tracking-tight">Search Results</h2>
                            <p className="mt-2 text-sm text-slate-100/90">Found {searchData.total_results} unique businesses</p>
                        </div>
                        <div className="flex flex-wrap gap-3">
                            <button onClick={() => setShowExportPicker(true)} className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-2 text-sm font-medium text-white backdrop-blur hover:bg-white/20">
                                <SlidersHorizontal className="h-4 w-4" />
                                Customize Export
                            </button>
                        </div>
                    </div>
                </div>

                {quotaLimited && (
                    <div className="m-8 rounded-2xl border border-amber-200 bg-amber-50 p-4">
                        <div className="flex gap-3">
                            <AlertTriangle className="h-5 w-5 text-amber-600" />
                            <div>
                                <p className="text-sm font-semibold text-amber-900">Search stopped early because the monthly API quota was reached.</p>
                                <p className="mt-1 text-sm text-amber-800">The results below are partial.</p>
                            </div>
                        </div>
                    </div>
                )}

                <div className="overflow-x-auto px-8 pb-8">
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
                            {businesses.map((business, index) => (
                                <tr key={index} className="hover:bg-slate-50">
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
                                </tr>
                            ))}
                            {businesses.length === 0 && (
                                <tr>
                                    <td colSpan={DEFAULT_COLUMNS.length} className="px-6 py-8 text-center text-slate-500">No businesses found for this search.</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {showExportPicker && (
                <div className="fixed inset-0 z-20 flex items-center justify-center bg-slate-950/50 px-4">
                    <div className="w-full max-w-xl rounded-[2rem] bg-white p-6 shadow-2xl">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <h3 className="text-xl font-semibold text-slate-900">Customize export columns</h3>
                                <p className="mt-1 text-sm text-slate-500">Choose which fields to include in the file.</p>
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
                            <button onClick={() => handleDownload('csv')} className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                                <Download className="h-4 w-4" />
                                CSV
                            </button>
                            <button onClick={() => handleDownload('xlsx')} className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
                                <Download className="h-4 w-4" />
                                Excel
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
