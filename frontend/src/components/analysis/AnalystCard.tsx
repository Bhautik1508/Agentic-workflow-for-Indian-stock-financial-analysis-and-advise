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
    /** The run stopped before this analyst was reached — distinct from an
     *  analyst that ran and was excluded for want of data. */
    notRun?: boolean;
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
        case 'positive': return 'bg-buy';
        case 'negative': return 'bg-sell';
        default:         return 'bg-ink-4';
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

    // A failed analyst can be opened when there is a reason to show. That
    // reason used to live only in a `title` tooltip — which does not exist on
    // touch, so on a phone "Excluded — data unavailable" was the end of it.
    const hasError = !!report.error?.trim();
    const canExpand = !isRunning && (!isDegraded || hasError);

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
                onClick={() => canExpand && setExpanded(v => !v)}
                disabled={!canExpand}
                className={`w-full flex items-center gap-4 px-5 py-4 text-left ${canExpand ? 'cursor-pointer hover:bg-paper-hover' : ''} transition-colors`}
            >
                <AnalystMonogram name={report.agent_name} />

                <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-3">
                        <h3 className="font-serif text-[18px] font-semibold text-ink leading-tight">
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
                            <span className="text-micro text-ink-3 shrink-0">n/a</span>
                        )}
                    </div>
                    <div className="mt-1">
                        {isRunning ? (
                            <div className="flex items-center gap-1.5">
                                <span className="pulse-dot w-1 h-1 rounded-full bg-ink-3" />
                                <span className="pulse-dot w-1 h-1 rounded-full bg-ink-3" />
                                <span className="pulse-dot w-1 h-1 rounded-full bg-ink-3" />
                                <span className="text-small text-ink-3 ml-2">Reasoning…</span>
                            </div>
                        ) : isDegraded ? (
                            <p className="text-small text-ink-3">
                                {report.notRun
                                    ? 'Not run — the analysis stopped first'
                                    : 'Excluded — data unavailable'}
                                {hasError && <span className="text-ink-3"> · why?</span>}
                            </p>
                        ) : (
                            <p className="text-small text-ink-2 line-clamp-1">
                                {report.signal_line || report.summary?.slice(0, 90) || '—'}
                            </p>
                        )}
                    </div>
                </div>

                {canExpand && (
                    <ChevronDown
                        size={16}
                        className={`text-ink-4 transition-transform shrink-0 ${expanded ? 'rotate-180' : ''}`}
                    />
                )}
            </button>

            {/* ─── Expanded panel ─── */}
            <AnimatePresence initial={false}>
                {expanded && canExpand && (
                    <motion.div
                        key="content"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.22, ease: 'easeInOut' }}
                        className="overflow-hidden"
                    >
                        <div className="px-5 pb-5 pt-1 border-t border-rule">
                            {isDegraded ? (
                                <div className="pt-4">
                                    <h4 className="heading-eyebrow mb-2">Why it was excluded</h4>
                                    <p className="text-small text-ink-2 font-mono break-words">
                                        {report.error}
                                    </p>
                                    <p className="text-micro text-ink-4 mt-3">
                                        This pillar contributed nothing to the verdict — it was not
                                        scored zero, it was left out of the weighting entirely.
                                    </p>
                                </div>
                            ) : (
                            <>
                            {report.summary && (
                                <p className="text-body text-ink-2 mb-5 max-w-prose">
                                    {report.summary}
                                </p>
                            )}

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-x-8 gap-y-5">
                                {/* Key signals (data table) */}
                                <div className="md:col-span-2">
                                    <h4 className="heading-eyebrow mb-2">Key signals</h4>
                                    {report.data_table && report.data_table.length > 0 ? (
                                        <ul className="divide-y divide-rule-soft">
                                            {report.data_table.map((row, i) => (
                                                <li key={i} className="flex items-baseline justify-between py-2">
                                                    <span className="flex items-center gap-2">
                                                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${signalDot(row.signal)}`} />
                                                        <span className="text-small text-ink-2">{row.label}</span>
                                                    </span>
                                                    <span className="font-tnum text-[14px] text-ink">{row.value}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    ) : (
                                        <p className="text-small text-ink-4">No signals returned.</p>
                                    )}
                                </div>

                                {/* Findings + flags */}
                                <div className="space-y-5">
                                    {report.key_findings && report.key_findings.length > 0 && (
                                        <div>
                                            <h4 className="heading-eyebrow mb-2">Findings</h4>
                                            <ul className="space-y-1.5">
                                                {report.key_findings.slice(0, 3).map((f, i) => (
                                                    <li key={i} className="text-small text-ink-2 leading-snug">
                                                        <span className="text-buy mr-1.5">+</span>{f}
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
                                                    <li key={i} className="text-small text-ink-2 leading-snug">
                                                        <span className="text-sell mr-1.5">−</span>{f}
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}
                                </div>
                            </div>
                            </>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.article>
    );
}
