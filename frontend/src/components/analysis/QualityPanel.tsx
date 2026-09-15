'use client';

import type { ExtendedRisk, QualityMetrics } from '@/hooks/useAnalysis';

interface QualityPanelProps {
    quality: QualityMetrics | null;
    extendedRisk: ExtendedRisk | null;
}

function Stat({ label, value, note, tone }: {
    label: string; value: string; note?: string; tone?: 'good' | 'bad' | 'neutral';
}) {
    const colour =
        tone === 'good' ? 'text-[#15803D]' :
        tone === 'bad' ? 'text-[#B91C1C]' :
        'text-[#1A1B1E]';
    return (
        <div className="min-w-0">
            <p className="heading-eyebrow text-[10px] mb-1">{label}</p>
            <p className={`text-[15px] font-medium tabular-nums ${colour}`}>{value}</p>
            {note && <p className="text-micro text-[#B6B8B8] mt-0.5 leading-snug">{note}</p>}
        </div>
    );
}

/**
 * Accounting quality and the risk measures a Sharpe ratio cannot express.
 *
 * These are computed in Python, not inferred by the model — so they are stated
 * as facts rather than as the analysts' opinion, and a missing value is shown
 * as "n/a" rather than hidden, because an absent number and a bad one are
 * different things.
 */
export function QualityPanel({ quality, extendedRisk }: QualityPanelProps) {
    const p = quality?.piotroski;
    const d = quality?.dupont;
    const c = quality?.cash_quality;
    const rb = extendedRisk?.rolling_beta;
    const liq = extendedRisk?.liquidity;

    const hasQuality = p?.score != null || d?.roe != null || c?.cash_conversion_3y_avg != null;
    const hasRisk = extendedRisk?.sortino_ratio != null || rb?.beta_1y != null || liq?.tier;
    if (!hasQuality && !hasRisk) return null;

    return (
        <section className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {hasQuality && (
                <div className="card-paper px-5 py-4">
                    <p className="heading-eyebrow text-[10px] mb-3">Accounting quality</p>
                    <div className="grid grid-cols-2 gap-x-5 gap-y-4">
                        {p?.score != null && (
                            <Stat
                                label="Piotroski F-Score"
                                value={`${p.score}/${p.max_score}`}
                                note={p.interpretation}
                                tone={p.score / p.max_score >= 0.78 ? 'good'
                                    : p.score / p.max_score >= 0.5 ? 'neutral' : 'bad'}
                            />
                        )}
                        {d?.roe != null && (
                            <Stat
                                label="ROE driver"
                                value={d.driver ?? '—'}
                                note={`${(d.roe * 100).toFixed(1)}% = margin ${(d.net_margin! * 100).toFixed(1)}% × turnover ${d.asset_turnover}x × leverage ${d.equity_multiplier}x`}
                                tone={d.driver === 'leverage' ? 'bad' : 'good'}
                            />
                        )}
                        {c?.cash_conversion_3y_avg != null && (
                            <Stat
                                label="Cash conversion (3y)"
                                value={`${c.cash_conversion_3y_avg.toFixed(2)}x`}
                                note={c.flag ?? undefined}
                                tone={c.cash_conversion_3y_avg >= 0.9 ? 'good'
                                    : c.cash_conversion_3y_avg >= 0.7 ? 'neutral' : 'bad'}
                            />
                        )}
                        {c?.accruals_ratio != null && (
                            <Stat
                                label="Accruals ratio"
                                value={`${(c.accruals_ratio * 100).toFixed(1)}%`}
                                note="Profit not backed by cash — lower is better"
                                tone={c.accruals_ratio <= 0 ? 'good' : 'bad'}
                            />
                        )}
                    </div>
                    {p?.unavailable?.length ? (
                        <p className="text-micro text-[#B6B8B8] mt-3">
                            Not evaluable from available statements: {p.unavailable.join(', ')}
                        </p>
                    ) : null}
                </div>
            )}

            {hasRisk && (
                <div className="card-paper px-5 py-4">
                    <p className="heading-eyebrow text-[10px] mb-3">Risk profile</p>
                    <div className="grid grid-cols-2 gap-x-5 gap-y-4">
                        {extendedRisk?.sortino_ratio != null && (
                            <Stat
                                label="Sortino"
                                value={extendedRisk.sortino_ratio.toFixed(2)}
                                note="Counts only downside volatility as risk"
                                tone={extendedRisk.sortino_ratio > 0 ? 'good' : 'bad'}
                            />
                        )}
                        {rb?.beta_1y != null && (
                            <Stat
                                label="Beta 1Y vs 2Y"
                                value={`${rb.beta_1y}${rb.beta_2y != null ? ` / ${rb.beta_2y}` : ''}`}
                                note={rb.trend === 'rising' ? 'Becoming more market-sensitive'
                                    : rb.trend === 'falling' ? 'Becoming less market-sensitive'
                                    : rb.trend === 'stable' ? 'Risk profile unchanged'
                                    : 'Not enough history to compare'}
                                tone={rb.trend === 'rising' ? 'bad' : 'neutral'}
                            />
                        )}
                        {extendedRisk?.week52_percentile != null && (
                            <Stat
                                label="52-week position"
                                value={`${extendedRisk.week52_percentile}th pctile`}
                                note="0 = at the low, 100 = at the high"
                                tone="neutral"
                            />
                        )}
                        {liq?.median_daily_value_cr != null && (
                            <Stat
                                label="Liquidity"
                                value={`₹${liq.median_daily_value_cr.toLocaleString('en-IN')} Cr/day`}
                                note={liq.thin ? 'Thin — cap position size regardless of conviction'
                                    : `${liq.tier} — no size constraint`}
                                tone={liq.thin ? 'bad' : 'good'}
                            />
                        )}
                    </div>
                    {extendedRisk?.calmar_ratio != null && (
                        <p className="text-micro text-[#B6B8B8] mt-3">
                            Calmar {extendedRisk.calmar_ratio.toFixed(2)} (1Y return ÷ max drawdown)
                            {extendedRisk.vwap_relative_pct != null && (
                                <> · {Math.abs(extendedRisk.vwap_relative_pct)}%{' '}
                                {extendedRisk.vwap_relative_pct >= 0 ? 'above' : 'below'} its 20-session VWAP</>
                            )}
                        </p>
                    )}
                </div>
            )}
        </section>
    );
}
