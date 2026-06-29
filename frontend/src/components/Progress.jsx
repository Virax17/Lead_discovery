import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { fetchSearch } from '../api';
import { Loader2 } from 'lucide-react';

export default function Progress() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [statusData, setStatusData] = useState(null);
    const [error, setError] = useState('');

    useEffect(() => {
        let interval;
        const poll = async () => {
            try {
                const data = await fetchSearch(id);
                setStatusData(data);
                
                if (data.status === 'completed' || data.status === 'completed_quota_limited') {
                    clearInterval(interval);
                    navigate(`/search/${id}/results`, { replace: true });
                }
            } catch (err) {
                setError('Lost connection to server');
                clearInterval(interval);
            }
        };

        poll(); // Initial check
        interval = setInterval(poll, 3000);
        return () => clearInterval(interval);
    }, [id, navigate]);

    if (error) {
        return (
            <div className="max-w-md mx-auto bg-white p-6 rounded-lg shadow-sm border border-red-200">
                <h3 className="text-lg font-medium text-red-800">Error polling status</h3>
                <p className="mt-2 text-sm text-red-600">{error}</p>
                <button onClick={() => navigate('/')} className="mt-4 text-blue-600 hover:underline">Return to Dashboard</button>
            </div>
        );
    }

    if (!statusData) {
        return (
            <div className="flex justify-center items-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
            </div>
        );
    }

    const progressPercent = statusData.keywords_total > 0 
        ? Math.round((statusData.keywords_completed / statusData.keywords_total) * 100) 
        : 0;

    return (
        <div className="max-w-2xl mx-auto">
            <div className="bg-white shadow-sm border border-gray-200 rounded-lg p-8 text-center">
                <Loader2 className="w-12 h-12 animate-spin text-blue-600 mx-auto mb-6" />
                <h2 className="text-2xl font-semibold text-gray-900 mb-2">Searching Google Places...</h2>
                <p className="text-gray-500 mb-8">This may take a few minutes depending on the region size.</p>
                
                <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2">
                    <div className="bg-blue-600 h-2.5 rounded-full transition-all duration-500 ease-out" style={{ width: `${progressPercent}%` }}></div>
                </div>
                
                <div className="flex justify-between text-sm text-gray-600 font-medium">
                    <span>Keywords: {statusData.keywords_completed} / {statusData.keywords_total}</span>
                    <span>Found: {statusData.total_results}</span>
                </div>
            </div>
        </div>
    );
}
