'use client';

import { motion } from 'framer-motion';
import type { AgentReport } from '@/hooks/useAnalysis';
import { PILLAR_ORDER } from '@/lib/strengths';

interface ScoreBreakdownProps {
    agents: Record<string, AgentReport | undefined>;
    onJumpToAnalyst?: (node: string) => void;
}

function scoreColor(score: number): string {
    if (score >= 7) return '#15803D';
    if (score >= 5) return '#A16207';
    return '#B91C1C';
}

export function ScoreBreakdown({ agents, onJumpToAnalyst }: ScoreBreakdownProps) {
    return (
        <section className="mt-8">
            <h2 className="heading-eyebrow mb-3">How the verdict was built</h2>
            <div className="card-paper p-5 md:p-6">
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4 md:gap-6">
                    {PILLAR_ORDER.map(({ node, label }, i) => {
                        const r = agents[node];
                        const isLoading = !r;
                        const isDegraded = r?.status === 'error' || r?.degraded || r?.score === null;
                        const value = r?.score ?? 0;

                        return (
                            <button
                                key={node}
                                onClick={() => onJumpToAnalyst?.(node)}
                                disabled={isLoading || isDegraded}
                                className={`group text-left transition-colors ${(!isLoading && !isDegraded) ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
                            >
                                <div className="flex items-baseline justify-between mb-1.5">
                                    <span className="text-small text-[#4A4D55]">{label}</span>
                                    {isLoading ? (
                                        <span className="text-micro text-[#B6B8B8]">—</span>
                                    ) : isDegraded ? (
                                        <span className="text-micro text-[#7A7F88]">n/a</span>
                                    ) : (
                                        <span className="font-tnum text-[15px] font-semibold" style={{ color: scoreColor(value) }}>
                                            {value.toFixed(1)}
                                        </span>
                                    )}
                                </div>
                                <div className="h-1.5 rounded-full bg-[#F2F1EB] overflow-hidden">
                                    {!isLoading && !isDegraded && (
                                        <motion.div
                                            initial={{ width: 0 }}
                                            animate={{ width: `${(value / 10) * 100}%` }}
                                            transition={{ duration: 0.55, delay: 0.05 * i }}
                                            className="h-full rounded-full"
                                            style={{ backgroundColor: scoreColor(value) }}
                                        />
                                    )}
                                    {isLoading && (
                                        <div className="h-full rounded-full skeleton-shimmer bg-[#EFEDE5]" />
                                    )}
                                </div>
                                {r?.signal_line && !isDegraded && (
                                    <p className="text-micro text-[#7A7F88] mt-1.5 line-clamp-1">{r.signal_line}</p>
                                )}
                                {isDegraded && (
                                    <p className="text-micro text-[#7A7F88] mt-1.5">Excluded from verdict</p>
                                )}
                            </button>
                        );
                    })}
                </div>
                <p className="text-micro text-[#B6B8B8] mt-4">Click a pillar to jump to its full reasoning.</p>
            </div>
        </section>
    );
}
