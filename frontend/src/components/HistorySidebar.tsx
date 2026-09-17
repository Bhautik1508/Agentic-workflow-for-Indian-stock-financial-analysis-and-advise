'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { History, ChevronLeft, ChevronRight, Trash2, ArrowUp, ArrowDown, Minus, ChevronsUp, ChevronsDown } from 'lucide-react';
import { loadHistory, type HistoryItem, type Verdict } from '@/hooks/useAnalysis';
import Link from 'next/link';

const DECISION_CONFIG: Record<Verdict, { color: string; icon: typeof ArrowUp; bg: string; text: string }> = {
    STRONG_BUY: { color: '#166534', icon: ChevronsUp,   bg: 'bg-strong-buy-soft', text: 'text-strong-buy' },
    BUY:        { color: '#15803D', icon: ArrowUp,      bg: 'bg-buy-soft', text: 'text-buy' },
    HOLD:       { color: '#A16207', icon: Minus,        bg: 'bg-hold-soft', text: 'text-hold' },
    SELL:       { color: '#B91C1C', icon: ArrowDown,    bg: 'bg-sell-soft', text: 'text-sell' },
    STRONG_SELL:{ color: '#991B1B', icon: ChevronsDown, bg: 'bg-strong-sell-soft', text: 'text-strong-sell' },
};

function formatRelativeTime(iso: string): string {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    const h = Math.floor(diff / 3600000);
    const d = Math.floor(diff / 86400000);
    if (d >= 1) return `${d}d ago`;
    if (h >= 1) return `${h}h ago`;
    if (m >= 1) return `${m}m ago`;
    return 'just now';
}

export function HistorySidebar() {
    const [isOpen, setIsOpen] = useState(false);
    const [history, setHistory] = useState<HistoryItem[]>([]);

    // Load history from localStorage (SSR-safe)
    const refresh = useCallback(() => {
        setHistory(loadHistory());
    }, []);

    useEffect(() => {
        refresh();
        // Re-load when window regains focus (in case another tab updated)
        window.addEventListener('focus', refresh);
        return () => window.removeEventListener('focus', refresh);
    }, [refresh]);

    const clearHistory = () => {
        localStorage.removeItem('stocksage_history');
        setHistory([]);
    };

    return (
        <>
            {/* Toggle Tab */}
            <button
                onClick={() => setIsOpen((v) => !v)}
                className="fixed left-0 top-1/2 -translate-y-1/2 z-50 bg-card border border-rule border-l-0 rounded-r-xl px-2 py-4 flex flex-col items-center gap-2 text-ink-2 hover:text-accent hover:border-accent/40 transition-all cursor-pointer group"
                aria-label="Toggle history sidebar"
            >
                <History size={16} className="group-hover:text-accent transition-colors" />
                {isOpen ? (
                    <ChevronLeft size={12} className="text-ink-3" />
                ) : (
                    <ChevronRight size={12} className="text-ink-3" />
                )}
                {history.length > 0 && (
                    <span className="text-[9px] font-mono text-ink-3">{history.length}</span>
                )}
            </button>

            {/* Sidebar Panel */}
            <AnimatePresence>
                {isOpen && (
                    <motion.aside
                        initial={{ x: '-100%' }}
                        animate={{ x: 0 }}
                        exit={{ x: '-100%' }}
                        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                        className="fixed left-0 top-0 h-full z-40 w-64 bg-paper/95 backdrop-blur-xl border-r border-rule flex flex-col shadow-lg"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-4 py-4 border-b border-rule">
                            <div className="flex items-center gap-2">
                                <History size={14} className="text-accent" />
                                <span className="text-xs font-mono uppercase tracking-widest text-ink-2">
                                    Recent Analyses
                                </span>
                            </div>
                            {history.length > 0 && (
                                <button
                                    onClick={clearHistory}
                                    className="text-ink-3 hover:text-sell transition-colors cursor-pointer"
                                    title="Clear history"
                                >
                                    <Trash2 size={13} />
                                </button>
                            )}
                        </div>

                        {/* History List */}
                        <div className="flex-1 overflow-y-auto py-2">
                            {history.length === 0 ? (
                                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                                    <History size={28} className="text-ink-4 mb-3" />
                                    <p className="text-xs text-ink-3 leading-relaxed">
                                        Your recent analyses will appear here.
                                    </p>
                                </div>
                            ) : (
                                <ul className="space-y-1 px-2">
                                    {history.map((item, idx) => {
                                        const conf = item.decision ? DECISION_CONFIG[item.decision] : null;
                                        const Icon = conf?.icon ?? Minus;

                                        return (
                                            <motion.li
                                                key={item.ticker + idx}
                                                initial={{ opacity: 0, x: -10 }}
                                                animate={{ opacity: 1, x: 0 }}
                                                transition={{ delay: idx * 0.04 }}
                                            >
                                                <Link
                                                    href={`/analyze/${encodeURIComponent(item.ticker)}`}
                                                    onClick={() => setIsOpen(false)}
                                                    className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg hover:bg-paper-hover transition-colors group"
                                                >
                                                    {/* Decision badge */}
                                                    {conf ? (
                                                        <div
                                                            className={`w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 ${conf.bg}`}
                                                        >
                                                            <Icon size={12} style={{ color: conf.color }} />
                                                        </div>
                                                    ) : (
                                                        <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 bg-paper-2">
                                                            <Minus size={12} className="text-ink-3" />
                                                        </div>
                                                    )}

                                                    {/* Ticker + meta */}
                                                    <div className="flex-1 min-w-0">
                                                        <p className="text-sm font-semibold text-ink truncate group-hover:text-accent transition-colors">
                                                            {item.ticker}
                                                        </p>
                                                        <div className="flex items-center gap-1.5">
                                                            {conf && (
                                                                <span
                                                                    className={`text-[9px] font-mono font-bold ${conf.text}`}
                                                                >
                                                                    {item.decision}
                                                                </span>
                                                            )}
                                                            {item.confidence_score !== null && (
                                                                <span className="text-[9px] text-ink-3 font-mono">
                                                                    {/* Wire format is 0..1; defend against legacy entries by clamping. */}
                                                                    {Math.round(Math.max(0, Math.min(1, item.confidence_score)) * 100)}%
                                                                </span>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* Relative time */}
                                                    <span className="text-[9px] text-ink-3 font-mono flex-shrink-0">
                                                        {formatRelativeTime(item.timestamp)}
                                                    </span>
                                                </Link>
                                            </motion.li>
                                        );
                                    })}
                                </ul>
                            )}
                        </div>

                        {/* Footer */}
                        <div className="px-4 py-3 border-t border-rule">
                            <p className="text-[9px] text-ink-3 font-mono text-center">
                                Max {10} analyses stored locally
                            </p>
                        </div>
                    </motion.aside>
                )}
            </AnimatePresence>

            {/* Backdrop on mobile */}
            <AnimatePresence>
                {isOpen && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={() => setIsOpen(false)}
                        className="fixed inset-0 z-30 bg-ink/20 backdrop-blur-sm lg:hidden"
                    />
                )}
            </AnimatePresence>
        </>
    );
}
