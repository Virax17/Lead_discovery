import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, Plus, X, Sparkles, ShieldAlert } from 'lucide-react';
import { createSearch, fetchCities, fetchStates } from '../api';
import { useI18n } from '../i18n/I18nContext';
import { useShell } from '../context/ShellContext';
import Combobox from './Combobox';
import LocationPicker from './LocationPicker';

// Matches MAX_FANOUT_LOCATIONS in backend/app/services/search_runner.py.
const MAX_FANOUT_LOCATIONS = 25;

const DEFAULT_KEYWORDS = [
    'Industrial shutdown contractor',
    'Turnaround maintenance contractor',
    'Refinery maintenance contractor',
    'Petrochemical plant maintenance',
    'Fertilizer plant maintenance contractor',
    'Grain elevator maintenance contractor',
    'Pipeline maintenance contractor',
    'Pipeline integrity contractor',
    'Hot tapping contractor',
    'Onsite machining contractor',
    'Flange bolting contractor',
    'Heat exchanger retubing contractor',
    'Power plant maintenance contractor',
    'Steel plant maintenance contractor',
    'Wind turbine maintenance contractor',
    'Oil and gas EPC contractor',
    'Structural steel erection contractor',
    'Bridge construction contractor'
];

const DEFAULT_INDUSTRIES = [
    'Oil and gas',
    'Petrochemical',
    'Wind energy',
    'Power',
    'Fertilizer',
    'Agriculture',
    'Steel',
    'Heavy engineering',
    'Heavy civil/Infrastructure',
    'Industrial EPC'
];

function TagEditor({ label, items, setItems, placeholder, addLabel }) {
    const [draft, setDraft] = useState('');

    const addItem = () => {
        const value = draft.trim();
        if (!value) return;
        if (items.some(item => item.toLowerCase() === value.toLowerCase())) {
            setDraft('');
            return;
        }
        setItems([...items, value]);
        setDraft('');
    };

    return (
        <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-700">{label}</label>
            <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
                {items.map(item => (
                    <span key={item} className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-1 text-sm text-white">
                        {item}
                        <button type="button" onClick={() => setItems(items.filter(existing => existing !== item))} className="text-white/70 hover:text-white" aria-label={`Remove ${item}`}>
                            <X className="h-3 w-3" />
                        </button>
                    </span>
                ))}
                <input
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            addItem();
                        }
                    }}
                    placeholder={placeholder}
                    className="min-w-[220px] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-slate-400"
                />
                <button
                    type="button"
                    onClick={addItem}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-sm font-medium text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                >
                    <Plus className="h-3 w-3" />
                    {addLabel}
                </button>
            </div>
        </div>
    );
}

