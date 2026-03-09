'use client';

import { useEffect, useState } from 'react';
import {
    ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';

interface PriceRecord {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    sma20: number | null;
    sma50: number | null;
}

interface PriceChartProps {
    ticker: string;
}

const PERIODS = [
    { label: '1M', value: '1mo' },
    { label: '3M', value: '3mo' },
    { label: '6M', value: '6mo' },
    { label: '1Y', value: '1y' },
];

// Muted chart colors
const COLORS = {
    up: '#3a7a5e',
    down: '#7a3a40',
    volUp: 'rgba(58, 122, 94, 0.35)',
    volDown: 'rgba(122, 58, 64, 0.35)',
    sma20: 'rgba(91, 138, 240, 0.5)',
    sma50: 'rgba(180, 140, 80, 0.5)',
    grid: 'rgba(255, 255, 255, 0.03)',
    axisText: '#343a4f',
    crosshair: 'rgba(255, 255, 255, 0.1)',
};

function formatDate(dateStr: string) {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: PriceRecord }> }) {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
        <div className="bg-[#111627] border border-white/[0.06] rounded-lg px-3 py-2 shadow-xl">
            <p className="text-[10px] text-[#5a6480] mb-1.5 font-mono">{d.date}</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] font-mono">
                <span className="text-[#5a6480]">O</span>
                <span className="text-[#dce4f5] text-right">₹{d.open?.toFixed(2)}</span>
                <span className="text-[#5a6480]">H</span>
                <span className="text-[#dce4f5] text-right">₹{d.high?.toFixed(2)}</span>
                <span className="text-[#5a6480]">L</span>
                <span className="text-[#dce4f5] text-right">₹{d.low?.toFixed(2)}</span>
                <span className="text-[#5a6480]">C</span>
                <span className="text-[#dce4f5] text-right">₹{d.close?.toFixed(2)}</span>
                <span className="text-[#5a6480]">Vol</span>
                <span className="text-[#dce4f5] text-right">{(d.volume / 1e6).toFixed(1)}M</span>
            </div>
        </div>
    );
}

export function PriceChart({ ticker }: PriceChartProps) {
    const [data, setData] = useState<PriceRecord[]>([]);
    const [period, setPeriod] = useState('1y');
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        setLoading(true);
        fetch(`http://127.0.0.1:8000/api/price-history/${ticker}?period=${period}`)
            .then((r) => r.json())
            .then((json) => {
                setData(json.data || []);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, [ticker, period]);

    // Price range for Y axis
    const prices = data.map((d) => [d.low, d.high]).flat().filter(Boolean);
    const minPrice = prices.length ? Math.floor(Math.min(...prices) * 0.98) : 0;
    const maxPrice = prices.length ? Math.ceil(Math.max(...prices) * 1.02) : 100;

    // Volume max for secondary axis
    const maxVol = data.length ? Math.max(...data.map((d) => d.volume || 0)) : 1;

    return (
        <div className="bg-[#0c0f19] rounded-xl border border-white/[0.06] overflow-hidden">
            {/* Period tabs */}
            <div className="flex items-center justify-between px-4 pt-3 pb-1">
                <div className="flex items-center gap-4">
                    {PERIODS.map((p) => (
                        <button
                            key={p.value}
                            onClick={() => setPeriod(p.value)}
                            className={`text-[11px] font-mono pb-1 border-b transition-all cursor-pointer ${period === p.value
                                    ? 'text-[#5b8af0] border-[#5b8af0]'
                                    : 'text-[#343a4f] border-transparent hover:text-[#5a6480]'
                                }`}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
                {/* Legend */}
                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1">
                        <div className="w-4 h-px" style={{ background: COLORS.sma20, borderTop: '1px dashed rgba(91,138,240,0.5)' }} />
                        <span className="text-[9px] font-mono text-[#343a4f]">SMA20</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <div className="w-4 h-px" style={{ background: COLORS.sma50, borderTop: '1px dashed rgba(180,140,80,0.5)' }} />
                        <span className="text-[9px] font-mono text-[#343a4f]">SMA50</span>
                    </div>
                </div>
            </div>

            {/* Chart */}
            <div className="h-[40vh] min-h-[280px] px-2">
                {loading ? (
                    <div className="w-full h-full flex items-center justify-center">
                        <div className="flex gap-1">
                            <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-[#5b8af0]" />
                            <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-[#5b8af0]" />
                            <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-[#5b8af0]" />
                        </div>
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                            {/* Grid — horizontal only */}
                            <XAxis
                                dataKey="date"
                                tickFormatter={formatDate}
                                tick={{ fill: COLORS.axisText, fontSize: 10 }}
                                axisLine={{ stroke: COLORS.grid }}
                                tickLine={false}
                                interval="preserveStartEnd"
                                minTickGap={60}
                            />
                            <YAxis
                                domain={[minPrice, maxPrice]}
                                orientation="right"
                                tick={{ fill: COLORS.axisText, fontSize: 10 }}
                                axisLine={false}
                                tickLine={false}
                                tickFormatter={(v: number) => `₹${v}`}
                                width={55}
                            />
                            {/* Volume bars — bottom 15% overlaid */}
                            <Bar dataKey="volume" yAxisId="vol" barSize={4} isAnimationActive={false}>
                                {data.map((d, i) => (
                                    <Cell
                                        key={i}
                                        fill={d.close >= d.open ? COLORS.volUp : COLORS.volDown}
                                    />
                                ))}
                            </Bar>
                            <YAxis
                                yAxisId="vol"
                                domain={[0, maxVol * 6]}
                                hide
                            />

                            {/* Price bars (candlestick-style) */}
                            <Bar dataKey="close" barSize={6} isAnimationActive={false}>
                                {data.map((d, i) => (
                                    <Cell
                                        key={i}
                                        fill={d.close >= d.open ? COLORS.up : COLORS.down}
                                    />
                                ))}
                            </Bar>

                            {/* SMA lines */}
                            <Line
                                dataKey="sma20"
                                stroke={COLORS.sma20}
                                strokeWidth={1}
                                strokeDasharray="4 4"
                                dot={false}
                                isAnimationActive={false}
                                connectNulls
                            />
                            <Line
                                dataKey="sma50"
                                stroke={COLORS.sma50}
                                strokeWidth={1}
                                strokeDasharray="4 4"
                                dot={false}
                                isAnimationActive={false}
                                connectNulls
                            />

                            <Tooltip
                                content={<CustomTooltip />}
                                cursor={{ stroke: COLORS.crosshair, strokeWidth: 1 }}
                            />
                        </ComposedChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
}
