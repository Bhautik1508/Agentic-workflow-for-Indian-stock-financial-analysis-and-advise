'use client';

import { useState, useEffect, useCallback } from 'react';
import {
    ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
    CartesianGrid,
} from 'recharts';
import { Loader2 } from 'lucide-react';

interface PriceRecord {
    date: string;
    open: number | null;
    high: number | null;
    low: number | null;
    close: number | null;
    volume: number;
    sma20: number | null;
    sma50: number | null;
}

interface StockChartProps {
    ticker: string;
}

const PERIODS = [
    { label: '1M', value: '1mo' },
    { label: '3M', value: '3mo' },
    { label: '6M', value: '6mo' },
    { label: '1Y', value: '1y' },
];

function formatPrice(val: number) {
    return `₹${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatVolume(val: number) {
    if (val >= 10_000_000) return `${(val / 10_000_000).toFixed(1)}Cr`;
    if (val >= 100_000) return `${(val / 100_000).toFixed(1)}L`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(0)}K`;
    return val.toString();
}

/* Custom candlestick shape */
function CandlestickBar(props: Record<string, unknown>) {
    const { x, y, width, height, payload } = props as {
        x: number; y: number; width: number; height: number;
        payload: PriceRecord;
    };

    if (!payload.open || !payload.close || !payload.high || !payload.low) return null;

    const isUp = payload.close >= payload.open;
    const color = isUp ? '#00ff9f' : '#ff4060';

    // Scale factors — we need the yAxis domain to compute pixel positions
    // Recharts passes the bar's y and height based on the "volume" dataKey
    // Since we're rendering a custom shape, we need to work within the chart coordinates
    // We'll use the bar's basic position and just render a colored bar
    const barWidth = Math.max(width * 0.6, 2);
    const barX = x + (width - barWidth) / 2;

    return (
        <g>
            {/* Candle body */}
            <rect
                x={barX}
                y={y}
                width={barWidth}
                height={Math.max(height, 1)}
                fill={color}
                opacity={0.9}
                rx={1}
            />
        </g>
    );
}

