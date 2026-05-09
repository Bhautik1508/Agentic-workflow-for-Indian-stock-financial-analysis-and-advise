'use client';

import { useAnalysis, type RiskProfile } from '@/hooks/useAnalysis';
import { use, useState } from 'react';
import { TopBar } from '@/components/analysis/TopBar';
import { PriceChart } from '@/components/analysis/PriceChart';
import { AnalystCard } from '@/components/analysis/AnalystCard';
import { VerdictHero } from '@/components/analysis/VerdictHero';
import { ScoreBreakdown } from '@/components/analysis/ScoreBreakdown';
import { ComparisonRow } from '@/components/analysis/ComparisonRow';
import { CounterFactualPanel } from '@/components/analysis/CounterFactualPanel';
import { Disclaimer } from '@/components/analysis/Disclaimer';
import { HistorySidebar } from '@/components/HistorySidebar';
import { WatchToggle } from '@/components/analysis/WatchToggle';
import { ShareButton } from '@/components/analysis/ShareButton';
import { PrintButton } from '@/components/analysis/PrintButton';

const AGENT_NODES = [
    'financial_node',
    'technical_node',
    'risk_node',
    'sentiment_node',
    'macro_governance_node',
];

const PROFILE_OPTIONS: { value: RiskProfile; label: string; tagline: string }[] = [
    { value: 'conservative', label: 'Conservative', tagline: 'Capital preservation' },
    { value: 'balanced',     label: 'Balanced',     tagline: 'Standard mix' },
    { value: 'aggressive',   label: 'Aggressive',   tagline: 'Momentum / sentiment' },
];

export default function AnalyzePage({ params }: { params: Promise<{ ticker: string }> }) {
    const unwrappedParams = use(params);
    const ticker = unwrappedParams.ticker;
    const [profile, setProfile] = useState<RiskProfile>('balanced');
    const state = useAnalysis(ticker, profile);

    const decodedName = decodeURIComponent(ticker);
    const isComplete = state.status === 'complete';
    const isAnalyzing = state.status === 'analyzing';

    const timestamp = new Date().toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });

    function jumpToAnalyst(node: string) {
        const id = `analyst-${node.replace('_node', '').replace(/_/g, '-')}`;
        const el = document.getElementById(id);
        el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    return (
        <div className="w-full min-h-screen relative">
            <div className="no-print">
                <HistorySidebar />
            </div>

            <div className="no-print">
                <TopBar
                    ticker={decodedName}
                    exchange="NSE"
                    timestamp={isComplete ? timestamp : undefined}
                />
            </div>

            <div className="max-w-6xl mx-auto px-4 md:px-8 py-8 md:py-10 pb-20">

                {/* Profile selector + actions row */}
                <div className="flex items-center justify-between gap-3 mb-6 flex-wrap no-print">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="heading-eyebrow mr-1">Profile</span>
                        {PROFILE_OPTIONS.map((opt) => {
                            const active = profile === opt.value;
                            return (
                                <button
                                    key={opt.value}
                                    onClick={() => setProfile(opt.value)}
                                    disabled={state.status === 'analyzing' || state.status === 'initializing'}
                                    className={`px-3 py-1.5 text-[12px] font-medium rounded-md border transition
                                        ${active
                                            ? 'border-[#1E40AF] bg-[#F0F4FB] text-[#1E40AF]'
                                            : 'border-[#E5E3DB] bg-white text-[#4A4D55] hover:border-[#C6C3B8]'}
                                        disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer`}
                                    title={opt.tagline}
                                >
                                    {opt.label}
                                </button>
                            );
                        })}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                        <WatchToggle name={decodedName} />
                        <ShareButton runId={state.run_id} disabled={state.status !== 'complete'} />
                        <PrintButton />
                    </div>
                </div>

                {/* ─── Verdict hero ─── */}
                <VerdictHero
                    decision={state.final_decision}
                    agents={state.agents}
                    status={state.status}
                />

                {/* ─── Comparison row ─── */}
                <ComparisonRow agents={state.agents} />

                {/* ─── Price chart with target/stop overlays ─── */}
                <section className="mt-8">
                    <PriceChart
                        // Prefer the resolved exchange ticker emitted by the backend
                        // `start` event (e.g. RELIANCE.NS); fall back to the URL name
                        // until the backend has resolved it.
                        ticker={state.ticker ?? decodedName}
                        targetPrice={state.final_decision?.target_price ?? null}
                        stopLoss={state.final_decision?.stop_loss ?? null}
                    />
                </section>

                {/* ─── Score breakdown (always visible) ─── */}
                <ScoreBreakdown agents={state.agents} onJumpToAnalyst={jumpToAnalyst} />

                {/* ─── What would change this verdict? ─── */}
                <CounterFactualPanel counterFactual={state.final_decision?.counter_factual} />

                {/* ─── Analyst cards ─── */}
                <section className="mt-10">
                    <h2 className="heading-section mb-5">Analyst notes</h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {AGENT_NODES.map((nodeName, i) => {
                            const report = state.agents[nodeName];
                            const inProgress = (isAnalyzing || state.status === 'initializing') && !report;

                            const reportStatus: 'running' | 'complete' | 'error' = report
                                ? (report.status === 'error' || report.degraded ? 'error' : 'complete')
                                : inProgress ? 'running' : 'error';

                            return (
                                <AnalystCard
                                    key={nodeName}
                                    index={i}
                                    report={{
                                        agent_name: report?.agent_name || nodeName.replace('_node', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) + ' Analyst',
                                        status: reportStatus,
                                        score: report?.score ?? null,
                                        signal_line: report?.signal_line,
                                        data_table: report?.data_table,
                                        key_findings: report?.key_findings,
                                        risk_flags: report?.risk_flags,
                                        summary: report?.summary,
                                        degraded: report?.degraded,
                                        error: report?.error ?? null,
                                    }}
                                />
                            );
                        })}
                    </div>
                </section>

                <Disclaimer />
            </div>
        </div>
    );
}
