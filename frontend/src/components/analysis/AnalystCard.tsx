'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ─── Types ─────────────────────────────────
interface DataTableRow {
    label: string;
    value: string;
    signal: string;
}

interface AgentReportData {
    agent_name: string;
    status: 'running' | 'complete' | 'error';
    score: number;
    signal_line?: string;
    data_table?: DataTableRow[];
    key_findings?: string[];
    risk_flags?: string[];
    summary?: string;
}

interface AnalystCardProps {
    report: AgentReportData;
    index?: number;
}

// ─── Helpers ───────────────────────────────
const AGENT_ICONS: Record<string, string> = {
    'Financial Analyst': '📊',
    'Technical Analyst': '📈',
    'Sentiment Analyst': '💬',
    'Risk Analyst': '🛡️',
    'Macro & Governance Analyst': '🏛️',
};

function scoreColor(score: number): string {
    if (score >= 7) return '#3d9970';   // buy-ish
    if (score >= 5) return '#8a7a40';   // hold
    return '#c0444a';                   // sell-ish
}

function scoreBgColor(score: number): string {
    if (score >= 7) return 'rgba(61, 153, 112, 0.70)';
    if (score >= 5) return 'rgba(138, 122, 64, 0.70)';
    return 'rgba(192, 68, 74, 0.70)';
}

function signalDotColor(signal: string): string {
    switch (signal) {
        case 'positive': return '#3d9970';
        case 'negative': return '#c0444a';
        default: return '#5a6480';
    }
}

function agentShortName(name: string): string {
    return name.replace(' Analyst', '').replace('Macro & Governance', 'Macro & Gov');
}