/* Custom tooltip */
function ChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: PriceRecord }> }) {
    if (!active || !payload || !payload[0]) return null;
    const d = payload[0].payload;

    return (
        <div className="bg-surface border border-border rounded-lg p-3 shadow-xl text-xs min-w-[160px]">
            <div className="font-mono text-text-muted mb-2">{d.date}</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <span className="text-text-dim">Open</span>
                <span className="text-foreground font-mono-num text-right">{d.open ? formatPrice(d.open) : '—'}</span>
                <span className="text-text-dim">High</span>
                <span className="text-foreground font-mono-num text-right">{d.high ? formatPrice(d.high) : '—'}</span>
                <span className="text-text-dim">Low</span>
                <span className="text-foreground font-mono-num text-right">{d.low ? formatPrice(d.low) : '—'}</span>
                <span className="text-text-dim">Close</span>
                <span className="text-foreground font-mono-num text-right">{d.close ? formatPrice(d.close) : '—'}</span>
                <span className="text-text-dim">Volume</span>
                <span className="text-foreground font-mono-num text-right">{formatVolume(d.volume)}</span>
            </div>
            <div className="border-t border-border/50 mt-2 pt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                <span className="text-[#4080ff]">SMA20</span>
                <span className="font-mono-num text-right text-[#4080ff]">{d.sma20 ? formatPrice(d.sma20) : '—'}</span>
                <span className="text-[#ff9f00]">SMA50</span>
                <span className="font-mono-num text-right text-[#ff9f00]">{d.sma50 ? formatPrice(d.sma50) : '—'}</span>
            </div>
        </div>
    );
}

export function StockChart({ ticker }: StockChartProps) {
    const [period, setPeriod] = useState('1y');
    const [data, setData] = useState<PriceRecord[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const fetchData = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const res = await fetch(`http://localhost:8000/api/price-history/${ticker}?period=${period}`);
            if (!res.ok) throw new Error('Failed to fetch price data');
            const json = await res.json();
            setData(json.data || []);
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Failed to load chart data');
            setData([]);
        } finally {
            setLoading(false);
        }
    }, [ticker, period]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    return (
        <div className="rounded-2xl border border-border/50 bg-surface/30 p-4">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-[10px] font-mono uppercase tracking-[0.2em] text-text-dim">
                    Price Chart
                </h3>
                <div className="flex gap-1">
                    {PERIODS.map((p) => (
                        <button
                            key={p.value}
                            onClick={() => setPeriod(p.value)}
                            className={`px-2.5 py-1 text-[10px] font-mono rounded-md transition-all cursor-pointer ${period === p.value
                                    ? 'bg-primary/15 text-primary border border-primary/25'
                                    : 'text-text-dim hover:text-text-muted border border-transparent'
                                }`}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Chart */}
            {loading ? (
                <div className="flex items-center justify-center h-[280px]">
                    <Loader2 size={20} className="animate-spin text-primary/40" />
                </div>
            ) : error ? (
                <div className="flex items-center justify-center h-[280px] text-xs text-text-dim">
                    {error}
                </div>
            ) : (
                <div className="h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                            <CartesianGrid stroke="rgba(26,37,64,0.5)" strokeDasharray="3 3" />
                            <XAxis
                                dataKey="date"
                                tick={{ fill: '#3a5070', fontSize: 9, fontFamily: 'var(--font-mono)' }}
                                axisLine={{ stroke: '#1a2540' }}
                                tickLine={false}
                                tickFormatter={(val: string) => {
                                    const d = new Date(val);
                                    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
                                }}
                                interval="preserveStartEnd"
                                minTickGap={40}
                            />
                            <YAxis
                                yAxisId="price"
                                orientation="right"
                                tick={{ fill: '#3a5070', fontSize: 9, fontFamily: 'var(--font-mono)' }}
                                axisLine={false}
                                tickLine={false}
                                domain={['auto', 'auto']}
                                tickFormatter={(val: number) => `₹${val}`}
                            />
                            <YAxis
                                yAxisId="volume"
                                orientation="left"
                                tick={false}
                                axisLine={false}
                                tickLine={false}
                                domain={[0, (max: number) => max * 5]}
                            />

                            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                            <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'rgba(0,212,255,0.15)' }} />

                            {/* Volume bars */}
                            <Bar
                                yAxisId="volume"
                                dataKey="volume"
                                barSize={3}
                                opacity={0.3}
                            >
                                {data.map((entry, i) => (
                                    <Cell
                                        key={i}
                                        fill={entry.close && entry.open && entry.close >= entry.open ? '#00ff9f' : '#ff4060'}
                                    />
                                ))}
                            </Bar>

                            {/* Price "candles" rendered as close-value bars with custom shape */}
                            <Bar
                                yAxisId="price"
                                dataKey="close"
                                barSize={4}
                                shape={<CandlestickBar />}
                            >
                                {data.map((entry, i) => (
                                    <Cell
                                        key={i}
                                        fill={entry.close && entry.open && entry.close >= entry.open ? '#00ff9f' : '#ff4060'}
                                    />
                                ))}
                            </Bar>

                            {/* SMA Lines */}
                            <Line
                                yAxisId="price"
                                type="monotone"
                                dataKey="sma20"
                                stroke="#4080ff"
                                strokeWidth={1.5}
                                strokeDasharray="4 2"
                                dot={false}
                                connectNulls={false}
                            />
                            <Line
                                yAxisId="price"
                                type="monotone"
                                dataKey="sma50"
                                stroke="#ff9f00"
                                strokeWidth={1.5}
                                strokeDasharray="4 2"
                                dot={false}
                                connectNulls={false}
                            />
                        </ComposedChart>
                    </ResponsiveContainer>

                    {/* Legend */}
                    <div className="flex items-center justify-center gap-4 mt-2 text-[9px] font-mono text-text-dim">
                        <span className="flex items-center gap-1">
                            <span className="w-3 h-[2px] bg-[#4080ff] inline-block" style={{ borderTop: '2px dashed #4080ff', background: 'transparent' }} /> SMA20
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="w-3 h-[2px] bg-[#ff9f00] inline-block" style={{ borderTop: '2px dashed #ff9f00', background: 'transparent' }} /> SMA50
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="w-2 h-2 bg-[#00ff9f] rounded-sm inline-block" /> Up
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="w-2 h-2 bg-[#ff4060] rounded-sm inline-block" /> Down
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
}
