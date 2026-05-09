'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, ArrowDown, Minus, ChevronsUp, ChevronsDown, AlertOctagon, Loader2, Database, Clock } from 'lucide-react';
import type { FinalDecision } from '@/hooks/useAnalysis';
import { inr, pct } from '@/lib/format';
import { topStrengths, topRisks } from '@/lib/strengths';
import type { AgentReport } from '@/hooks/useAnalysis';

type Verdict = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL';

interface VerdictHeroProps {
    decision: FinalDecision | null;
    agents: Record<string, AgentReport | undefined>;
    status: string;
}

const VERDICT_CONFIG: Record<Verdict, {
    label: string;
    icon: typeof ArrowUp;
    fg: string;
    bg: string;
    border: string;
    dotBg: string;
}> = {
    STRONG_BUY: { label: 'Strong Buy', icon: ChevronsUp,   fg: 'text-[#166534]', bg: 'bg-[#DCFCE7]', border: 'border-[#86EFAC]', dotBg: 'bg-[#15803D]' },
    BUY:        { label: 'Buy',        icon: ArrowUp,      fg: 'text-[#15803D]', bg: 'bg-[#ECFDF3]', border: 'border-[#A7E3BF]', dotBg: 'bg-[#15803D]' },
    HOLD:       { label: 'Hold',       icon: Minus,        fg: 'text-[#A16207]', bg: 'bg-[#FEF7E0]', border: 'border-[#E8C56A]', dotBg: 'bg-[#A16207]' },
    SELL:       { label: 'Sell',       icon: ArrowDown,    fg: 'text-[#B91C1C]', bg: 'bg-[#FEE7E7]', border: 'border-[#F0A0A0]', dotBg: 'bg-[#B91C1C]' },
    STRONG_SELL:{ label: 'Strong Sell',icon: ChevronsDown, fg: 'text-[#991B1B]', bg: 'bg-[#FCD7D7]', border: 'border-[#E8898E]', dotBg: 'bg-[#991B1B]' },
};

function HeroSkeleton({ status }: { status: string }) {
    const isError = status === 'error';
    return (
        <section className="card-paper px-6 py-8 md:px-10 md:py-10">
            <div className="flex items-center gap-3 mb-6">
                {isError ? (
                    <AlertOctagon size={18} className="text-[#B91C1C]" />
                ) : (
                    <Loader2 size={18} className="text-[#1E40AF] animate-spin" />
                )}
                <span className="heading-eyebrow">
                    {isError ? 'Analysis Failed' : 'Verdict in progress'}
                </span>
            </div>
            <div className="space-y-3">
                <div className="h-9 w-48 rounded skeleton-shimmer bg-[#F2F1EB]" />
                <div className="h-4 w-3/4 rounded skeleton-shimmer bg-[#F2F1EB]" />
                <div className="h-4 w-2/3 rounded skeleton-shimmer bg-[#F2F1EB]" />
            </div>
        </section>
    );
}