// ─── Component ─────────────────────────────
export function AnalystCard({ report, index = 0 }: AnalystCardProps) {
    const [expanded, setExpanded] = useState(false);
    const isRunning = report.status === 'running';
    const isError = report.status === 'error';
    const icon = AGENT_ICONS[report.agent_name] || '📋';

    return (
        <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.06, duration: 0.3 }}
            className="bg-[#0c0f19] border border-white/[0.06] rounded-xl overflow-hidden"
        >
            {/* ─── Collapsed Row ─── */}
            <button
                onClick={() => !isRunning && !isError && setExpanded(!expanded)}
                className="w-full flex items-center gap-3 px-4 h-16 cursor-pointer hover:bg-white/[0.02] transition-colors"
                disabled={isRunning || isError}
            >
                {/* Score dot / Running pulse */}
                <div className="w-3 flex-shrink-0 flex justify-center">
                    {isRunning ? (
                        <span className="w-2.5 h-2.5 rounded-full bg-[#5a6480] animate-pulse" />
                    ) : isError ? (
                        <span className="w-2.5 h-2.5 rounded-full bg-[#c0444a]/50" />
                    ) : (
                        <span
                            className="w-2.5 h-2.5 rounded-full"
                            style={{ backgroundColor: scoreColor(report.score) }}
                        />
                    )}
                </div>

                {/* Icon + Name */}
                <span className="text-sm mr-1">{icon}</span>
                <span className="text-xs font-medium text-[#7888a5] whitespace-nowrap">
                    {agentShortName(report.agent_name)}
                </span>

                {/* Signal line / Running state / Error */}
                <div className="flex-1 min-w-0 text-left ml-1">
                    {isRunning ? (
                        <div className="flex items-center gap-1">
                            <span className="pulse-dot w-1 h-1 rounded-full bg-[#5a6480]" />
                            <span className="pulse-dot w-1 h-1 rounded-full bg-[#5a6480]" />
                            <span className="pulse-dot w-1 h-1 rounded-full bg-[#5a6480]" />
                            <div className="ml-2 h-2.5 w-24 rounded skeleton-shimmer bg-[#111627]" />
                        </div>
                    ) : isError ? (
                        <span className="text-[11px] text-[#c0444a]/60 font-mono">
                            Analysis unavailable
                        </span>
                    ) : (
                        <span className="text-[11px] text-[#a0b0c8] truncate block font-mono">
                            {report.signal_line || report.summary?.slice(0, 60) || '—'}
                        </span>
                    )}
                </div>

                {/* Score + Bar */}
                {!isRunning && !isError && (
                    <div className="flex items-center gap-2 flex-shrink-0">
                        <div className="w-16 h-1 rounded-full bg-white/[0.04] overflow-hidden">
                            <div
                                className="h-full rounded-full score-bar-fill"
                                style={{
                                    width: `${(report.score / 10) * 100}%`,
                                    backgroundColor: scoreBgColor(report.score),
                                }}
                            />
                        </div>
                        <span
                            className="font-dm-mono text-xs font-medium w-6 text-right"
                            style={{ color: scoreColor(report.score) }}
                        >
                            {report.score.toFixed(1)}
                        </span>
                    </div>
                )}

                {/* Chevron */}
                {!isRunning && !isError && (
                    <ChevronDown
                        size={14}
                        className={`text-[#4a5270] transition-transform flex-shrink-0 ${expanded ? 'rotate-180' : ''
                            }`}
                    />
                )}
            </button>

            {/* ─── Expanded Panel ─── */}
            <AnimatePresence>
                {expanded && !isRunning && !isError && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: 'easeInOut' }}
                        className="overflow-hidden"
                    >
                        <div className="px-4 pb-4 pt-1 border-t border-white/[0.04]">
                            <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                                {/* Left: Data Table (3 cols) */}
                                <div className="md:col-span-3">
                                    <h4 className="text-[9px] font-mono tracking-widest text-[#4a5270] mb-2 uppercase">
                                        Key Signals
                                    </h4>
                                    <div className="space-y-0">
                                        {(report.data_table || []).map((row, i) => (
                                            <div
                                                key={i}
                                                className="flex items-center justify-between py-1.5 border-b border-white/[0.03] last:border-0"
                                            >
                                                <div className="flex items-center gap-2">
                                                    <span
                                                        className="w-1 h-1 rounded-full flex-shrink-0"
                                                        style={{ backgroundColor: signalDotColor(row.signal) }}
                                                    />
                                                    <span className="text-[11px] text-[#7888a5]">
                                                        {row.label}
                                                    </span>
                                                </div>
                                                <span className="text-[11px] font-mono text-[#dce4f5]">
                                                    {row.value}
                                                </span>
                                            </div>
                                        ))}
                                        {(!report.data_table || report.data_table.length === 0) && (
                                            <p className="text-[10px] text-[#4a5270] font-mono py-2">
                                                No data table available
                                            </p>
                                        )}
                                    </div>
                                </div>

                                {/* Right: Key Findings + Flags (2 cols) */}
                                <div className="md:col-span-2">
                                    {/* Key Findings */}
                                    {report.key_findings && report.key_findings.length > 0 && (
                                        <div className="mb-3">
                                            <h4 className="text-[9px] font-mono tracking-widest text-[#4a5270] mb-2 uppercase">
                                                Findings
                                            </h4>
                                            <div className="space-y-1">
                                                {report.key_findings.slice(0, 3).map((f, i) => (
                                                    <p key={i} className="text-[10px] text-[#a0b0c8] leading-relaxed">
                                                        <span className="text-[#3d9970] mr-1">+</span>
                                                        {f}
                                                    </p>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Risk Flags */}
                                    {report.risk_flags && report.risk_flags.length > 0 && (
                                        <div>
                                            <h4 className="text-[9px] font-mono tracking-widest text-[#4a5270] mb-2 uppercase">
                                                Flags
                                            </h4>
                                            <div className="space-y-1">
                                                {report.risk_flags.slice(0, 3).map((f, i) => (
                                                    <p key={i} className="text-[10px] text-[#a0b0c8] leading-relaxed">
                                                        <span className="text-[#c0444a] mr-1">—</span>
                                                        {f}
                                                    </p>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}
