import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { fetchCountries, fetchQuota } from '../api';

const ShellContext = createContext(null);

export function ShellProvider({ children }) {
    const [quota, setQuota] = useState(null);
    const [quotaLoading, setQuotaLoading] = useState(true);
    const [countries, setCountries] = useState([]);
    const [countriesLoading, setCountriesLoading] = useState(true);
    const [currentUser, setCurrentUser] = useState(null);

    const refreshQuota = useCallback(async () => {
        const hasToken = Boolean(localStorage.getItem('token'));
        if (!hasToken) {
            setQuota(null);
            setCurrentUser(null);
            setQuotaLoading(false);
            return null;
        }

        setQuotaLoading(true);
        try {
            const data = await fetchQuota();
            setQuota(data);
            setCurrentUser(data?.user || null);
            return data;
        } catch {
            setQuota(null);
            setCurrentUser(null);
            return null;
        } finally {
            setQuotaLoading(false);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        const hasToken = Boolean(localStorage.getItem('token'));

        if (!hasToken) {
            setQuota(null);
            setCurrentUser(null);
            setCountries([]);
            setQuotaLoading(false);
            setCountriesLoading(false);
            return undefined;
        }

        const loadQuota = async () => {
            setQuotaLoading(true);
            try {
                const data = await fetchQuota();
                if (!cancelled) {
                    setQuota(data);
                    setCurrentUser(data?.user || null);
                }
            } catch {
                if (!cancelled) {
                    setQuota(null);
                    setCurrentUser(null);
                }
            } finally {
                if (!cancelled) {
                    setQuotaLoading(false);
                }
            }
        };

        const loadCountries = async () => {
            setCountriesLoading(true);
            try {
                const data = await fetchCountries();
                if (!cancelled) {
                    setCountries(data);
                }
            } catch {
                if (!cancelled) {
                    setCountries([]);
                }
            } finally {
                if (!cancelled) {
                    setCountriesLoading(false);
                }
            }
        };

        loadQuota();
        loadCountries();

        return () => {
            cancelled = true;
        };
    }, []);

    const value = useMemo(() => ({
        quota,
        quotaLoading,
        countries,
        countriesLoading,
        currentUser,
        refreshQuota,
    }), [quota, quotaLoading, countries, countriesLoading, currentUser, refreshQuota]);

    return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell() {
    const context = useContext(ShellContext);
    if (!context) {
        throw new Error('useShell must be used inside ShellProvider');
    }
    return context;
}
