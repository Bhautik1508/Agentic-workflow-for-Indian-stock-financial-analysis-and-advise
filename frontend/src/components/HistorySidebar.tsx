'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { History, ChevronLeft, ChevronRight, Trash2, ArrowUp, ArrowDown, Minus } from 'lucide-react';
import { loadHistory, type HistoryItem } from '@/hooks/useAnalysis';
import Link from 'next/link';

const DECISION_CONFIG = {
    BUY: { color: '#00ff9f', icon: ArrowUp, bg: 'bg-[#00ff9f]/10', text: 'text-[#00ff9f]' },
    SELL: { color: '#ff4060', icon: ArrowDown, bg: 'bg-[#ff4060]/10', text: 'text-[#ff4060]' },
    HOLD: { color: '#ffd700', icon: Minus, bg: 'bg-[#ffd700]/10', text: 'text-[#ffd700]' },
} as const;

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
                className="fixed left-0 top-1/2 -translate-y-1/2 z-50 bg-surface border border-border border-l-0 rounded-r-xl px-2 py-4 flex flex-col items-center gap-2 text-text-muted hover:text-primary hover:border-primary/40 transition-all cursor-pointer group"
                aria-label="Toggle history sidebar"
            >
                <History size={16} className="group-hover:text-primary transition-colors" />
                {isOpen ? (
                    <ChevronLeft size={12} className="text-text-dim" />
                ) : (
                    <ChevronRight size={12} className="text-text-dim" />
                )}
                {history.length > 0 && (
                    <span className="text-[9px] font-mono text-text-dim">{history.length}</span>
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
                        className="fixed left-0 top-0 h-full z-40 w-64 bg-background/95 backdrop-blur-xl border-r border-border flex flex-col shadow-2xl"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-4 py-4 border-b border-border/60">
                            <div className="flex items-center gap-2">
                                <History size={14} className="text-primary" />
                                <span className="text-xs font-mono uppercase tracking-widest text-text-muted">
                                    Recent Analyses
                                </span>
                            </div>
                            {history.length > 0 && (
                                <button
                                    onClick={clearHistory}
                                    className="text-text-dim hover:text-danger transition-colors cursor-pointer"
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
                                    <History size={28} className="text-border mb-3" />
                                    <p className="text-xs text-text-dim leading-relaxed">
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
                                                    className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg hover:bg-white/[0.04] transition-colors group"
                                                >
                                                    {/* Decision badge */}
                                                    {conf ? (
                                                        <div
                                                            className={`w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 ${conf.bg}`}
                                                        >
                                                            <Icon size={12} style={{ color: conf.color }} />
                                                        </div>
                                                    ) : (
                                                        <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 bg-border/30">
                                                            <Minus size={12} className="text-text-dim" />
                                                        </div>
                                                    )}

                                                    {/* Ticker + meta */}
                                                    <div className="flex-1 min-w-0">
                                                        <p className="text-sm font-semibold text-foreground/90 truncate group-hover:text-primary transition-colors">
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
                                                                <span className="text-[9px] text-text-dim font-mono">
                                                                    {(item.confidence_score * 10).toFixed(0)}%
                                                                </span>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* Relative time */}
                                                    <span className="text-[9px] text-text-dim font-mono flex-shrink-0">
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
                        <div className="px-4 py-3 border-t border-border/60">
                            <p className="text-[9px] text-text-dim font-mono text-center">
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
                        className="fixed inset-0 z-30 bg-black/30 backdrop-blur-sm lg:hidden"
                    />
                )}
            </AnimatePresence>
        </>
    );
}
