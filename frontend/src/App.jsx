import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate } from 'react-router-dom';
import { LogOut, Search as SearchIcon, Clock, Database, Shield } from 'lucide-react';
import { I18nProvider, useI18n } from './i18n/I18nContext';
import { ShellProvider, useShell } from './context/ShellContext';

const Login = lazy(() => import('./components/Login'));
const Dashboard = lazy(() => import('./components/Dashboard'));
const Progress = lazy(() => import('./components/Progress'));
const Results = lazy(() => import('./components/Results'));
const History = lazy(() => import('./components/History'));
const MasterDatabase = lazy(() => import('./components/MasterDatabase'));
const Admin = lazy(() => import('./components/Admin'));

function RouteFallback() {
    return (
        <div className="mx-auto max-w-7xl px-4 py-16 text-center text-sm text-slate-500">
            Loading...
        </div>
    );
}

function NavLink({ to, icon: Icon, children }) {
    return (
        <Link to={to} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900">
            <Icon className="h-4 w-4" /> {children}
        </Link>
    );
}

function LayoutFrame({ children }) {
    const navigate = useNavigate();
    const { quota, quotaLoading, currentUser } = useShell();
    const { t, formatNumber } = useI18n();
    const token = localStorage.getItem('token');

    const handleLogout = () => {
        localStorage.removeItem('token');
        navigate('/login');
    };

    return (
        <div className="min-h-screen bg-[radial-gradient(circle_at_top,#eff6ff_0%,#f8fafc_38%,#ffffff_100%)] text-slate-900 font-sans">
            <nav className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/80 backdrop-blur-xl">
                <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
                    <div className="flex items-center gap-6">
                        <div className="flex flex-shrink-0 items-center gap-2 text-xl font-bold text-slate-900">
                            <SearchIcon className="h-5 w-5 text-blue-600" />
                            {t('app.brand')}
                        </div>
                        <div className="hidden items-center gap-1 md:flex">
                            <NavLink to="/" icon={SearchIcon}>{t('app.nav.newSearch')}</NavLink>
                            <NavLink to="/history" icon={Clock}>{t('app.nav.history')}</NavLink>
                            <NavLink to="/database" icon={Database}>{t('app.nav.masterDatabase')}</NavLink>
                            {currentUser?.role === 'admin' && (
                                <NavLink to="/admin" icon={Shield}>{t('app.nav.admin')}</NavLink>
                            )}
                        </div>
                    </div>

                    <div className="flex items-center gap-4">
                        {currentUser && (
                            <div className="hidden text-right text-sm leading-tight sm:block">
                                <div className="font-medium text-slate-800">{currentUser.username}</div>
                                <div className="text-xs text-slate-500">
                                    {t('app.creditsUsed', {
                                        used: formatNumber(currentUser.credits_used ?? 0),
                                        limit: formatNumber(currentUser.credit_limit ?? 0),
                                    })}
                                </div>
                            </div>
                        )}

                        <div className={`whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ${
                            quota?.status === 'BLOCKED' ? 'bg-rose-100 text-rose-700' :
                            quota?.status === 'WARNING' ? 'bg-amber-100 text-amber-700' :
                            'bg-emerald-100 text-emerald-700'
                        }`}>
                            {quotaLoading
                                ? t('app.loading')
                                : t('app.quotaCallsUsed', {
                                    used: formatNumber(quota?.calls_used ?? 0),
                                    limit: formatNumber(quota?.quota_block_threshold ?? 1000),
                                })}
                        </div>

                        {token && (
                            <button
                                onClick={handleLogout}
                                className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                                aria-label={t('app.logout')}
                            >
                                <LogOut className="h-5 w-5" />
                            </button>
                        )}
                    </div>
                </div>

                <div className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-4 pb-2 sm:px-6 md:hidden lg:px-8">
                    <NavLink to="/" icon={SearchIcon}>{t('app.nav.newSearch')}</NavLink>
                    <NavLink to="/history" icon={Clock}>{t('app.nav.history')}</NavLink>
                    <NavLink to="/database" icon={Database}>{t('app.nav.masterDatabase')}</NavLink>
                    {currentUser?.role === 'admin' && (
                        <NavLink to="/admin" icon={Shield}>{t('app.nav.admin')}</NavLink>
                    )}
                </div>
            </nav>

            <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
                {children}
            </main>
        </div>
    );
}

function ProtectedLayout({ children }) {
    const token = localStorage.getItem('token');
    if (!token) {
        return <Navigate to="/login" replace />;
    }

    return (
        <ShellProvider>
            <LayoutFrame>
                {children}
            </LayoutFrame>
        </ShellProvider>
    );
}

function AppRoutes() {
    return (
        <Suspense fallback={<RouteFallback />}>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/" element={<ProtectedLayout><Dashboard /></ProtectedLayout>} />
                <Route path="/search/:id/progress" element={<ProtectedLayout><Progress /></ProtectedLayout>} />
                <Route path="/search/:id/results" element={<ProtectedLayout><Results /></ProtectedLayout>} />
                <Route path="/history" element={<ProtectedLayout><History /></ProtectedLayout>} />
                <Route path="/database" element={<ProtectedLayout><MasterDatabase /></ProtectedLayout>} />
                <Route path="/admin" element={<ProtectedLayout><Admin /></ProtectedLayout>} />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </Suspense>
    );
}

function App() {
    return (
        <I18nProvider>
            <BrowserRouter>
                <AppRoutes />
            </BrowserRouter>
        </I18nProvider>
    );
}

export default App;
