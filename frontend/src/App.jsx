import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate } from 'react-router-dom';
import { LogOut, Search as SearchIcon, Clock } from 'lucide-react';
import { fetchQuota, logout } from './api';

import Login from './components/Login';
import Dashboard from './components/Dashboard';
import Progress from './components/Progress';
import Results from './components/Results';
import History from './components/History';

function Layout({ children }) {
    const navigate = useNavigate();
    const [quota, setQuota] = useState(null);
    const token = localStorage.getItem('token');

    useEffect(() => {
        if (!token) {
            return;
        }
        fetchQuota().then(setQuota).catch(err => {
            if (err.message === "Unauthorized") navigate('/login');
        });
    }, [navigate, token]);

    if (!token) {
        return <Navigate to="/login" replace />;
    }

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    return (
        <div className="min-h-screen bg-[radial-gradient(circle_at_top,#eff6ff_0%,#f8fafc_38%,#ffffff_100%)] text-slate-900 font-sans">
            <nav className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/80 backdrop-blur-xl">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between h-16">
                        <div className="flex space-x-8">
                            <div className="flex-shrink-0 flex items-center font-bold text-xl text-slate-900">
                                LeadDiscovery
                            </div>
                            <Link to="/" className="inline-flex items-center px-1 pt-1 text-sm font-medium text-slate-700 hover:text-blue-600">
                                <SearchIcon className="w-4 h-4 mr-2" /> New Search
                            </Link>
                            <Link to="/history" className="inline-flex items-center px-1 pt-1 text-sm font-medium text-slate-700 hover:text-blue-600">
                                <Clock className="w-4 h-4 mr-2" /> History
                            </Link>
                        </div>
                        <div className="flex items-center space-x-6">
                            {quota && (
                                <div className={`text-sm font-medium px-3 py-1 rounded-full ${
                                    quota.status === 'BLOCKED' ? 'bg-rose-100 text-rose-700' :
                                    quota.status === 'WARNING' ? 'bg-amber-100 text-amber-700' :
                                    'bg-emerald-100 text-emerald-700'
                                }`}>
                                    {quota.calls_used ?? 0} / {quota.quota_block_threshold ?? 1000} calls used
                                </div>
                            )}
                            <button onClick={handleLogout} className="text-slate-500 hover:text-slate-700">
                                <LogOut className="w-5 h-5" />
                            </button>
                        </div>
                    </div>
                </div>
            </nav>
            <main className="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
                {children}
            </main>
        </div>
    );
}

function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/" element={<Layout><Dashboard /></Layout>} />
                <Route path="/search/:id/progress" element={<Layout><Progress /></Layout>} />
                <Route path="/search/:id/results" element={<Layout><Results /></Layout>} />
                <Route path="/history" element={<Layout><History /></Layout>} />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </BrowserRouter>
    );
}

export default App;
