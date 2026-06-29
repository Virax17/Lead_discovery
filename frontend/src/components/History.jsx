import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchHistory, downloadFile } from '../api';
import { Download, ChevronRight } from 'lucide-react';

export default function History() {
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetchHistory().then(data => {
            setHistory(data);
            setLoading(false);
        });
    }, []);

    if (loading) return <div className="text-center p-8">Loading history...</div>;

    return (
        <div className="space-y-6">
            <h2 className="text-2xl font-bold text-gray-900">Search History</h2>
            
            <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
                <ul className="divide-y divide-gray-200">
                    {history.map((search) => (
                        <li key={search.id} className="hover:bg-gray-50 transition-colors">
                            <div className="px-6 py-4 flex items-center justify-between">
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between">
                                        <p className="text-sm font-medium text-blue-600 truncate">
                                            {search.country} {search.state ? `/ ${search.state}` : ''} {search.city ? `/ ${search.city}` : ''}
                                        </p>
                                        <div className="ml-2 flex-shrink-0 flex">
                                            <p className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                                                search.status === 'completed' ? 'bg-green-100 text-green-800' :
                                                search.status === 'completed_quota_limited' ? 'bg-amber-100 text-amber-800' :
                                                'bg-gray-100 text-gray-800'
                                            }`}>
                                                {search.status}
                                            </p>
                                        </div>
                                    </div>
                                    <div className="mt-2 flex justify-between">
                                        <div className="sm:flex">
                                            <p className="flex items-center text-sm text-gray-500">
                                                {search.total_results} results • {new Date(search.created_at).toLocaleDateString()}
                                            </p>
                                        </div>
                                        <div className="flex items-center space-x-4">
                                            {(search.status === 'completed' || search.status === 'completed_quota_limited') && (
                                                <>
                                                    <button onClick={() => downloadFile(search.id, 'xlsx')} className="text-gray-500 hover:text-blue-600 transition-colors" title="Download Excel">
                                                        <Download className="w-4 h-4" />
                                                    </button>
                                                    <Link to={`/search/${search.id}/results`} className="text-gray-500 hover:text-blue-600 transition-colors">
                                                        <ChevronRight className="w-5 h-5" />
                                                    </Link>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </li>
                    ))}
                    {history.length === 0 && (
                        <li className="px-6 py-8 text-center text-gray-500">No past searches found.</li>
                    )}
                </ul>
            </div>
        </div>
    );
}
