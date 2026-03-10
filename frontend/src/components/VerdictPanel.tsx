'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, ArrowDown, Minus, Loader2 } from 'lucide-react';

interface FinalDecision {
    decision: 'BUY' | 'HOLD' | 'SELL';
    confidence_score: number;
    investment_thesis: string;
    key_risks: string[];
    key_catalysts?: string[];
    target_price?: number;
    stop_loss?: number;
    agent_scores?: Record<string, number>;
}

interface VerdictPanelProps {
    decision: FinalDecision | null;
    status: string;
    agentScores?: Record<string, number>;
}

// Desaturated signal colors — border-only badge style
const DECISION_CONFIG = {
    BUY: {
        color: '#3d9970',
        border: 'border-[#3d9970]/40',
        bg: 'bg-[#3d9970]/8',
        icon: ArrowUp,
    },
    SELL: {
        color: '#c0444a',
        border: 'border-[#c0444a]/40',
        bg: 'bg-[#c0444a]/8',
        icon: ArrowDown,
    },
    HOLD: {
        color: '#8a7a40',
        border: 'border-[#8a7a40]/40',
        bg: 'bg-[#8a7a40]/8',
        icon: Minus,
    },
};

const AGENT_ORDER = [
    { key: 'financial_node', label: 'Financial' },
    { key: 'technical_node', label: 'Technical' },
    { key: 'sentiment_node', label: 'Sentiment' },
    { key: 'risk_node', label: 'Risk' },
    { key: 'macro_governance_node', label: 'Macro & Gov' },
];

function scoreBarColor(score: number): string {
    if (score >= 7) return 'rgba(61, 153, 112, 0.70)';
    if (score >= 5) return 'rgba(138, 122, 64, 0.70)';
    return 'rgba(192, 68, 74, 0.70)';
}

