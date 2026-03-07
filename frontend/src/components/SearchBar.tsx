'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Loader2, ArrowRight } from 'lucide-react';
import { useStockSearch } from '@/hooks/useStockSearch';
import { useRouter } from 'next/navigation';

export default function SearchBar() {
    const { query, setQuery, results, isLoading } = useStockSearch();
    const [isFocused, setIsFocused] = useState(false);
    const router = useRouter();
    const [searchError, setSearchError] = useState('');

    const handleSelect = (ticker: string) => {
        setSearchError('');
        // Navigate to the analysis page for this ticker
        router.push(`/analyze/${encodeURIComponent(ticker.replace('.NS', ''))}`);
    };

    const handleKeyDown = async (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter' && query.trim()) {
            setSearchError('');
            try {
                const res = await fetch(`http://localhost:8000/api/search/${encodeURIComponent(query)}`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.results && data.results.length > 0) {
                        handleSelect(data.results[0].ticker);
                    } else {
                        setSearchError('Invalid stock symbol. Please enter a valid Indian stock.');
                    }
                } else {
                    setSearchError('Error analyzing symbol. Please try again.');
                }
            } catch {
                setSearchError('Network error checking symbol.');
            }
        }
    };

    return (
        <div className="relative w-full max-w-2xl mx-auto z-50">
            <motion.div
                animate={{
                    boxShadow: isFocused
                        ? '0 0 0 2px var(--color-primary), 0 0 20px rgba(0, 212, 255, 0.2)'
                        : '0 0 0 1px var(--color-border), 0 0 0 rgba(0,0,0,0)'
                }}
                transition={{ duration: 0.2 }}
                className="relative flex items-center bg-surface rounded-2xl overflow-hidden backdrop-blur-md"
            >
                <div className="pl-6 text-foreground/50">
                    <Search size={22} className={isFocused ? "text-primary transition-colors" : ""} />
                </div>

                <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onFocus={() => setIsFocused(true)}
                    onBlur={() => setTimeout(() => setIsFocused(false), 200)} // Delay to allow clicks on results
                    onKeyDown={handleKeyDown}
                    placeholder="Search for an Indian company (e.g., RELIANCE, TCS)..."
                    className="w-full bg-transparent py-5 px-4 text-lg text-foreground outline-none placeholder:text-foreground/40"
                />

                <div className="pr-4 flex items-center gap-2">
                    {isLoading && <Loader2 size={20} className="animate-spin text-primary" />}
                    <kbd className="hidden sm:inline-flex px-2 py-1 text-xs font-mono text-foreground/40 bg-background rounded-md border border-border">
                        ENTER
                    </kbd>
                </div>
            </motion.div>

            {searchError && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute top-full mt-2 w-full text-center text-danger text-sm font-medium"
                >
                    {searchError}
                </motion.div>
            )}

            <AnimatePresence>
                {isFocused && query && results.length > 0 && (
                    <motion.div
                        initial={{ opacity: 0, y: 10, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 10, scale: 0.98 }}
                        transition={{ duration: 0.2 }}
                        className="absolute top-full mt-3 w-full bg-surface/95 backdrop-blur-xl border border-border rounded-xl shadow-2xl overflow-hidden"
                    >
                        {results.map((result, idx) => (
                            <div
                                key={result.ticker + idx}
                                onMouseDown={(e) => {
                                    // Use onMouseDown instead of onClick to prevent onBlur from firing first
                                    e.preventDefault();
                                    handleSelect(result.ticker);
                                }}
                                className="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-white/5 transition-colors group"
                            >
                                <div>
                                    <p className="text-foreground font-medium text-lg">{result.name}</p>
                                    <p className="text-sm font-mono text-foreground/50">{result.ticker}</p>
                                </div>
                                <ArrowRight size={18} className="text-foreground/20 group-hover:text-primary group-hover:translate-x-1 transition-all" />
                            </div>
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
