'use client';

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Loader2, ArrowRight, TrendingUp } from 'lucide-react';
import { useStockSearch } from '@/hooks/useStockSearch';
import { useRouter } from 'next/navigation';
import { getApiUrl } from '@/config';

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
                    const API_BASE_URL = getApiUrl();
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
            {/* Search Input — editorial light */}
            <motion.div
                animate={{
                    boxShadow: isFocused
                        ? '0 0 0 1px rgba(30,64,175,0.45), 0 6px 22px rgba(26,27,30,0.06)'
                        : '0 0 0 1px #E5E3DB, 0 1px 2px rgba(26,27,30,0.03)',
                }}
                transition={{ duration: 0.2 }}
                className="relative flex items-center bg-white rounded-full overflow-hidden"
            >
                <div className="pl-5 text-[#7A7F88]">
                    <Search size={18} className={isFocused ? 'text-[#1E40AF] transition-colors duration-200' : ''} />
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
                    placeholder="Search any NSE/BSE company — e.g. Reliance, TCS, Lupin"
                    className="w-full bg-transparent py-4 px-4 text-[15px] text-[#1A1B1E] outline-none placeholder:text-[#B6B8B8]"
                />

                <div className="pr-4 flex items-center gap-2">
                    {isLoading && <Loader2 size={16} className="animate-spin text-[#1E40AF]" />}
                    <kbd className="hidden sm:inline-flex px-2 py-0.5 text-[10px] font-mono text-[#7A7F88] bg-[#F2F1EB] rounded border border-[#E5E3DB] tracking-wider">
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
                        className="absolute top-full mt-2 w-full text-center text-[#B91C1C] text-xs font-medium"
                    >
                        {searchError}
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Dropdown */}
            <AnimatePresence>
                {showDropdown && (
                    <motion.div
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 6 }}
                        transition={{ duration: 0.18 }}
                        className="absolute top-full mt-2 w-full bg-white border border-[#E5E3DB] rounded-2xl shadow-lg overflow-hidden"
                    >
                        {isLoading && results.length === 0 && (
                            <div className="flex items-center justify-center gap-2 py-6 text-[#7A7F88] text-sm">
                                <Loader2 size={14} className="animate-spin text-[#1E40AF]" />
                                Searching…
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
                                className={`flex items-center justify-between px-5 py-3 cursor-pointer transition-colors ${highlightedIndex === idx
                                    ? 'bg-[#F0F4FB]'
                                    : 'hover:bg-[#FAFAF7]'
                                    }`}
                            >
                                <div className="flex items-center gap-3 min-w-0">
                                    <div className="w-8 h-8 rounded-md bg-[#F0F4FB] flex items-center justify-center flex-shrink-0">
                                        <TrendingUp size={14} className="text-[#1E40AF]" />
                                    </div>
                                    <div className="min-w-0">
                                        <p className="text-[#1A1B1E] font-medium text-sm truncate">
                                            {result.name}
                                        </p>
                                        <div className="flex items-center gap-2 mt-0.5">
                                            <span className="text-xs font-mono text-[#7A7F88]">
                                                {result.ticker}
                                            </span>
                                            {result.sector && (
                                                <span className="text-[10px] text-[#B6B8B8] truncate max-w-[140px]">
                                                    {result.sector}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                                    <span
                                        className={`text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded ${result.exchange === 'NSE'
                                            ? 'bg-[#F0F4FB] text-[#1E40AF]'
                                            : 'bg-[#FEF7E0] text-[#A16207]'
                                            }`}
                                    >
                                        {result.exchange || 'NSE'}
                                    </span>
                                    <ArrowRight
                                        size={14}
                                        className={`transition-all duration-200 ${highlightedIndex === idx
                                            ? 'text-[#1E40AF] translate-x-0.5'
                                            : 'text-[#B6B8B8]'
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
