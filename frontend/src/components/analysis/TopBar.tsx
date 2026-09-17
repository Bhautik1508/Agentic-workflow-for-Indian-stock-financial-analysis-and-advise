'use client';

import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { getApiUrl } from '@/config';
import { inr } from '@/lib/format';

interface TopBarProps {
    ticker: string;
    exchange?: string;
    /** When the verdict was produced. Undefined until a run completes. */
    timestamp?: string;
    /** True when the verdict was replayed from cache rather than computed now. */
    cached?: boolean;
}

interface PriceData {
    current_price: number;
    previous_close: number;
    change: number;
    change_pct: number;
}

/** Only `close` is read here; the API returns the full OHLCV row. */
interface PriceRecord {
    close: number | null;
}

/** A row that actually has a close. The predicate below narrows to this so the
 *  arithmetic cannot silently operate on null. */
type ClosedRow = PriceRecord & { close: number };

function hasClose(row: PriceRecord): row is ClosedRow {
    return typeof row.close === 'number' && Number.isFinite(row.close);
}

export function TopBar({ ticker, exchange = 'NSE', timestamp, cached = false }: TopBarProps) {
    const [price, setPrice] = useState<PriceData | null>(null);

    useEffect(() => {
        async function fetchPrice() {
            try {
                const API_BASE_URL = getApiUrl();
                const res = await fetch(
                    `${API_BASE_URL}/api/price-history/${encodeURIComponent(ticker)}?period=5d`,
                );
                const data = await res.json();
                // Skip rows with no close. yfinance emits a bar for the
                // still-forming session whose OHLC are null while its volume is
                // real, and `null - 1257.5` is -1257.5 in JS, not an error — so
                // every stock reported a confident -100.00%. An unknown price
                // must read as unknown, never as a catastrophic loss.
                const rows: ClosedRow[] = Array.isArray(data.data)
                    ? (data.data as PriceRecord[]).filter(hasClose)
                    : [];
                if (rows.length >= 2) {
                    const latest = rows[rows.length - 1];
                    const prev = rows[rows.length - 2];
                    const change = latest.close - prev.close;
                    setPrice({
                        current_price: latest.close,
                        previous_close: prev.close,
                        change,
                        change_pct: prev.close !== 0 ? (change / prev.close) * 100 : 0,
                    });
                }
            } catch {
                // silently fail — price is supplementary
            }
        }
        if (ticker) fetchPrice();
    }, [ticker]);

    const decodedTicker = ticker;   // already decoded by the page
    // A cached verdict says so. An entry stored before the run time was
    // recorded has no time to show, so it says only that it is cached rather
    // than inventing one.
    const stamp = timestamp
        ? (cached ? `cached \u00b7 ${timestamp}` : timestamp)
        : (cached ? 'from cache' : null);
    const isPositive = price ? price.change >= 0 : true;
    const changeColor = isPositive ? 'text-buy' : 'text-sell';
    const arrow = isPositive ? '▲' : '▼';

    return (
        <header className="sticky top-0 z-50 w-full bg-paper/95 backdrop-blur-md border-b border-rule">
            <div className="max-w-6xl mx-auto h-14 px-4 md:px-8 flex items-center justify-between gap-4">
                {/* Left: brand + ticker */}
                <div className="flex items-center gap-4 min-w-0">
                    <Link
                        href="/"
                        className="text-ink-3 hover:text-ink transition-colors shrink-0"
                        aria-label="Back to home"
                    >
                        <ArrowLeft size={16} />
                    </Link>
                    <Link href="/" className="hidden md:flex items-center gap-2 shrink-0">
                        <span className="font-serif text-[16px] font-semibold tracking-tight text-ink">StockSage</span>
                        <span className="w-px h-4 bg-rule" />
                    </Link>
                    <div className="flex items-baseline gap-2 min-w-0">
                        <span className="font-serif text-[17px] font-semibold text-ink truncate">
                            {decodedTicker}
                        </span>
                        <span className="text-[10px] font-mono tracking-widest text-ink-3 border border-rule rounded px-1.5 py-0.5 shrink-0">
                            {exchange}
                        </span>
                    </div>
                </div>

                {/* Right: live price + timestamp */}
                <div className="flex items-center gap-4 shrink-0">
                    {price && (
                        <div className="flex items-baseline gap-2">
                            <span className="font-tnum text-[15px] font-medium text-ink">
                                {inr(price.current_price, { fractionDigits: 2 })}
                            </span>
                            <span className={`font-tnum text-[12px] ${changeColor}`}>
                                {isPositive ? '+' : ''}{price.change_pct.toFixed(2)}% {arrow}
                            </span>
                        </div>
                    )}
                    {stamp && (
                        <>
                            <div className="hidden md:block w-px h-4 bg-rule" />
                            <span
                                className="hidden md:inline text-[11px] font-mono text-ink-3"
                                title={cached
                                    ? 'Replayed from cache — not re-run just now'
                                    : 'When this verdict was produced'}
                            >
                                {stamp}
                            </span>
                        </>
                    )}
                </div>
            </div>
        </header>
    );
}
