'use client';

import { motion } from 'framer-motion';
import { AgentReport } from '@/hooks/useSSE';
import { ShieldAlert, TrendingUp, Brain, BarChart3, Landmark, XCircle } from 'lucide-react';

const AGENT_CONFIG: Record<string, { color: string; icon: typeof BarChart3; label: string }> = {
    'financial_node': { color: '#00ff9f', icon: BarChart3, label: 'Financial Analyst' },
    'sentiment_node': { color: '#ff9f00', icon: Brain, label: 'Sentiment Analyst' },
    'risk_node': { color: '#ff4060', icon: ShieldAlert, label: 'Risk Analyst' },
    'technical_node': { color: '#4080ff', icon: TrendingUp, label: 'Technical Analyst' },
    'macro_governance_node': { color: '#c0c040', icon: Landmark, label: 'Macro & Governance' },
};

function ScoreBar({ score }: { score: number }) {
    const pct = Math.min(Math.max((score / 10) * 100, 0), 100);
    const color = score >= 7 ? '#00ff9f' : score >= 5 ? '#ff9f00' : '#ff4060';

    return (
        <div className="flex items-center gap-2 w-full">
            <div className="flex-1 h-[6px] bg-white/5 rounded-full overflow-hidden">
                <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 1, ease: 'easeOut', delay: 0.2 }}
                    className="h-full rounded-full"
                    style={{ backgroundColor: color }}
                />
            </div>
            <span className="text-xs font-mono-num font-semibold min-w-[32px] text-right" style={{ color }}>
                {score.toFixed(1)}
            </span>
        </div>
    );
}

export function AgentCard({ nodeName, report, isRunning }: { nodeName: string; report?: AgentReport; isRunning: boolean }) {
    const config = AGENT_CONFIG[nodeName] || { color: '#6b82a0', icon: BarChart3, label: nodeName };
    const Icon = config.icon;
    const displayName = report?.agent_name || config.label;

    // Pending state
    if (!report && !isRunning) {
        return (
            <div
                className="rounded-xl border border-border/30 bg-surface/20 p-4 opacity-40"
                style={{ borderLeftColor: config.color, borderLeftWidth: '3px' }}
            >
                <div className="flex items-center gap-3">
                    <Icon size={16} style={{ color: config.color }} />
                    <span className="text-sm text-text-dim">{config.label}</span>
                </div>
            </div>
        );
    }

    // Running / analyzing state
    if (isRunning && !report) {
        return (
            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-xl border border-border/40 bg-surface/40 p-4 relative overflow-hidden"
                style={{ borderLeftColor: config.color, borderLeftWidth: '3px' }}
            >
                {/* Shimmer effect */}
                <motion.div
                    className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.02] to-transparent"
                    animate={{ x: ['-100%', '100%'] }}
                    transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                />
                <div className="flex items-center gap-3 relative z-10">
                    <Icon size={16} style={{ color: config.color }} />
                    <span className="text-sm font-medium" style={{ color: config.color }}>{config.label}</span>
                    <div className="flex gap-1 ml-auto">
                        <div className="w-1.5 h-1.5 rounded-full pulse-dot" style={{ backgroundColor: config.color }} />
                        <div className="w-1.5 h-1.5 rounded-full pulse-dot" style={{ backgroundColor: config.color }} />
                        <div className="w-1.5 h-1.5 rounded-full pulse-dot" style={{ backgroundColor: config.color }} />
                    </div>
                </div>
                <p className="text-[10px] font-mono text-text-dim mt-2 tracking-wider uppercase relative z-10">
                    Analysing...
                </p>
            </motion.div>
        );
    }

    // Complete / Error state
    const isError = report!.status === 'error';

    return (
        <motion.div
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            className="rounded-xl border border-border/50 bg-surface/60 backdrop-blur-sm overflow-hidden"
            style={{ borderLeftColor: isError ? '#ff4060' : config.color, borderLeftWidth: '3px' }}
        >
            <div className="p-4">
                {/* Header */}
                <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                        {isError ? (
                            <XCircle size={16} className="text-danger" />
                        ) : (
                            <Icon size={16} style={{ color: config.color }} />
                        )}
                        <h3 className="text-sm font-semibold text-foreground/90">{displayName}</h3>
                    </div>
                    <span
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                        style={{
                            backgroundColor: isError ? 'rgba(255,64,96,0.1)' : 'rgba(0,255,159,0.1)',
                            color: isError ? '#ff4060' : '#00ff9f',
                        }}
                    >
                        {isError ? 'ERROR' : 'COMPLETE'}
                    </span>
                </div>

                {/* Score bar */}
                {!isError && <ScoreBar score={report!.score} />}

                {/* Summary */}
                <p className="text-xs text-foreground/60 leading-relaxed mt-3 line-clamp-3">
                    {report!.summary}
                </p>

                {/* Key findings as pills */}
                {!isError && report!.key_findings && report!.key_findings.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-3">
                        {report!.key_findings.slice(0, 3).map((finding, idx) => (
                            <span
                                key={idx}
                                className="text-[10px] px-2 py-0.5 rounded-full bg-white/[0.04] text-text-muted border border-white/[0.06] truncate max-w-[200px]"
                            >
                                {finding}
                            </span>
                        ))}
                    </div>
                )}

                {/* Risk flags */}
                {!isError && report!.risk_flags && report!.risk_flags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                        {report!.risk_flags.slice(0, 2).map((risk, idx) => (
                            <span
                                key={idx}
                                className="inline-flex items-center gap-1 text-[9px] uppercase font-mono tracking-wider px-1.5 py-0.5 rounded bg-danger/10 text-danger/80 border border-danger/15"
                            >
                                ⚠ {risk}
                            </span>
                        ))}
                    </div>
                )}

                {/* Confidence */}
                {!isError && (
                    <div className="mt-3 text-[10px] text-text-dim font-mono">
                        Confidence: {((report!.confidence || 0) * 100).toFixed(0)}%
                    </div>
                )}
            </div>
        </motion.div>
    );
}
