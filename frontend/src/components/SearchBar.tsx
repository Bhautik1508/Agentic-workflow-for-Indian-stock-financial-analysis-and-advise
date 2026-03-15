'use client';

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Loader2, ArrowRight, TrendingUp } from 'lucide-react';
import { useStockSearch } from '@/hooks/useStockSearch';
import { useRouter } from 'next/navigation';

export default function SearchBar() {
    const { query, setQuery, results, isLoading } = useStockSearch();
    const [isFocused, setIsFocused] = useState(false);
    const [highlightedIndex, setHighlightedIndex] = useState(-1);
    const [searchError, setSearchError] = useState('');
    const router = useRouter();
    const inputRef = useRef<HTMLInputElement>(null);

    const handleSelect = useCallback((companyName: string) => {
        setSearchError('');
        setQuery('');
        router.push(`/analyze/${encodeURIComponent(companyName)}`);
    }, [router, setQuery]);

    const handleKeyDown = async (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlightedIndex((prev) =>
                prev < results.length - 1 ? prev + 1 : 0
            );
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlightedIndex((prev) =>
                prev > 0 ? prev - 1 : results.length - 1
            );
        } else if (e.key === 'Enter') {
            e.preventDefault();
            setSearchError('');

            if (highlightedIndex >= 0 && results[highlightedIndex]) {
                // Navigate using highlighted result's ticker
                const selected = results[highlightedIndex];
                handleSelect(selected.ticker.replace('.NS', '').replace('.BO', ''));
                return;
            }

            if (query.trim()) {
                try {
                    const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
                    const res = await fetch(
                        `${API_BASE_URL}/api/search/${encodeURIComponent(query)}`
                    );
                    if (res.ok) {
                        const data = await res.json();
                        if (data.results && data.results.length > 0) {
                            const first = data.results[0];
                            handleSelect(first.ticker.replace('.NS', '').replace('.BO', ''));
                        } else {
                            setSearchError('No matching Indian stock found. Try a different name.');
                        }
                    } else {
                        setSearchError('Error searching. Please try again.');
                    }
                } catch {
                    setSearchError('Network error. Check your connection.');
                }
            }
        } else if (e.key === 'Escape') {
            setIsFocused(false);
            inputRef.current?.blur();
        }
    };

    const showDropdown = isFocused && query.length >= 2 && (results.length > 0 || isLoading);

    return (
        <div className="relative w-full max-w-2xl mx-auto z-50">
            {/* Search Input */}
            <motion.div
                animate={{
                    boxShadow: isFocused
                        ? '0 0 0 1px rgba(0,212,255,0.6), 0 0 30px rgba(0,212,255,0.12), 0 0 60px rgba(0,212,255,0.04)'
                        : '0 0 0 1px rgba(26,37,64,0.8)',
                }}
                transition={{ duration: 0.25 }}
                className="relative flex items-center bg-surface rounded-full overflow-hidden"
            >
                <div className="pl-5 text-text-muted">
                    <Search size={20} className={isFocused ? 'text-primary transition-colors duration-200' : ''} />
                </div>

                <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={(e) => {
                        setQuery(e.target.value);
                        setHighlightedIndex(-1);
                        setSearchError('');
                    }}
                    onFocus={() => setIsFocused(true)}
                    onBlur={() => setTimeout(() => setIsFocused(false), 200)}
                    onKeyDown={handleKeyDown}
                    placeholder="Search for an Indian company (e.g., RELIANCE, TCS)..."
                    className="w-full bg-transparent py-4 px-4 text-base text-foreground outline-none placeholder:text-text-dim"
                />

                <div className="pr-4 flex items-center gap-2">
                    {isLoading && <Loader2 size={18} className="animate-spin text-primary" />}
                    <kbd className="hidden sm:inline-flex px-2 py-1 text-[10px] font-mono text-text-dim bg-background/60 rounded border border-border/60 tracking-wider">
                        ENTER
                    </kbd>
                </div>
            </motion.div>

            {/* Error */}
            <AnimatePresence>
                {searchError && (
                    <motion.div
                        initial={{ opacity: 0, y: -5 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -5 }}
                        className="absolute top-full mt-2 w-full text-center text-danger text-xs font-medium"
                    >
                        {searchError}
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Dropdown */}
            <AnimatePresence>
                {showDropdown && (
                    <motion.div
                        initial={{ opacity: 0, y: 8, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 8, scale: 0.98 }}
                        transition={{ duration: 0.2 }}
                        className="absolute top-full mt-2 w-full bg-surface border border-border rounded-2xl shadow-2xl overflow-hidden backdrop-blur-xl"
                    >
                        {isLoading && results.length === 0 && (
                            <div className="flex items-center justify-center gap-2 py-6 text-text-muted text-sm">
                                <Loader2 size={16} className="animate-spin text-primary" />
                                Searching...
                            </div>
                        )}

                        {results.map((result, idx) => (
                            <div
                                key={result.ticker + idx}
                                onMouseDown={(e) => {
                                    e.preventDefault();
                                    handleSelect(result.ticker.replace('.NS', '').replace('.BO', ''));
                                }}
                                onMouseEnter={() => setHighlightedIndex(idx)}
                                className={`flex items-center justify-between px-5 py-3.5 cursor-pointer transition-colors group ${highlightedIndex === idx
                                    ? 'bg-primary/8'
                                    : 'hover:bg-white/[0.03]'
                                    }`}
                            >
                                <div className="flex items-center gap-3 min-w-0">
                                    <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                                        <TrendingUp size={14} className="text-primary" />
                                    </div>
                                    <div className="min-w-0">
                                        <p className="text-foreground font-medium text-sm truncate">
                                            {result.name}
                                        </p>
                                        <div className="flex items-center gap-2 mt-0.5">
                                            <span className="text-xs font-mono text-text-muted">
                                                {result.ticker}
                                            </span>
                                            {result.sector && (
                                                <span className="text-[10px] text-text-dim truncate max-w-[140px]">
                                                    {result.sector}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                                    {/* Exchange badge */}
                                    <span
                                        className={`text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded ${result.exchange === 'NSE'
                                            ? 'bg-primary/15 text-primary'
                                            : 'bg-warning/15 text-warning'
                                            }`}
                                    >
                                        {result.exchange || 'NSE'}
                                    </span>
                                    <ArrowRight
                                        size={14}
                                        className={`transition-all duration-200 ${highlightedIndex === idx
                                            ? 'text-primary translate-x-0.5'
                                            : 'text-text-dim'
                                            }`}
                                    />
                                </div>
                            </div>
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
