'use client';

import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { getApiUrl } from '@/config';
import { inr } from '@/lib/format';

interface TopBarProps {
    ticker: string;
    exchange?: string;
    timestamp?: string;
}

interface PriceData {
    current_price: number;
    previous_close: number;
    change: number;
    change_pct: number;
}

export function TopBar({ ticker, exchange = 'NSE', timestamp }: TopBarProps) {
    const [price, setPrice] = useState<PriceData | null>(null);

    useEffect(() => {
        async function fetchPrice() {
            try {
                const API_BASE_URL = getApiUrl();
                const res = await fetch(
                    `${API_BASE_URL}/api/price-history/${encodeURIComponent(ticker)}?period=5d`,
                );
                const data = await res.json();
                if (data.data && data.data.length >= 2) {
                    const latest = data.data[data.data.length - 1];
                    const prev = data.data[data.data.length - 2];
                    const change = latest.close - prev.close;
                    const changePct = (change / prev.close) * 100;
                    setPrice({
                        current_price: latest.close,
                        previous_close: prev.close,
                        change,
                        change_pct: changePct,
                    });
                }
            } catch {
                // silently fail — price is supplementary
            }
        }
        if (ticker) fetchPrice();
    }, [ticker]);

    const decodedTicker = ticker;   // already decoded by the page
    const isPositive = price ? price.change >= 0 : true;
    const changeColor = isPositive ? 'text-[#15803D]' : 'text-[#B91C1C]';
    const arrow = isPositive ? '▲' : '▼';

    return (
        <header className="sticky top-0 z-50 w-full bg-[#FAFAF7]/95 backdrop-blur-md border-b border-[#E5E3DB]">
            <div className="max-w-6xl mx-auto h-14 px-4 md:px-8 flex items-center justify-between gap-4">
                {/* Left: brand + ticker */}
                <div className="flex items-center gap-4 min-w-0">
                    <Link
                        href="/"
                        className="text-[#7A7F88] hover:text-[#1A1B1E] transition-colors shrink-0"
                        aria-label="Back to home"
                    >
                        <ArrowLeft size={16} />
                    </Link>
                    <Link href="/" className="hidden md:flex items-center gap-2 shrink-0">
                        <span className="font-serif text-[16px] font-semibold tracking-tight text-[#1A1B1E]">StockSage</span>
                        <span className="w-px h-4 bg-[#E5E3DB]" />
                    </Link>
                    <div className="flex items-baseline gap-2 min-w-0">
                        <span className="font-serif text-[17px] font-semibold text-[#1A1B1E] truncate">
                            {decodedTicker}
                        </span>
                        <span className="text-[10px] font-mono tracking-widest text-[#7A7F88] border border-[#E5E3DB] rounded px-1.5 py-0.5 shrink-0">
                            {exchange}
                        </span>
                    </div>
                </div>

                {/* Right: live price + timestamp */}
                <div className="flex items-center gap-4 shrink-0">
                    {price && (
                        <div className="flex items-baseline gap-2">
                            <span className="font-tnum text-[15px] font-medium text-[#1A1B1E]">
                                {inr(price.current_price, { fractionDigits: 2 })}
                            </span>
                            <span className={`font-tnum text-[12px] ${changeColor}`}>
                                {isPositive ? '+' : ''}{price.change_pct.toFixed(2)}% {arrow}
                            </span>
                        </div>
                    )}
                    {timestamp && (
                        <>
                            <div className="hidden md:block w-px h-4 bg-[#E5E3DB]" />
                            <span className="hidden md:inline text-[11px] font-mono text-[#7A7F88]">
                                {timestamp}
                            </span>
                        </>
                    )}
                </div>
            </div>
        </header>
    );
}
