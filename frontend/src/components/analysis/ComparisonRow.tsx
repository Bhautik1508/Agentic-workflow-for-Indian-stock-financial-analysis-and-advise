'use client';

import type { AgentReport, RelativeContext } from '@/hooks/useAnalysis';
import { pct } from '@/lib/format';

interface ComparisonRowProps {
    agents: Record<string, AgentReport | undefined>;
    /** Index- and sector-relative performance. Optional so the component still
     *  renders for a cached run that predates it. */
    relative?: RelativeContext | null;
}

interface MetricCard {
    label: string;
    value: string;
    direction: 'up' | 'down' | 'flat';
    note?: string;
}

/** Walk available agent reports and pull comparable metrics into a small tile row. */
export function ComparisonRow({ agents, relative }: ComparisonRowProps) {
    const cards: MetricCard[] = [];

    // Relative performance leads: "down 8%" is not a verdict input, "down 8%
    // while the sector is down 15%" is. Shown first because it is the question
    // a reader asks before any ratio.
    const vsIndex = relative?.vs_benchmark?.['1Y'];
    if (vsIndex?.excess_pct != null) {
        const ahead = vsIndex.excess_pct > 0;
        cards.push({
            label: `vs ${relative?.benchmark_index?.symbol ?? 'NIFTY 50'} (1Y)`,
            value: `${ahead ? '+' : ''}${vsIndex.excess_pct.toFixed(1)}%`,
            direction: ahead ? 'up' : 'down',
            note: ahead ? 'Outperforming the index' : 'Lagging the index',
        });
    }

    const vsSector = relative?.vs_sector?.['1Y'];
    if (vsSector?.excess_pct != null && relative?.sector_index_symbol) {
        const ahead = vsSector.excess_pct > 0;
        cards.push({
            label: `vs ${relative.sector_index_symbol} (1Y)`,
            value: `${ahead ? '+' : ''}${vsSector.excess_pct.toFixed(1)}%`,
            direction: ahead ? 'up' : 'down',
            note: ahead ? 'Ahead of its sector' : 'Behind its own sector',
        });
    }

    if (relative?.alpha_1y_pct != null) {
        cards.push({
            label: 'CAPM alpha (1Y)',
            value: `${relative.alpha_1y_pct > 0 ? '+' : ''}${relative.alpha_1y_pct.toFixed(1)}%`,
            direction: relative.alpha_1y_pct > 0 ? 'up' : 'down',
            note: 'Return beyond what its beta implies',
        });
    }

    const regime = relative?.volatility_regime;
    if (regime?.india_vix != null) {
        cards.push({
            label: 'India VIX',
            value: `${regime.india_vix} · ${regime.regime}`,
            direction: regime.regime === 'calm' || regime.regime === 'normal' ? 'flat' : 'down',
            note: 'Market volatility regime',
        });
    }

    // 1. P/E vs sector (from Financial Analyst data)
    const fin = agents['financial_node'];
    const finData = fin?.data as Record<string, unknown> | undefined;
    const peVsSector = typeof finData?.['pe_premium_discount_pct'] === 'number'
        ? (finData['pe_premium_discount_pct'] as number)
        : null;
    if (peVsSector !== null) {
        const isPremium = peVsSector > 0;
        cards.push({
            label: 'vs Sector P/E',
            value: pct(Math.abs(peVsSector), { fractionDigits: 1 }) + (isPremium ? ' premium' : ' discount'),
            direction: isPremium ? 'down' : 'up',
            note: 'Lower is cheaper',
        });
    }

    // 2. Beta (from Risk Analyst)
    const risk = agents['risk_node'];
    const riskData = risk?.data as Record<string, unknown> | undefined;
    const betaCategory = typeof riskData?.['beta_category'] === 'string'
        ? (riskData['beta_category'] as string).replace('_', ' ')
        : null;
    if (betaCategory) {
        cards.push({
            label: 'Beta profile',
            value: betaCategory,
            direction: 'flat',
        });
    }

    // 3. Trend (from Technical Analyst)
    const tech = agents['technical_node'];
    const techData = tech?.data as Record<string, unknown> | undefined;
    const trend = typeof techData?.['trend'] === 'string'
        ? (techData['trend'] as string).replace(/_/g, ' ')
        : null;
    if (trend) {
        cards.push({
            label: 'Trend',
            value: trend,
            direction: trend.toLowerCase().includes('up') ? 'up'
                     : trend.toLowerCase().includes('down') ? 'down'
                     : 'flat',
        });
    }

    // 4. Macro environment (from Macro Analyst)
    const macro = agents['macro_governance_node'];
    const macroData = macro?.data as Record<string, unknown> | undefined;
    const macroEnv = typeof macroData?.['macro_environment'] === 'string'
        ? (macroData['macro_environment'] as string).replace(/_/g, ' ')
        : null;
    if (macroEnv) {
        cards.push({
            label: 'Macro setup',
            value: macroEnv,
            direction: macroEnv.toLowerCase().includes('favor') || macroEnv.toLowerCase().includes('positive') ? 'up'
                     : macroEnv.toLowerCase().includes('head') || macroEnv.toLowerCase().includes('negative') ? 'down'
                     : 'flat',
        });
    }

    if (cards.length === 0) return null;

    return (
        <section className="mt-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {cards.map((c, i) => {
                    const arrow = c.direction === 'up' ? '↑' : c.direction === 'down' ? '↓' : '→';
                    const tone = c.direction === 'up' ? 'text-[#15803D]'
                              : c.direction === 'down' ? 'text-[#B91C1C]'
                              : 'text-[#4A4D55]';
                    return (
                        <div key={i} className="card-paper px-4 py-3">
                            <p className="heading-eyebrow text-[10px] mb-1.5">{c.label}</p>
                            <p className={`text-[15px] font-medium capitalize ${tone}`}>
                                <span className="mr-1.5 opacity-70">{arrow}</span>{c.value}
                            </p>
                            {c.note && <p className="text-micro text-[#B6B8B8] mt-0.5">{c.note}</p>}
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
