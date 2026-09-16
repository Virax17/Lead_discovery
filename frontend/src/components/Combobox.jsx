import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

export default function Combobox({
    label,
    required = false,
    value,
    onChange,
    items,
    getLabel = item => item.name,
    getKey = item => item.code ?? item.name,
    placeholder = '',
    loading = false,
    disabled = false,
    emptyMessage = 'No matches found.',
}) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [highlighted, setHighlighted] = useState(0);
    const containerRef = useRef(null);
    const inputRef = useRef(null);

    // Only re-sync the visible text from `value` itself - `getLabel` is intentionally
    // excluded here since callers without a custom getLabel get a new default-param
    // function reference on every render, which would reset the input on every keystroke.
    useEffect(() => {
        setQuery(value ? getLabel(value) : '');
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value]);

    useEffect(() => {
        function handleClickOutside(event) {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setOpen(false);
                setQuery(value ? getLabel(value) : '');
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [value, getLabel]);

    const filtered = useMemo(() => {
        const normalized = query.trim().toLowerCase();
        const isCurrentValue = value && normalized === getLabel(value).toLowerCase();
        if (!normalized || isCurrentValue) return items;
        return items.filter(item => getLabel(item).toLowerCase().includes(normalized));
    }, [items, query, value, getLabel]);

    const selectItem = (item) => {
        onChange(item);
        setQuery(item ? getLabel(item) : '');
        setOpen(false);
    };

    const handleKeyDown = (event) => {
        if (!open && (event.key === 'ArrowDown' || event.key === 'Enter')) {
            setOpen(true);
            return;
        }
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setHighlighted(h => Math.min(h + 1, filtered.length - 1));
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setHighlighted(h => Math.max(h - 1, 0));
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (filtered[highlighted]) selectItem(filtered[highlighted]);
        } else if (event.key === 'Escape') {
            setOpen(false);
            setQuery(value ? getLabel(value) : '');
        }
    };

    return (
        <div ref={containerRef} className="relative">
            {label && (
                <label className="block text-sm font-medium text-slate-700">
                    {label}{required ? ' *' : ''}
                </label>
            )}
            <div className="relative mt-1">
                <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    disabled={disabled}
                    placeholder={loading ? 'Loading...' : placeholder}
                    onChange={e => {
                        setQuery(e.target.value);
                        setHighlighted(0);
                        if (!open) setOpen(true);
                        if (e.target.value === '') onChange(null);
                    }}
                    onFocus={() => setOpen(true)}
                    onKeyDown={handleKeyDown}
                    className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 pr-9 text-sm outline-none transition focus:border-blue-500 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                />
                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            </div>

            {open && !disabled && (
                <div className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-2xl border border-slate-200 bg-white py-1 shadow-lg">
                    {filtered.length === 0 && (
                        <p className="px-4 py-3 text-sm text-slate-400">{emptyMessage}</p>
                    )}
                    {filtered.map((item, index) => {
                        const key = getKey(item);
                        const isSelected = value && getKey(value) === key;
                        return (
                            <button
                                type="button"
                                key={key ?? index}
                                onMouseDown={e => e.preventDefault()}
                                onClick={() => selectItem(item)}
                                className={`block w-full px-4 py-2 text-left text-sm ${
                                    index === highlighted ? 'bg-slate-100' : ''
                                } ${isSelected ? 'font-semibold text-blue-600' : 'text-slate-700'} hover:bg-slate-100`}
                            >
                                {getLabel(item)}
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
