import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Plus, KeyRound, Ban, CheckCircle2, Globe, X, Users as UsersIcon, Wrench } from 'lucide-react';
import { createAdminUser, fetchAdminUsers, updateAdminUserPassword, updateAdminUserActive, normalizeAdminCountries } from '../api';
import { useI18n } from '../i18n/I18nContext';
import { useShell } from '../context/ShellContext';

const EMPTY_FORM = { username: '', password: '', role: 'user', credit_limit: 1000 };

function Modal({ title, onClose, children }) {
    return (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-slate-950/50 px-4">
            <div className="w-full max-w-md rounded-[2rem] bg-white p-6 shadow-2xl">
                <div className="flex items-start justify-between gap-4">
                    <h3 className="text-xl font-semibold text-slate-900">{title}</h3>
                    <button onClick={onClose} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                        <X className="h-4 w-4" />
                    </button>
                </div>
                <div className="mt-5">{children}</div>
            </div>
        </div>
    );
}

function StatusBadge({ active, label }) {
    return (
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
            active ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
        }`}>
            <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-emerald-500' : 'bg-rose-500'}`} />
            {label}
        </span>
    );
}

export default function Admin() {
    const navigate = useNavigate();
    const { t, formatDate, formatNumber } = useI18n();
    const { currentUser } = useShell();
    const [tab, setTab] = useState('users');
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [showAddUser, setShowAddUser] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [passwordModalUser, setPasswordModalUser] = useState(null);
    const [passwordDraft, setPasswordDraft] = useState('');
    const [busyUsername, setBusyUsername] = useState(null);
    const [normalizing, setNormalizing] = useState(false);

    useEffect(() => {
        if (currentUser && currentUser.role !== 'admin') {
            navigate('/');
            return;
        }

        let active = true;
        fetchAdminUsers().then(data => {
            if (!active) return;
            setUsers(data || []);
        }).catch(() => {
            if (!active) return;
            setError(t('admin.failedLoadUsers'));
        }).finally(() => {
            if (active) setLoading(false);
        });

        return () => {
            active = false;
        };
    }, [currentUser, navigate]);

    const clearFeedback = () => {
        setError('');
        setMessage('');
    };

    const handleChange = (key, value) => {
        setForm(prev => ({ ...prev, [key]: value }));
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        clearFeedback();

        try {
            const created = await createAdminUser({
                username: form.username,
                password: form.password,
                role: form.role,
                credit_limit: Number(form.credit_limit || 0),
            });
            setUsers(prev => [created, ...prev]);
            setMessage(t('admin.userCreated'));
            setForm(EMPTY_FORM);
            setShowAddUser(false);
        } catch (err) {
            setError(err.message || t('admin.failedCreateUser'));
        }
    };

    const openPasswordModal = (username) => {
        clearFeedback();
        setPasswordDraft('');
        setPasswordModalUser(username);
    };

    const handlePasswordSubmit = async (event) => {
        event.preventDefault();
        clearFeedback();
        setBusyUsername(passwordModalUser);
        try {
            await updateAdminUserPassword(passwordModalUser, passwordDraft);
            setMessage(t('admin.passwordUpdated', { username: passwordModalUser }));
            setPasswordModalUser(null);
            setPasswordDraft('');
        } catch (err) {
            setError(err.message || t('admin.failedUpdatePassword'));
        } finally {
            setBusyUsername(null);
        }
    };

    const handleToggleActive = async (user) => {
        clearFeedback();
        setBusyUsername(user.username);
        try {
            const updated = await updateAdminUserActive(user.username, !user.active);
            setUsers(prev => prev.map(u => (u.username === user.username ? { ...u, ...updated } : u)));
            setMessage(updated.active ? t('admin.userActivated', { username: user.username }) : t('admin.userDeactivated', { username: user.username }));
        } catch (err) {
            setError(err.message || t('admin.failedUpdateActive'));
        } finally {
            setBusyUsername(null);
        }
    };

    const handleNormalizeCountries = async () => {
        clearFeedback();
        setNormalizing(true);
        try {
            const result = await normalizeAdminCountries();
            const merges = result.merges || [];
            setMessage(merges.length > 0
                ? t('admin.countriesMerged', { count: merges.length })
                : t('admin.noCountryDuplicates'));
        } catch (err) {
            setError(err.message || t('admin.failedNormalizeCountries'));
        } finally {
            setNormalizing(false);
        }
    };

    if (currentUser && currentUser.role !== 'admin') {
        return null;
    }

    const tabButtonClass = (key) => `inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition ${
        tab === key ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
    }`;

    return (
        <div className="space-y-6">
            <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_20px_80px_rgba(15,23,42,0.08)]">
                <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_55%,#38bdf8_100%)] px-8 py-8 text-white">
                    <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-white/90">
                        <Shield className="h-3 w-3" />
                        {t('admin.title')}
                    </p>
                    <h2 className="text-3xl font-semibold tracking-tight">{t('admin.title')}</h2>
                    <p className="mt-2 text-sm text-slate-100/90">{t('admin.subtitle')}</p>
                </div>

                <div className="flex items-center gap-2 border-b border-slate-200 px-8 py-4">
                    <button type="button" onClick={() => setTab('users')} className={tabButtonClass('users')}>
                        <UsersIcon className="h-4 w-4" />
                        {t('admin.usersTab')}
                    </button>
                    <button type="button" onClick={() => setTab('maintenance')} className={tabButtonClass('maintenance')}>
                        <Wrench className="h-4 w-4" />
                        {t('admin.maintenanceTab')}
                    </button>
                </div>

                {(error || message) && (
                    <div className="px-8 pt-6">
                        {error && (
                            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
                        )}
                        {message && (
                            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div>
                        )}
                    </div>
                )}

                {tab === 'users' && (
                    <div className="p-8">
                        <div className="flex items-center justify-between gap-4">
                            <p className="text-sm text-slate-500">
                                {loading ? t('common.loading') : t('admin.userCount', { count: formatNumber(users.length) })}
                            </p>
                            <button
                                type="button"
                                onClick={() => setShowAddUser(true)}
                                className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
                            >
                                <Plus className="h-4 w-4" />
                                {t('admin.addUser')}
                            </button>
                        </div>

                        <div className="mt-5 overflow-x-auto">
                            <table className="min-w-full divide-y divide-slate-200 rounded-2xl border border-slate-200">
                                <thead className="bg-slate-50">
                                    <tr>
                                        <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.username')}</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.role')}</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.usage')}</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.active')}</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.createdAt')}</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.lastLogin')}</th>
                                        <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('admin.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-200 bg-white">
                                    {users.map(user => (
                                        <tr key={user.username} className="hover:bg-slate-50">
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-3">
                                                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-semibold text-blue-700">
                                                        {user.username.slice(0, 2).toUpperCase()}
                                                    </div>
                                                    <span className="text-sm font-medium text-slate-900">{user.username}</span>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-sm text-slate-600 capitalize">{user.role}</td>
                                            <td className="px-4 py-3 text-sm text-slate-600">
                                                {formatNumber(user.credits_used ?? 0)} / {formatNumber(user.credit_limit ?? 0)}
                                            </td>
                                            <td className="px-4 py-3">
                                                <StatusBadge active={user.active} label={user.active ? t('common.yes') : t('common.no')} />
                                            </td>
                                            <td className="px-4 py-3 text-sm text-slate-600">{formatDate(user.created_at)}</td>
                                            <td className="px-4 py-3 text-sm text-slate-600">{formatDate(user.last_login_at)}</td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center justify-end gap-1.5">
                                                    <button
                                                        type="button"
                                                        onClick={() => openPasswordModal(user.username)}
                                                        className="rounded-full p-2 text-slate-500 hover:bg-slate-100 hover:text-blue-600"
                                                        title={t('admin.changePassword')}
                                                        aria-label={t('admin.changePassword')}
                                                    >
                                                        <KeyRound className="h-4 w-4" />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={busyUsername === user.username}
                                                        onClick={() => handleToggleActive(user)}
                                                        className={`rounded-full p-2 hover:bg-slate-100 disabled:opacity-50 ${user.active ? 'text-slate-500 hover:text-rose-600' : 'text-slate-500 hover:text-emerald-600'}`}
                                                        title={user.active ? t('admin.deactivate') : t('admin.activate')}
                                                        aria-label={user.active ? t('admin.deactivate') : t('admin.activate')}
                                                    >
                                                        {user.active ? <Ban className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                    {users.length === 0 && !loading && (
                                        <tr>
                                            <td colSpan={7} className="px-4 py-8 text-center text-slate-500">{t('admin.noUsers')}</td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {tab === 'maintenance' && (
                    <div className="p-8">
                        <div className="max-w-xl rounded-2xl border border-slate-200 p-6">
                            <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
                                <Globe className="h-4 w-4 text-blue-600" />
                                {t('admin.mergeCountries')}
                            </h3>
                            <p className="mt-1 text-sm text-slate-500">{t('admin.mergeCountriesHint')}</p>
                            <button
                                type="button"
                                disabled={normalizing}
                                onClick={handleNormalizeCountries}
                                className="mt-4 inline-flex items-center gap-2 rounded-full border border-slate-200 px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                                <Globe className="h-4 w-4" />
                                {normalizing ? t('admin.merging') : t('admin.mergeCountries')}
                            </button>
                        </div>
                    </div>
                )}
            </div>

            {showAddUser && (
                <Modal title={t('admin.addUser')} onClose={() => setShowAddUser(false)}>
                    <form className="space-y-4" onSubmit={handleSubmit}>
                        <div>
                            <label className="block text-sm font-medium text-slate-700">{t('admin.username')}</label>
                            <input
                                value={form.username}
                                onChange={e => handleChange('username', e.target.value)}
                                className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:bg-white"
                                required
                                autoFocus
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-slate-700">{t('admin.password')}</label>
                            <input
                                type="password"
                                value={form.password}
                                onChange={e => handleChange('password', e.target.value)}
                                className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:bg-white"
                                required
                            />
                        </div>
                        <div className="grid gap-4 sm:grid-cols-2">
                            <div>
                                <label className="block text-sm font-medium text-slate-700">{t('admin.role')}</label>
                                <select
                                    value={form.role}
                                    onChange={e => handleChange('role', e.target.value)}
                                    className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:bg-white"
                                >
                                    <option value="user">user</option>
                                    <option value="admin">admin</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-700">{t('admin.creditLimit')}</label>
                                <input
                                    type="number"
                                    min="0"
                                    value={form.credit_limit}
                                    onChange={e => handleChange('credit_limit', e.target.value)}
                                    className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:bg-white"
                                />
                            </div>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button
                                type="button"
                                onClick={() => setShowAddUser(false)}
                                className="rounded-full border border-slate-200 px-5 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                            >
                                {t('common.close')}
                            </button>
                            <button
                                type="submit"
                                className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
                            >
                                <Plus className="h-4 w-4" />
                                {t('admin.create')}
                            </button>
                        </div>
                    </form>
                </Modal>
            )}

            {passwordModalUser && (
                <Modal title={t('admin.newPasswordFor', { username: passwordModalUser })} onClose={() => setPasswordModalUser(null)}>
                    <form className="space-y-4" onSubmit={handlePasswordSubmit}>
                        <div>
                            <label className="block text-sm font-medium text-slate-700">{t('admin.password')}</label>
                            <input
                                type="password"
                                value={passwordDraft}
                                onChange={e => setPasswordDraft(e.target.value)}
                                className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:bg-white"
                                required
                                minLength={1}
                                autoFocus
                            />
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button
                                type="button"
                                onClick={() => setPasswordModalUser(null)}
                                className="rounded-full border border-slate-200 px-5 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                            >
                                {t('common.close')}
                            </button>
                            <button
                                type="submit"
                                disabled={busyUsername === passwordModalUser}
                                className="rounded-full bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                            >
                                {t('admin.save')}
                            </button>
                        </div>
                    </form>
                </Modal>
            )}
        </div>
    );
}
