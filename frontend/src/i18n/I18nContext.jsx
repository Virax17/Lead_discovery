import React, { createContext, useContext, useMemo } from 'react';
import { translations } from './locales';

const LOCALE = 'en';
const I18nContext = createContext(null);

function resolvePath(source, path) {
    return path.split('.').reduce((value, part) => (value && Object.prototype.hasOwnProperty.call(value, part) ? value[part] : undefined), source);
}

function formatTemplate(template, vars) {
    return template.replace(/\{(\w+)\}/g, (_, key) => {
        const value = vars[key];
        return value === undefined || value === null ? '' : String(value);
    });
}

export function I18nProvider({ children }) {
    const value = useMemo(() => {
        const active = translations[LOCALE];

        const t = (key, vars = {}) => {
            const template = resolvePath(active, key) ?? key;
            if (typeof template !== 'string') {
                return key;
            }
            return formatTemplate(template, vars);
        };

        const formatNumber = (value) => new Intl.NumberFormat(LOCALE).format(value ?? 0);
        const formatCurrency = (value) => new Intl.NumberFormat(LOCALE, {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 2,
        }).format(value ?? 0);
        const formatDate = (value) => {
            if (!value) return '-';
            const date = value instanceof Date ? value : new Date(value);
            if (Number.isNaN(date.getTime())) return '-';
            return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'medium' }).format(date);
        };

        return {
            locale: LOCALE,
            t,
            formatNumber,
            formatCurrency,
            formatDate,
        };
    }, []);

    return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
    const context = useContext(I18nContext);
    if (!context) {
        throw new Error('useI18n must be used inside I18nProvider');
    }
    return context;
}
