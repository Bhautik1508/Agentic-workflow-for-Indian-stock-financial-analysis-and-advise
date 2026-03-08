'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, ArrowDown, Minus, BookOpen, AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';
import type { FinalDecision } from '@/hooks/useSSE';

interface VerdictPanelProps {
    decision: FinalDecision | null;
    status: string;
    errorMessage?: string;
}

const DECISION_CONFIG = {
    BUY: {
        color: '#00ff9f',
        bgClass: 'bg-[#00ff9f]/5',
        borderClass: 'border-[#00ff9f]/25',
        glowClass: 'glow-green',
        textClass: 'text-[#00ff9f]',
        icon: ArrowUp,
        label: 'BUY',
    },
    SELL: {
        color: '#ff4060',
        bgClass: 'bg-[#ff4060]/5',
        borderClass: 'border-[#ff4060]/25',
        glowClass: 'glow-red',
        textClass: 'text-[#ff4060]',
        icon: ArrowDown,
        label: 'SELL',
    },
    HOLD: {
        color: '#ffd700',
        bgClass: 'bg-[#ffd700]/5',
        borderClass: 'border-[#ffd700]/25',
        glowClass: 'glow-gold',
        textClass: 'text-[#ffd700]',
        icon: Minus,
        label: 'HOLD',
    },
};

function ConfidenceCircle({ score, color }: { score: number; color: string }) {
    const pct = Math.round(score * 10); // 0-100
    const radius = 36;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (pct / 100) * circumference;

    return (
        <div className="relative w-24 h-24 flex items-center justify-center">
            <svg className="w-24 h-24 -rotate-90" viewBox="0 0 80 80">
                <circle cx="40" cy="40" r={radius} stroke="rgba(255,255,255,0.06)" strokeWidth="4" fill="none" />
                <motion.circle
                    cx="40" cy="40" r={radius}
                    stroke={color}
                    strokeWidth="4"
                    fill="none"
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    initial={{ strokeDashoffset: circumference }}
                    animate={{ strokeDashoffset: offset }}
                    transition={{ duration: 1.5, ease: 'easeOut' }}
                />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-lg font-bold font-mono-num" style={{ color }}>{pct}%</span>
                <span className="text-[9px] text-text-dim uppercase tracking-wider">Confidence</span>
            </div>
        </div>
    );
}

export function VerdictPanel({ decision, status, errorMessage }: VerdictPanelProps) {
    if (status === 'error') {
        return (
            <div className="rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center flex flex-col items-center justify-center min-h-[300px]">
                <AlertTriangle size={32} className="text-danger mb-4" />
                <h3 className="text-lg font-bold text-danger mb-2">Analysis Failed</h3>
                <p className="text-sm text-foreground/70">{errorMessage || 'An error occurred'}</p>
            </div>
        );
    }

    if (!decision) {
        return (
            <div className="rounded-2xl border border-border/50 bg-surface/30 p-8 text-center flex flex-col items-center justify-center min-h-[300px]">
                <Loader2 size={28} className="text-primary/40 animate-spin mb-4" />
                <p className="text-sm text-text-muted">Awaiting analysis...</p>
                <div className="flex gap-1 mt-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-primary/40 pulse-dot" />
                    <div className="w-1.5 h-1.5 rounded-full bg-primary/40 pulse-dot" />
                    <div className="w-1.5 h-1.5 rounded-full bg-primary/40 pulse-dot" />
                </div>
            </div>
        );
    }

    const config = DECISION_CONFIG[decision.decision] || DECISION_CONFIG.HOLD;
    const DecisionIcon = config.icon;

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 15 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 120, damping: 20 }}
                className={`rounded-2xl border ${config.borderClass} ${config.bgClass} ${config.glowClass} p-6 relative overflow-hidden`}
            >
                {/* Top glow line */}
                <div
                    className="absolute top-0 left-0 w-full h-[2px]"
                    style={{ background: `linear-gradient(90deg, transparent, ${config.color}40, transparent)` }}
                />

                {/* Decision Badge */}
                <div className="flex flex-col items-center text-center mb-6">
                    <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-text-dim mb-3">
                        FINAL VERDICT
                    </p>
                    <div className="flex items-center gap-3">
                        <DecisionIcon size={28} className={config.textClass} />
                        <h2
                            className="text-5xl font-black tracking-tight"
                            style={{ color: config.color, textShadow: `0 0 30px ${config.color}30` }}
                        >
                            {config.label}
                        </h2>
                    </div>
                </div>

                {/* Confidence Circle */}
                <div className="flex justify-center mb-6">
                    <ConfidenceCircle score={decision.confidence_score} color={config.color} />
                </div>

                {/* Investment Thesis */}
                {decision.investment_thesis && (
                    <div className="mb-5">
                        <h4 className="text-xs font-semibold flex items-center gap-1.5 mb-2 text-text-muted uppercase tracking-wider">
                            <BookOpen size={12} /> Thesis
                        </h4>
                        <p className="text-sm text-foreground/70 leading-relaxed bg-black/20 p-3 rounded-lg border border-white/5">
                            {decision.investment_thesis}
                        </p>
                    </div>
                )}

                {/* Key Risks */}
                {decision.key_risks && decision.key_risks.length > 0 && (
                    <div>
                        <h4 className="text-xs font-semibold flex items-center gap-1.5 mb-2 text-warning uppercase tracking-wider">
                            <AlertTriangle size={12} /> Key Risks
                        </h4>
                        <ul className="space-y-1.5">
                            {decision.key_risks.map((risk, i) => (
                                <li key={i} className="text-xs text-foreground/60 flex items-start gap-2">
                                    <span className="text-warning mt-0.5">⚠</span>
                                    <span>{risk}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </motion.div>
        </AnimatePresence>
    );
}