export default function Dashboard() {
    const navigate = useNavigate();
    const { t, formatNumber, formatCurrency } = useI18n();
    const { quota, quotaLoading, countries, countriesLoading } = useShell();
    const [step, setStep] = useState('setup');
    const [country, setCountry] = useState({ name: 'India', code: null });
    const [stateSel, setStateSel] = useState(null);
    const [citySel, setCitySel] = useState(null);
    const [useCustomArea, setUseCustomArea] = useState(false);
    const [customCenter, setCustomCenter] = useState(null);
    const [customRadiusKm, setCustomRadiusKm] = useState(25);
    const [states, setStates] = useState([]);
    const [statesLoading, setStatesLoading] = useState(false);
    const [cities, setCities] = useState([]);
    const [citiesLoading, setCitiesLoading] = useState(false);
    const [maxResults, setMaxResults] = useState(100);
    const [websiteOnly, setWebsiteOnly] = useState(false);
    const [keywords, setKeywords] = useState(DEFAULT_KEYWORDS);
    const [industries, setIndustries] = useState(DEFAULT_INDUSTRIES);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Backfill the ISO code for the hardcoded default country once the list loads.
    useEffect(() => {
        if (!country.code && countries.length) {
            const match = countries.find(c => c.name.toLowerCase() === country.name.toLowerCase());
            if (match) setCountry(match);
        }
    }, [countries, country.code, country.name]);

    // Country changed: reload its states, reset state/city selection.
    useEffect(() => {
        let cancelled = false;
        setStateSel(null);
        setCitySel(null);
        setCities([]);
        if (!country.code) {
            setStates([]);
            return undefined;
        }
        setStatesLoading(true);
        fetchStates(country.code)
            .then(data => { if (!cancelled) setStates(data); })
            .catch(() => { if (!cancelled) setStates([]); })
            .finally(() => { if (!cancelled) setStatesLoading(false); });
        return () => { cancelled = true; };
    }, [country.code]);

    // State changed: reload its cities, reset city selection.
    useEffect(() => {
        let cancelled = false;
        setCitySel(null);
        if (!country.code || !stateSel?.code) {
            setCities([]);
            return undefined;
        }
        setCitiesLoading(true);
        fetchCities(country.code, stateSel.code)
            .then(data => { if (!cancelled) setCities(data); })
            .catch(() => { if (!cancelled) setCities([]); })
            .finally(() => { if (!cancelled) setCitiesLoading(false); });
        return () => { cancelled = true; };
    }, [country.code, stateSel]);

    const countryCode = country.code;
    const allStatesOption = useMemo(() => ({ name: t('common.anyState'), code: '__all__' }), [t]);
    const allCitiesOption = useMemo(() => ({ name: t('common.anyCity'), code: '__all__' }), [t]);

    const quotaPlan = quota?.active_plan === 'paid_overage' ? t('app.paidOverage') : t('app.free');
    const quotaUsed = quota?.calls_used ?? 0;
    const quotaLimit = quota?.quota_block_threshold ?? 1000;
    const quotaOverage = quota?.overage_cost_estimate ?? 0;
    // No state/city selected -> the backend auto-fans the search across a
    // bounded set of the country's states, each searched with a real
    // locationBias circle (see run_region_search's fan-out). Capped at
    // MAX_FANOUT_LOCATIONS (matches the backend's own cap) rather than raw
    // state count, since state count varies arbitrarily by country and has
    // nothing to do with how large or business-dense it actually is — the
    // cap keeps cost bounded and predictable the same way for every country.
    // A custom-drawn circle is a deliberate, exact request -- always exactly
    // one location, never the country-level fan-out.
    const isFanningOut = !useCustomArea && !stateSel?.name && !citySel?.name;
    const locationCount = isFanningOut ? Math.min(Math.max(states.length, 1), MAX_FANOUT_LOCATIONS) : 1;
    const pagesPerLocation = Math.max(1, Math.ceil(Number(maxResults || 1) / 20));
    const estimatedCalls = useMemo(
        () => keywords.length * locationCount * pagesPerLocation,
        [keywords.length, locationCount, pagesPerLocation]
    );
    const projectedUsage = (quota?.calls_used ?? 0) + estimatedCalls;
    const projectedOverage = quota ? Math.max(0, projectedUsage - quotaLimit) : 0;
    const searchWouldBlock = quota ? !quota.allow_paid_overage && projectedUsage > quotaLimit : false;

    const payload = {
        country: country.name,
        country_code: countryCode,
        state: useCustomArea ? null : (stateSel?.name || null),
        city: useCustomArea ? null : (citySel?.name || null),
        center_lat: useCustomArea ? customCenter?.lat ?? null : null,
        center_lng: useCustomArea ? customCenter?.lng ?? null : null,
        radius_km: useCustomArea ? customRadiusKm : null,
        max_results: Number(maxResults),
        keywords,
        industries,
        website_only: websiteOnly
    };

    const reviewSearch = (event) => {
        event.preventDefault();
        setError('');

        if (keywords.length === 0) {
            setError(t('dashboard.addAtLeastOneKeyword'));
            return;
        }
        if (industries.length === 0) {
            setError(t('dashboard.addAtLeastOneIndustry'));
            return;
        }
        if (useCustomArea && !customCenter) {
            setError(t('dashboard.customAreaNeedsCenter'));
            return;
        }

        setStep('preview');
    };

    const startSearch = async () => {
        setError('');
        setLoading(true);
        try {
            const data = await createSearch(payload);
            navigate(`/search/${data.search_id}/progress`);
        } catch (err) {
            setError(err.message || t('dashboard.failedToStart'));
            setLoading(false);
        }
    };

    return (
        <div className="mx-auto max-w-6xl space-y-6">
            <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-[0_20px_80px_rgba(15,23,42,0.08)]">
                <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_55%,#38bdf8_100%)] px-8 py-10 text-white">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                            <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-white/90">
                                <Sparkles className="h-3 w-3" />
                                {t('dashboard.setupTag')}
                            </p>
                            <h2 className="text-4xl font-semibold tracking-tight">{t('dashboard.setupHeading')}</h2>
                            <p className="mt-3 max-w-2xl text-sm text-slate-100/90">
                                {t('dashboard.setupSubtitle')}
                            </p>
                            <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-medium text-white/90">
                                {[t('dashboard.heroStep1'), t('dashboard.heroStep2'), t('dashboard.heroStep3')].map((step, index) => (
                                    <span key={step} className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5">
                                        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-white/20 text-[10px] font-semibold">{index + 1}</span>
                                        {step}
                                    </span>
                                ))}
                            </div>
                        </div>
                        <div className="rounded-3xl border border-white/20 bg-white/10 p-5 backdrop-blur">
                            <p className="text-xs uppercase tracking-[0.2em] text-white/70">{t('dashboard.quotaSnapshot')}</p>
                            {quotaLoading ? (
                                <p className="mt-3 text-sm text-white/80">{t('dashboard.loadingQuota')}</p>
                            ) : quota ? (
                                <div className="mt-3 space-y-2 text-sm text-white">
                                    <div className="flex items-center justify-between gap-6">
                                        <span>{t('dashboard.plan')}</span>
                                        <span className="font-semibold capitalize">{quotaPlan}</span>
                                    </div>
                                    <div className="flex items-center justify-between gap-6">
                                        <span>{t('dashboard.used')}</span>
                                        <span className="font-semibold">{formatNumber(quotaUsed)} / {formatNumber(quotaLimit)}</span>
                                    </div>
                                    <div className="flex items-center justify-between gap-6">
                                        <span>{t('dashboard.overage')}</span>
                                        <span className="font-semibold">{formatCurrency(quotaOverage)}</span>
                                    </div>
                                </div>
                            ) : (
                                <p className="mt-3 text-sm text-white/80">{t('dashboard.loadingQuota')}</p>
                            )}
                        </div>
                    </div>
                </div>

                <div className="grid gap-0 xl:grid-cols-[1.3fr_0.9fr]">
                    <div className="p-8">
                        {error && (
                            <div className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                                {error}
                            </div>
                        )}

                        {step === 'setup' ? (
                            <form onSubmit={reviewSearch} className="space-y-6">
                                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                                    <Combobox
                                        label={t('dashboard.country')}
                                        value={country}
                                        onChange={item => item && setCountry(item)}
                                        items={countries}
                                        getKey={c => c.code}
                                        loading={countriesLoading}
                                        placeholder={t('dashboard.searchCountry')}
                                    />
                                    {!useCustomArea && (
                                        <>
                                            <Combobox
                                                label={t('dashboard.stateRegion')}
                                                value={stateSel || allStatesOption}
                                                onChange={item => setStateSel(!item || item.code === '__all__' ? null : item)}
                                                items={[allStatesOption, ...states]}
                                                getKey={s => s.code}
                                                loading={statesLoading}
                                                disabled={!country.code}
                                                placeholder={t('dashboard.searchState')}
                                            />
                                            <Combobox
                                                label={t('dashboard.city')}
                                                value={citySel || allCitiesOption}
                                                onChange={item => setCitySel(!item || item.code === '__all__' ? null : item)}
                                                items={[allCitiesOption, ...cities]}
                                                getKey={c => c.code ?? c.name}
                                                loading={citiesLoading}
                                                disabled={!stateSel}
                                                placeholder={stateSel ? t('dashboard.searchCity') : t('dashboard.selectStateFirst')}
                                            />
                                        </>
                                    )}
                                </div>

                                <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                                    <div>
                                        <p className="text-sm font-medium text-slate-700">{t('dashboard.customAreaLabel')}</p>
                                        <p className="text-xs text-slate-500">{t('dashboard.customAreaHint')}</p>
                                    </div>
                                    <label className="relative inline-flex cursor-pointer items-center">
                                        <input
                                            type="checkbox"
                                            checked={useCustomArea}
                                            onChange={e => {
                                                setUseCustomArea(e.target.checked);
                                                if (e.target.checked) {
                                                    setStateSel(null);
                                                    setCitySel(null);
                                                } else {
                                                    setCustomCenter(null);
                                                }
                                            }}
                                            className="peer sr-only"
                                        />
                                        <div className="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-blue-600 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:after:translate-x-5" />
                                    </label>
                                </div>

                                {useCustomArea && (
                                    <LocationPicker
                                        center={customCenter}
                                        radiusKm={customRadiusKm}
                                        onChange={({ lat, lng, radiusKm }) => {
                                            setCustomCenter({ lat, lng });
                                            setCustomRadiusKm(radiusKm);
                                        }}
                                    />
                                )}

                                <div className="grid gap-4 sm:grid-cols-2">
                                    <div>
                                        <label className="block text-sm font-medium text-slate-700">{t('dashboard.maxResults')}</label>
                                        <input
                                            type="number"
                                            min="1"
                                            max="100"
                                            value={maxResults}
                                            onChange={e => setMaxResults(Math.min(100, Math.max(1, parseInt(e.target.value || '1', 10))))}
                                            className="mt-1 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-blue-500 focus:bg-white"
                                        />
                                    </div>
                                    <div className="flex items-end">
                                        <label className="flex w-full items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700">
                                            <span>{t('dashboard.websiteOnly')}</span>
                                            <input type="checkbox" checked={websiteOnly} onChange={e => setWebsiteOnly(e.target.checked)} className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                                        </label>
                                    </div>
                                </div>

                                <TagEditor
                                    label={t('dashboard.keywords')}
                                    items={keywords}
                                    setItems={setKeywords}
                                    placeholder={t('dashboard.addKeyword')}
                                    addLabel={t('dashboard.add')}
                                />

                                <TagEditor
                                    label={t('dashboard.industryTypes')}
                                    items={industries}
                                    setItems={setIndustries}
                                    placeholder={t('dashboard.addIndustry')}
                                    addLabel={t('dashboard.add')}
                                />

                                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                                    {t('dashboard.estimatedCalls')}: <span className="font-semibold text-slate-900">{formatNumber(estimatedCalls)}</span>
                                    {quota && (
                                        <span className="ml-3">
                                            {t('dashboard.projectedOverage')}: <span className="font-semibold text-slate-900">{formatNumber(projectedOverage)}</span>
                                        </span>
                                    )}
                                    <p className="mt-2 text-xs text-slate-500">{t('dashboard.estimatedCallsNote')}</p>
                                </div>

                                <div className="flex items-center justify-between gap-4 border-t border-slate-200 pt-6">
                                    <p className="text-sm text-slate-500">{t('dashboard.step1')}</p>
                                    <button type="submit" className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60">
                                        {t('dashboard.reviewSummary')}
                                        <ChevronRight className="h-4 w-4" />
                                    </button>
                                </div>
                            </form>
                        ) : (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between gap-4">
                                    <div>
                                        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">{t('dashboard.previewSummary')}</p>
                                        <h3 className="mt-2 text-2xl font-semibold text-slate-900">{t('dashboard.confirmTitle')}</h3>
                                    </div>
                                    <button type="button" onClick={() => setStep('setup')} className="rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                                        {t('dashboard.backToSetup')}
                                    </button>
                                </div>

                                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                                    <SummaryCard label={t('dashboard.region')} value={country.name} />
                                    <SummaryCard
                                        label={t('dashboard.scope')}
                                        value={useCustomArea && customCenter
                                            ? `${t('dashboard.customAreaLabel')} · ${customRadiusKm}km radius`
                                            : `${stateSel?.name || t('common.anyState')} · ${citySel?.name || t('common.anyCity')}`}
                                    />
                                    <SummaryCard label={t('dashboard.websiteFilter')} value={websiteOnly ? t('dashboard.enabled') : t('dashboard.disabled')} />
                                    <SummaryCard label={t('dashboard.keywords')} value={t('dashboard.selected', { count: formatNumber(keywords.length) })} />
                                    <SummaryCard label={t('dashboard.industryTypes')} value={t('dashboard.selected', { count: formatNumber(industries.length) })} />
                                    <SummaryCard label={t('dashboard.maxResults')} value={`${formatNumber(maxResults)} ${t('dashboard.perKeyword')}`} />
                                </div>

                                <div className="grid gap-4 rounded-3xl border border-slate-200 bg-slate-50 p-5 sm:grid-cols-2">
                                    <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('dashboard.quotaImpact')}</p>
                                        <p className="mt-2 text-lg font-semibold text-slate-900">{t('dashboard.estimatedCallsLabel', { count: formatNumber(estimatedCalls) })}</p>
                                        <p className="mt-1 text-sm text-slate-600">
                                            {isFanningOut
                                                ? `${t('dashboard.estimatedCalls')} = ${formatNumber(keywords.length)} keywords x ${formatNumber(locationCount)} locations in ${country.name} x ${formatNumber(pagesPerLocation)} page(s).`
                                                : `${t('dashboard.estimatedCalls')} = ${formatNumber(keywords.length)} keywords x ${formatNumber(pagesPerLocation)} page(s).`}
                                        </p>
                                        {useCustomArea && (
                                            <p className="mt-1 text-sm text-amber-700">
                                                Searching a single {formatNumber(customRadiusKm)}km-radius circle you drew on the map — this is an exact, deterministic count, not an estimate: it will always be exactly {formatNumber(keywords.length)} keywords x {formatNumber(pagesPerLocation)} page(s), with no fan-out or drill-down.
                                            </p>
                                        )}
                                        {isFanningOut && (
                                            <p className="mt-1 text-sm text-amber-700">
                                                No state or city selected — this will automatically search a real 50km-radius area around up to {formatNumber(locationCount)} location{locationCount === 1 ? '' : 's'} in {country.name}
                                                {states.length > MAX_FANOUT_LOCATIONS
                                                    ? ` (capped at ${formatNumber(MAX_FANOUT_LOCATIONS)}, the busiest of its ${formatNumber(states.length)} states/regions)`
                                                    : ''}
                                                . The actual number searched is often lower — nearby locations that would overlap are automatically merged into one. This is a typical estimate: any location+keyword combo already searched recently costs nothing to repeat, but dense states/regions may automatically drill down into a few of their cities for deeper coverage when the state-level search alone doesn't capture everything, so actual calls can run higher than this estimate in those cases.
                                            </p>
                                        )}
                                        <p className="mt-2 text-sm text-slate-600">
                                            Final businesses can be lower after duplicate removal, website-only filtering, and country matching.
                                        </p>
                                    </div>
                                    <div>
                                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{t('dashboard.quotaUsage')}</p>
                                        <p className="mt-2 text-lg font-semibold text-slate-900">
                                            {t('dashboard.projectedUsageLabel', {
                                                usage: formatNumber(projectedUsage),
                                                limit: formatNumber(quota ? quota.quota_block_threshold : 1000),
                                            })}
                                        </p>
                                        <p className={`mt-1 text-sm ${searchWouldBlock ? 'text-rose-700' : 'text-slate-600'}`}>
                                            {searchWouldBlock ? t('dashboard.searchWouldBlock') : t('dashboard.runFits')}
                                        </p>
                                    </div>
                                </div>

                                <div className="rounded-3xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
                                    <div className="flex items-start gap-3">
                                        <ShieldAlert className="mt-0.5 h-5 w-5 text-amber-700" />
                                        <div>
                                            <p className="font-semibold">{t('dashboard.beforeStarting')}</p>
                                            <p className="mt-1 text-amber-800">{t('dashboard.beforeStartingBody')}</p>
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between gap-4 border-t border-slate-200 pt-6">
                                    <p className="text-sm text-slate-500">{t('dashboard.step2')}</p>
                                    <button type="button" onClick={startSearch} disabled={loading} className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60">
                                        {loading ? t('dashboard.startingSearch') : t('dashboard.confirmAndStart')}
                                        <ChevronRight className="h-4 w-4" />
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>

                    <aside className="border-t border-slate-200 bg-slate-50/80 p-8 xl:border-l xl:border-t-0">
                        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">{t('dashboard.searchDefaults')}</p>
                        <div className="mt-4 space-y-3 text-sm text-slate-600">
                            <p>{t('dashboard.searchDefaults1')}</p>
                            <p>{t('dashboard.searchDefaults2')}</p>
                            <p>{t('dashboard.searchDefaults3')}</p>
                        </div>
                    </aside>
                </div>
            </div>
        </div>
    );
}

function SummaryCard({ label, value }) {
    return (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">{label}</p>
            <p className="mt-2 text-sm font-medium text-slate-900">{value}</p>
        </div>
    );
}