export function VerdictHero({ decision, agents, status }: VerdictHeroProps) {
    if (!decision) return <HeroSkeleton status={status} />;

    const cfg = VERDICT_CONFIG[decision.decision] ?? VERDICT_CONFIG.HOLD;
    const VerdictIcon = cfg.icon;

    const confidenceRaw = decision.confidence_score ?? 0;
    const confidenceNorm = confidenceRaw > 1 ? confidenceRaw / 100 : confidenceRaw;
    const confidencePct = Math.round(confidenceNorm * 100);

    const target = decision.target_price ?? null;
    const stop = decision.stop_loss ?? null;
    const upside = decision.grounded_targets?.upside_pct ?? null;
    const downside = decision.grounded_targets?.downside_pct ?? null;
    const positionSize = decision.grounded_targets?.position_size_modifier ?? null;
    const horizonRaw = (decision as { time_horizon?: string }).time_horizon;
    const horizon = horizonRaw === 'short_term' ? 'short term'
                  : horizonRaw === 'medium_term' ? '6 months'
                  : horizonRaw === 'long_term' ? '12 months'
                  : null;

    const strengths = topStrengths(agents, 3);
    const risks = topRisks(agents, 3);

    return (
        <AnimatePresence>
            <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: 'easeOut' }}
                className="card-paper px-6 py-8 md:px-10 md:py-10"
            >
                {/* ── Veto banner ── */}
                {decision.veto?.triggered && (
                    <div className="mb-5 -mx-6 md:-mx-10 px-6 md:px-10 py-3 border-y border-[#F0A0A0] bg-[#FEE7E7] flex items-start gap-2">
                        <AlertOctagon size={15} className="text-[#B91C1C] mt-0.5 shrink-0" />
                        <p className="text-small text-[#7A1F1F]">
                            <span className="font-semibold">Veto fired — </span>
                            {decision.veto.reasons.slice(0, 2).join(' · ')}
                        </p>
                    </div>
                )}

                {/* ── Verdict line: dot + label + price target + horizon ── */}
                <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 mb-2">
                    <div className="flex items-center gap-3">
                        <span className={`w-2 h-2 rounded-full ${cfg.dotBg}`} />
                        <h1 className={`heading-display ${cfg.fg} flex items-center gap-2`}>
                            <VerdictIcon size={28} className="opacity-80" strokeWidth={2.5} />
                            {cfg.label}
                        </h1>
                    </div>
                    {target && upside != null && (
                        <p className="font-serif text-[22px] text-[#1A1B1E]">
                            <span className="text-[#7A7F88] font-sans text-[14px] mr-2">to</span>
                            <span className="font-tnum">{inr(target)}</span>
                            <span className="ml-2 text-[#15803D] font-sans text-[14px] font-medium font-tnum">{pct(upside, { signed: true })}</span>
                            {horizon && <span className="text-[#7A7F88] font-sans text-[14px] ml-2">in {horizon}</span>}
                        </p>
                    )}
                </div>

                {/* ── Conviction + Stop + Position size + Profile + Quality chips ── */}
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-small text-[#4A4D55] mb-6">
                    <span className="font-tnum"><span className="text-[#7A7F88]">Conviction</span> {confidencePct}%</span>
                    {stop != null && (
                        <span className="font-tnum">
                            <span className="text-[#7A7F88]">Stop</span> {inr(stop)}
                            {downside != null && <span className="text-[#B91C1C] ml-1">−{downside.toFixed(1)}%</span>}
                        </span>
                    )}
                    {positionSize != null && (
                        <span className="font-tnum"><span className="text-[#7A7F88]">Size</span> {positionSize.toFixed(2)}×</span>
                    )}
                    {decision.risk_profile && (
                        <span className="px-1.5 py-0.5 rounded border border-[#E5E3DB] bg-[#F2F1EB] text-[11px] font-mono uppercase tracking-wider text-[#4A4D55]">
                            {decision.risk_profile}
                        </span>
                    )}
                    {decision.data_quality && (
                        <DataQualityChip overall={decision.data_quality.overall_completeness} />
                    )}
                    {decision.stale_sources?.slice(0, 2).map((s, i) => (
                        <span key={i} className="inline-flex items-center gap-1 text-[11px] text-[#A16207]">
                            <Clock size={11} /> {s}
                        </span>
                    ))}
                </div>

                {/* ── Thesis (editorial lede) ── */}
                {decision.investment_thesis && (
                    <p className="text-lede mb-7 max-w-3xl">
                        &ldquo;{decision.investment_thesis}&rdquo;
                    </p>
                )}

                {/* ── Strengths + Risks columns ── */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-6 pt-6 border-t border-[#E5E3DB]">
                    <div>
                        <h3 className="heading-eyebrow mb-3">Strengths</h3>
                        {strengths.length === 0 ? (
                            <p className="text-small text-[#7A7F88]">No pillar above 6.0 yet.</p>
                        ) : (
                            <ul className="space-y-2">
                                {strengths.map((h, i) => (
                                    <li key={i} className="flex gap-3">
                                        <span className="font-tnum text-[#15803D] font-medium w-12 shrink-0">{h.score.toFixed(1)}</span>
                                        <div className="min-w-0">
                                            <span className="text-small text-[#1A1B1E] font-medium">{h.pillar}</span>
                                            <span className="text-small text-[#4A4D55]"> — {h.text}</span>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                    <div>
                        <h3 className="heading-eyebrow mb-3">Risks</h3>
                        {risks.length === 0 && (decision.key_risks?.length ?? 0) === 0 ? (
                            <p className="text-small text-[#7A7F88]">No flagged risks.</p>
                        ) : (
                            <ul className="space-y-2">
                                {risks.length > 0
                                    ? risks.map((h, i) => (
                                        <li key={i} className="flex gap-3">
                                            <span className="font-tnum text-[#B91C1C] font-medium w-12 shrink-0">{h.score.toFixed(1)}</span>
                                            <div className="min-w-0">
                                                <span className="text-small text-[#1A1B1E] font-medium">{h.pillar}</span>
                                                <span className="text-small text-[#4A4D55]"> — {h.text}</span>
                                            </div>
                                        </li>
                                    ))
                                    : decision.key_risks?.slice(0, 3).map((r, i) => (
                                        <li key={i} className="flex gap-3">
                                            <span className="text-[#B91C1C] w-3 shrink-0">·</span>
                                            <span className="text-small text-[#4A4D55]">{r}</span>
                                        </li>
                                    ))
                                }
                            </ul>
                        )}
                    </div>
                </div>

                {/* ── Dissent (small) ── */}
                {decision.dissent_summary && (
                    <div className="mt-6 pt-5 border-t border-[#E5E3DB]">
                        <h4 className="heading-eyebrow mb-2">Dissent</h4>
                        <p className="text-small text-[#4A4D55] italic">{decision.dissent_summary}</p>
                    </div>
                )}
            </motion.section>
        </AnimatePresence>
    );
}

function DataQualityChip({ overall }: { overall: number }) {
    const p = Math.round((overall ?? 0) * 100);
    const tone = p >= 85 ? 'text-[#15803D]'
              : p >= 70 ? 'text-[#A16207]'
              : 'text-[#B91C1C]';
    return (
        <span className={`inline-flex items-center gap-1 text-[11px] ${tone}`}>
            <Database size={11} /> Data {p}%
        </span>
    );
}
