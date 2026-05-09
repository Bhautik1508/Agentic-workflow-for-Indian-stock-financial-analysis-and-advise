'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { AnalystMonogram } from './AnalystMonogram';

// ─── Types ─────────────────────────────────
interface DataTableRow {
    label: string;
    value: string;
    signal: string;
}

interface AgentReportData {
    agent_name: string;
    status: 'running' | 'complete' | 'error';
    score: number | null;
    signal_line?: string;
    data_table?: DataTableRow[];
    key_findings?: string[];
    risk_flags?: string[];
    summary?: string;
    degraded?: boolean;
    error?: string | null;
}

interface AnalystCardProps {
    report: AgentReportData;
    index?: number;
    initialOpen?: boolean;
}

// ─── Helpers ───────────────────────────────
function scoreColor(score: number): string {
    if (score >= 7) return '#15803D';
    if (score >= 5) return '#A16207';
    return '#B91C1C';
}

function signalDot(signal: string): string {
    switch (signal) {
        case 'positive': return 'bg-[#15803D]';
        case 'negative': return 'bg-[#B91C1C]';
        default:         return 'bg-[#B6B8B8]';
    }
}

function shortName(name: string): string {
    return name.replace(' Analyst', '').replace('Macro & Governance', 'Macro & Gov');
}

// ─── Component ─────────────────────────────
export function AnalystCard({ report, index = 0, initialOpen = false }: AnalystCardProps) {
    const [expanded, setExpanded] = useState(initialOpen);
    const isRunning = report.status === 'running';
    const isDegraded = report.status === 'error' || report.degraded === true || report.score === null;
    const scoreValue = report.score ?? 0;

    return (
        <motion.article
            id={`analyst-${shortName(report.agent_name).toLowerCase().replace(/\s+/g, '-')}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05, duration: 0.3 }}
            className="card-paper"
        >
            {/* ─── Header row ─── */}
            <button
                onClick={() => !isRunning && !isDegraded && setExpanded(v => !v)}
                disabled={isRunning || isDegraded}
                className={`w-full flex items-center gap-4 px-5 py-4 text-left ${(!isRunning && !isDegraded) ? 'cursor-pointer hover:bg-[#F8F7F2]' : ''} transition-colors`}
            >
                <AnalystMonogram name={report.agent_name} />

                <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-3">
                        <h3 className="font-serif text-[18px] font-semibold text-[#1A1B1E] leading-tight">
                            {shortName(report.agent_name)}
                        </h3>
                        {!isRunning && !isDegraded && (
                            <span
                                className="font-tnum text-[18px] font-semibold shrink-0"
                                style={{ color: scoreColor(scoreValue) }}
                            >
                                {scoreValue.toFixed(1)}
                            </span>
                        )}
                        {isDegraded && (
                            <span className="text-micro text-[#7A7F88] shrink-0">n/a</span>
                        )}
                    </div>
                    <div className="mt-1">
                        {isRunning ? (
                            <div className="flex items-center gap-1.5">
                                <span className="pulse-dot w-1 h-1 rounded-full bg-[#7A7F88]" />
                                <span className="pulse-dot w-1 h-1 rounded-full bg-[#7A7F88]" />
                                <span className="pulse-dot w-1 h-1 rounded-full bg-[#7A7F88]" />
                                <span className="text-small text-[#7A7F88] ml-2">Reasoning…</span>
                            </div>
                        ) : isDegraded ? (
                            <p className="text-small text-[#7A7F88]" title={report.error ?? undefined}>
                                Excluded — data unavailable
                            </p>
                        ) : (
                            <p className="text-small text-[#4A4D55] line-clamp-1">
                                {report.signal_line || report.summary?.slice(0, 90) || '—'}
                            </p>
                        )}
                    </div>
                </div>

                {!isRunning && !isDegraded && (
                    <ChevronDown
                        size={16}
                        className={`text-[#B6B8B8] transition-transform shrink-0 ${expanded ? 'rotate-180' : ''}`}
                    />
                )}
            </button>

            {/* ─── Expanded panel ─── */}
            <AnimatePresence initial={false}>
                {expanded && !isRunning && !isDegraded && (
                    <motion.div
                        key="content"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.22, ease: 'easeInOut' }}
                        className="overflow-hidden"
                    >
                        <div className="px-5 pb-5 pt-1 border-t border-[#E5E3DB]">
                            {report.summary && (
                                <p className="text-body text-[#4A4D55] mb-5 max-w-prose">
                                    {report.summary}
                                </p>
                            )}

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-x-8 gap-y-5">
                                {/* Key signals (data table) */}
                                <div className="md:col-span-2">
                                    <h4 className="heading-eyebrow mb-2">Key signals</h4>
                                    {report.data_table && report.data_table.length > 0 ? (
                                        <ul className="divide-y divide-[#EFEDE5]">
                                            {report.data_table.map((row, i) => (
                                                <li key={i} className="flex items-baseline justify-between py-2">
                                                    <span className="flex items-center gap-2">
                                                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${signalDot(row.signal)}`} />
                                                        <span className="text-small text-[#4A4D55]">{row.label}</span>
                                                    </span>
                                                    <span className="font-tnum text-[14px] text-[#1A1B1E]">{row.value}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <p className="text-small text-[#B6B8B8]">No signals returned.</p>
                                    )}
                                </div>

                                {/* Findings + flags */}
                                <div className="space-y-5">
                                    {report.key_findings && report.key_findings.length > 0 && (
                                        <div>
                                            <h4 className="heading-eyebrow mb-2">Findings</h4>
                                            <ul className="space-y-1.5">
                                                {report.key_findings.slice(0, 3).map((f, i) => (
                                                    <li key={i} className="text-small text-[#4A4D55] leading-snug">
                                                        <span className="text-[#15803D] mr-1.5">+</span>{f}
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}
                                    {report.risk_flags && report.risk_flags.length > 0 && (
                                        <div>
                                            <h4 className="heading-eyebrow mb-2">Flags</h4>
                                            <ul className="space-y-1.5">
                                                {report.risk_flags.slice(0, 3).map((f, i) => (
                                                    <li key={i} className="text-small text-[#4A4D55] leading-snug">
                                                        <span className="text-[#B91C1C] mr-1.5">−</span>{f}
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.article>
    );
}
