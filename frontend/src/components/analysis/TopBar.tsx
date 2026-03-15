'use client';

import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';

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
                const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
                const res = await fetch(`${API_BASE_URL}/api/price-history/${ticker}?period=5d`);
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

    const decodedTicker = decodeURIComponent(ticker);
    const isPositive = price ? price.change >= 0 : true;
    const changeColor = isPositive ? 'text-[#3d9970]' : 'text-[#c0444a]';
    const arrow = isPositive ? '▲' : '▼';

    return (
        <div className="sticky top-0 z-50 w-full bg-[#07090f]/95 backdrop-blur-md border-b border-white/[0.06]">
            <div className="max-w-7xl mx-auto h-12 px-4 md:px-6 flex items-center justify-between">
                {/* Left: Back + Ticker */}
                <div className="flex items-center gap-3">
                    <Link
                        href="/"
                        className="text-[#7888a5] hover:text-[#dce4f5] transition-colors"
                    >
                        <ArrowLeft size={16} />
                    </Link>
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold tracking-wide text-[#dce4f5]">
                            {decodedTicker}
                        </span>
                        <span className="text-[9px] font-mono tracking-widest text-[#5a6480] border border-white/[0.08] rounded px-1.5 py-0.5">
                            {exchange}
                        </span>
                    </div>
                </div>

                {/* Right: Price + Change + Timestamp */}
                <div className="flex items-center gap-4">
                    {price && (
                        <div className="flex items-center gap-2">
                            <span className="font-dm-mono text-sm font-medium text-[#dce4f5]">
                                ₹{price.current_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                            <span className={`font-dm-mono text-xs ${changeColor}`}>
                                {isPositive ? '+' : ''}{price.change_pct.toFixed(2)}% {arrow}
                            </span>
                        </div>
                    )}
                    {timestamp && (
                        <>
                            <div className="w-px h-4 bg-white/[0.08]" />
                            <span className="text-[10px] font-mono text-[#5a6480]">
                                {timestamp}
                            </span>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
