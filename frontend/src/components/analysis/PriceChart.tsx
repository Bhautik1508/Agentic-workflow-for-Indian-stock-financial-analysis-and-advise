'use client';

import { useEffect, useState } from 'react';
import {
    ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
    ReferenceLine,
} from 'recharts';
import { getApiUrl } from '@/config';
import { inr } from '@/lib/format';

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
    targetPrice?: number | null;
    stopLoss?: number | null;
}

const PERIODS = [
    { label: '1M', value: '1mo' },
    { label: '3M', value: '3mo' },
    { label: '6M', value: '6mo' },
    { label: '1Y', value: '1y' },
];

// Editorial light-theme palette
const COLORS = {
    up:        '#15803D',
    down:      '#B91C1C',
    volUp:     'rgba(21, 128, 61, 0.18)',
    volDown:   'rgba(185, 28, 28, 0.18)',
    sma20:     'rgba(30, 64, 175, 0.55)',
    sma50:     'rgba(161, 98, 7, 0.55)',
    grid:      'rgba(26, 27, 30, 0.06)',
    axisText:  '#7A7F88',
    crosshair: 'rgba(26, 27, 30, 0.18)',
    target:    '#166534',
    stop:      '#991B1B',
};

function formatDate(dateStr: string) {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: PriceRecord }> }) {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
        <div className="bg-white border border-rule rounded-md px-3 py-2 shadow-md">
            <p className="text-[11px] text-ink-3 mb-1.5 font-mono">{d.date}</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] font-mono">
                <span className="text-ink-3">O</span>
                <span className="text-ink text-right tabular">₹{d.open?.toFixed(2)}</span>
                <span className="text-ink-3">H</span>
                <span className="text-ink text-right tabular">₹{d.high?.toFixed(2)}</span>
                <span className="text-ink-3">L</span>
                <span className="text-ink text-right tabular">₹{d.low?.toFixed(2)}</span>
                <span className="text-ink-3">C</span>
                <span className="text-ink text-right tabular">₹{d.close?.toFixed(2)}</span>
                <span className="text-ink-3">Vol</span>
                <span className="text-ink text-right tabular">{(d.volume / 1e6).toFixed(1)}M</span>
            </div>
        </div>
    );
}