export function VerdictPanel({ decision, status, agentScores }: VerdictPanelProps) {
    // Loading state
    if (!decision) {
        return (
            <div className="bg-[#0c0f19] border border-white/[0.06] rounded-xl p-6 flex flex-col items-center justify-center min-h-[200px]">
                {status === 'error' ? (
                    <p className="text-[11px] text-[#c0444a]/60 font-mono">Analysis failed</p>
                ) : (
                    <>
                        <Loader2 size={20} className="text-[#5b8af0]/40 animate-spin mb-3" />
                        <p className="text-[11px] text-[#7888a5] font-mono">Awaiting verdict</p>
                        <div className="flex gap-1 mt-2">
                            <span className="pulse-dot w-1 h-1 rounded-full bg-[#5b8af0]/40" />
                            <span className="pulse-dot w-1 h-1 rounded-full bg-[#5b8af0]/40" />
                            <span className="pulse-dot w-1 h-1 rounded-full bg-[#5b8af0]/40" />
                        </div>
                    </>
                )}
            </div>
        );
    }

    const config = DECISION_CONFIG[decision.decision] || DECISION_CONFIG.HOLD;
    const DecisionIcon = config.icon;
    const confidencePct = Math.round(decision.confidence_score * 10);

    // Merge agent_scores from decision or from props
    const scores = decision.agent_scores || agentScores || {};

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease: 'easeOut' }}
                className={`bg-[#0c0f19] border ${config.border} rounded-xl p-5 overflow-hidden`}
            >
                {/* Decision Badge — border-only, monospace */}
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <DecisionIcon size={18} style={{ color: config.color }} />
                        <span
                            className="text-2xl font-bold font-mono tracking-tight"
                            style={{ color: config.color }}
                        >
                            {decision.decision}
                        </span>
                    </div>
                    {/* Confidence: horizontal bar + number */}
                    <div className="flex items-center gap-2">
                        <div className="w-20 h-[3px] rounded-full bg-white/[0.04] overflow-hidden">
                            <motion.div
                                className="h-full rounded-full"
                                style={{ backgroundColor: config.color }}
                                initial={{ width: 0 }}
                                animate={{ width: `${confidencePct}%` }}
                                transition={{ duration: 0.8, ease: 'easeOut' }}
                            />
                        </div>
                        <span className="font-dm-mono text-xs" style={{ color: config.color }}>
                            {confidencePct}%
                        </span>
                    </div>
                </div>

                {/* Thesis — accent left border */}
                {decision.investment_thesis && (
                    <div className="border-l-2 border-[#5b8af0]/30 pl-3 mb-4">
                        <p className="text-[11px] text-[#a0b0c8] leading-relaxed">
                            {decision.investment_thesis}
                        </p>
                    </div>
                )}

                {/* Price Targets */}
                {(decision.target_price || decision.stop_loss) && (
                    <div className="flex gap-4 mb-4">
                        {decision.target_price && (
                            <div>
                                <span className="text-[9px] font-mono text-[#4a5270] uppercase">Target</span>
                                <p className="font-dm-mono text-sm text-[#dce4f5]">
                                    ₹{decision.target_price.toLocaleString('en-IN')}
                                </p>
                            </div>
                        )}
                        {decision.stop_loss && (
                            <div>
                                <span className="text-[9px] font-mono text-[#4a5270] uppercase">Stop Loss</span>
                                <p className="font-dm-mono text-sm text-[#c0444a]">
                                    ₹{decision.stop_loss.toLocaleString('en-IN')}
                                </p>
                            </div>
                        )}
                    </div>
                )}

                {/* Catalysts + Risks — em-dash lists, no icons */}
                <div className="grid grid-cols-2 gap-3 mb-4">
                    {decision.key_catalysts && decision.key_catalysts.length > 0 && (
                        <div>
                            <h4 className="text-[9px] font-mono tracking-widest text-[#4a5270] uppercase mb-1.5">
                                Catalysts
                            </h4>
                            <div className="space-y-1">
                                {decision.key_catalysts.slice(0, 3).map((c, i) => (
                                    <p key={i} className="text-[10px] text-[#a0b0c8] leading-snug">
                                        <span className="text-[#3d9970]">— </span>{c}
                                    </p>
                                ))}
                            </div>
                        </div>
                    )}
                    {decision.key_risks && decision.key_risks.length > 0 && (
                        <div>
                            <h4 className="text-[9px] font-mono tracking-widest text-[#4a5270] uppercase mb-1.5">
                                Risks
                            </h4>
                            <div className="space-y-1">
                                {decision.key_risks.slice(0, 3).map((r, i) => (
                                    <p key={i} className="text-[10px] text-[#a0b0c8] leading-snug">
                                        <span className="text-[#c0444a]">— </span>{r}
                                    </p>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Score Breakdown — inline list (replaces radar chart) */}
                {Object.keys(scores).length > 0 && (
                    <div className="border-t border-white/[0.04] pt-3">
                        <h4 className="text-[9px] font-mono tracking-widest text-[#4a5270] uppercase mb-2">
                            Score Breakdown
                        </h4>
                        <div className="space-y-1.5">
                            {AGENT_ORDER.map(({ key, label }) => {
                                const score = scores[key];
                                if (score === undefined) return null;
                                return (
                                    <div key={key} className="flex items-center gap-2">
                                        <span className="text-[10px] text-[#7888a5] w-20 flex-shrink-0">
                                            {label}
                                        </span>
                                        <div className="flex-1 h-1 rounded-full bg-white/[0.04] overflow-hidden">
                                            <motion.div
                                                className="h-full rounded-full score-bar-fill"
                                                style={{ backgroundColor: scoreBarColor(score) }}
                                                initial={{ width: 0 }}
                                                animate={{ width: `${(score / 10) * 100}%` }}
                                                transition={{ duration: 0.6, delay: 0.1 }}
                                            />
                                        </div>
                                        <span className="font-dm-mono text-[10px] text-[#8896b3] w-5 text-right">
                                            {score.toFixed(1)}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </motion.div>
        </AnimatePresence>
    );
}
