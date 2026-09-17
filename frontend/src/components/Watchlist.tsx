'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { Bookmark, X, ArrowUpRight } from 'lucide-react';
import { loadWatchlist, removeFromWatchlist, type WatchlistEntry } from '@/lib/watchlist';
import { loadHistory, type HistoryItem } from '@/hooks/useAnalysis';
import { relativeTime } from '@/lib/format';

const VERDICT_TONE: Record<string, string> = {
    STRONG_BUY:  'text-strong-buy',
    BUY:         'text-buy',
    HOLD:        'text-hold',
    SELL:        'text-sell',
    STRONG_SELL: 'text-strong-sell',
};

export function Watchlist() {
    // Lazy initializers read localStorage exactly once on mount — avoids the
    // setState-in-effect anti-pattern. SSR returns [] thanks to the SSR-safe
    // helpers in lib/watchlist.ts and useAnalysis.ts.
    const [entries, setEntries] = useState<WatchlistEntry[]>(() => loadWatchlist());
    const [history, setHistory] = useState<HistoryItem[]>(() => loadHistory());

    const refresh = useCallback(() => {
        setEntries(loadWatchlist());
        setHistory(loadHistory());
    }, []);

    useEffect(() => {
        // Subscribe to external changes (other tabs, focus return).
        window.addEventListener('focus', refresh);
        window.addEventListener('storage', refresh);
        return () => {
            window.removeEventListener('focus', refresh);
            window.removeEventListener('storage', refresh);
        };
    }, [refresh]);

    if (entries.length === 0) return null;

    function lastVerdictFor(name: string): HistoryItem | undefined {
        const norm = name.toLowerCase().trim();
        return history.find(h => h.ticker.toLowerCase().trim() === norm);
    }

    function handleRemove(name: string) {
        setEntries(removeFromWatchlist(name));
    }

    return (
        <section className="mt-20 w-full max-w-3xl">
            <div className="flex items-baseline justify-between mb-3">
                <h2 className="heading-eyebrow">Your watchlist</h2>
                <span className="text-micro">{entries.length} {entries.length === 1 ? 'stock' : 'stocks'}</span>
            </div>
            <ul className="card-paper divide-y divide-rule-soft">
                {entries.map((e) => {
                    const last = lastVerdictFor(e.name);
                    const tone = last?.decision ? VERDICT_TONE[last.decision] : 'text-ink-3';
                    return (
                        <li key={e.name} className="flex items-center gap-3 px-4 py-3 group">
                            <Bookmark size={14} className="text-accent shrink-0" />
                            <Link
                                href={`/analyze/${encodeURIComponent(e.name)}`}
                                className="flex-1 flex items-baseline gap-3 min-w-0 hover:text-accent transition-colors"
                            >
                                <span className="font-serif text-[15px] font-medium text-ink truncate">
                                    {e.name}
                                </span>
                                {last?.decision && (
                                    <span className={`text-[11px] font-mono uppercase tracking-wider ${tone}`}>
                                        {last.decision.replace('_', ' ')}
                                    </span>
                                )}
                                {last?.confidence_score != null && (
                                    <span className="text-micro tabular">
                                        {Math.round(Math.max(0, Math.min(1, last.confidence_score)) * 100)}%
                                    </span>
                                )}
                                {last?.timestamp && (
                                    <span className="text-micro ml-auto">{relativeTime(last.timestamp)}</span>
                                )}
                                {!last && (
                                    <span className="text-micro ml-auto italic">never analysed</span>
                                )}
                                <ArrowUpRight size={14} className="text-ink-4 group-hover:text-accent transition shrink-0" />
                            </Link>
                            <button
                                onClick={() => handleRemove(e.name)}
                                aria-label={`Remove ${e.name} from watchlist`}
                                className="text-ink-4 hover:text-sell transition shrink-0 cursor-pointer"
                            >
                                <X size={14} />
                            </button>
                        </li>
                    );
                })}
            </ul>
        </section>
    );
}