export function PriceChart({ ticker, targetPrice = null, stopLoss = null }: PriceChartProps) {
    const [data, setData] = useState<PriceRecord[]>([]);
    const [period, setPeriod] = useState('1y');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!ticker) return;
        let cancelled = false;
        setLoading(true);
        setError(null);
        const API_BASE_URL = getApiUrl();
        const url = `${API_BASE_URL}/api/price-history/${encodeURIComponent(ticker)}?period=${period}`;
        fetch(url)
            .then(async (r) => {
                const json = await r.json().catch(() => ({} as { detail?: string; data?: unknown }));
                if (cancelled) return;
                if (!r.ok) {
                    setError(json.detail ?? `Server returned ${r.status}`);
                    setData([]);
                } else {
                    const rows = Array.isArray(json.data) ? (json.data as PriceRecord[]) : [];
                    setData(rows);
                    if (rows.length === 0) setError('No price data returned for this period.');
                }
            })
            .catch((e) => {
                if (cancelled) return;
                setError((e as Error).message ?? 'Failed to load price history.');
                setData([]);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
    }, [ticker, period]);

    // Price range for Y axis — include target/stop so reference lines fit on screen
    const refLines = [targetPrice, stopLoss].filter(v => v !== null && v !== undefined) as number[];
    const prices = [...data.map((d) => [d.low, d.high]).flat().filter(Boolean), ...refLines];
    const minPrice = prices.length ? Math.floor(Math.min(...prices) * 0.97) : 0;
    const maxPrice = prices.length ? Math.ceil(Math.max(...prices) * 1.03) : 100;

    // Volume max for secondary axis
    const maxVol = data.length ? Math.max(...data.map((d) => d.volume || 0)) : 1;

    return (
        <div className="card-paper overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 pt-3 pb-2">
                <h3 className="heading-eyebrow">Price chart</h3>
                <div className="flex items-center gap-1 no-print">
                    {PERIODS.map((p) => (
                        <button
                            key={p.value}
                            onClick={() => setPeriod(p.value)}
                            className={`text-[11px] font-mono px-2 py-1 rounded transition-all cursor-pointer ${period === p.value
                                ? 'bg-ink text-white'
                                : 'text-ink-3 hover:text-ink hover:bg-paper-2'
                                }`}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-4 px-4 pb-2">
                <span className="inline-flex items-center gap-1 text-[10px] font-mono text-ink-3">
                    <span className="w-4 h-[2px]" style={{ background: COLORS.sma20 }} /> SMA20
                </span>
                <span className="inline-flex items-center gap-1 text-[10px] font-mono text-ink-3">
                    <span className="w-4 h-[2px]" style={{ background: COLORS.sma50 }} /> SMA50
                </span>
                {targetPrice && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-mono text-buy">
                        <span className="w-4 h-[1px] border-t border-dashed" style={{ borderColor: COLORS.target }} /> Target {inr(targetPrice)}
                    </span>
                )}
                {stopLoss && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-mono text-sell">
                        <span className="w-4 h-[1px] border-t border-dashed" style={{ borderColor: COLORS.stop }} /> Stop {inr(stopLoss)}
                    </span>
                )}
            </div>

            {/* Chart */}
            <div className="h-[42vh] min-h-[300px] px-2 pb-2">
                {loading ? (
                    <div className="w-full h-full flex items-center justify-center">
                        <div className="flex gap-1">
                            <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-accent" />
                            <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-accent" />
                            <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-accent" />
                        </div>
                    </div>
                ) : (error || data.length === 0) ? (
                    <div className="w-full h-full flex flex-col items-center justify-center text-center px-6">
                        <p className="text-small text-ink-3 mb-1">Price chart unavailable</p>
                        <p className="text-micro text-ink-4 max-w-sm">
                            {error ?? 'No data returned for the selected period.'}
                        </p>
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
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
                            <Bar dataKey="volume" yAxisId="vol" barSize={4} isAnimationActive={false}>
                                {data.map((d, i) => (
                                    <Cell key={i} fill={d.close >= d.open ? COLORS.volUp : COLORS.volDown} />
                                ))}
                            </Bar>
                            <YAxis yAxisId="vol" domain={[0, maxVol * 6]} hide />

                            <Bar dataKey="close" barSize={6} isAnimationActive={false}>
                                {data.map((d, i) => (
                                    <Cell key={i} fill={d.close >= d.open ? COLORS.up : COLORS.down} />
                                ))}
                            </Bar>

                            <Line
                                dataKey="sma20"
                                stroke={COLORS.sma20}
                                strokeWidth={1.25}
                                dot={false}
                                isAnimationActive={false}
                                connectNulls
                            />
                            <Line
                                dataKey="sma50"
                                stroke={COLORS.sma50}
                                strokeWidth={1.25}
                                dot={false}
                                isAnimationActive={false}
                                connectNulls
                            />

                            {/* Target & stop overlays.
                                Deliberately unlabelled. `position: 'right'` put the
                                text exactly where the right-oriented Y axis lives, so
                                it sat on top of the price ticks and was clipped by the
                                chart edge ("Target ₹2,71"). No fixed position is
                                collision-proof across arbitrary data — a label anywhere
                                inside the plot can land on a candle — and both values
                                are already named in the legend directly above, colour
                                matched to the line. */}
                            {targetPrice != null && (
                                <ReferenceLine
                                    y={targetPrice}
                                    stroke={COLORS.target}
                                    strokeDasharray="4 3"
                                    strokeWidth={1}
                                />
                            )}
                            {stopLoss != null && (
                                <ReferenceLine
                                    y={stopLoss}
                                    stroke={COLORS.stop}
                                    strokeDasharray="4 3"
                                    strokeWidth={1}
                                />
                            )}

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
