'use client';

import { useAnalysis } from '@/hooks/useAnalysis';
import { use } from 'react';
import { TopBar } from '@/components/analysis/TopBar';
import { PriceChart } from '@/components/analysis/PriceChart';
import { AnalystCard } from '@/components/analysis/AnalystCard';
import { VerdictPanel } from '@/components/VerdictPanel';
import { HistorySidebar } from '@/components/HistorySidebar';

const AGENT_NODES = [
    'financial_node',
    'technical_node',
    'risk_node',
    'sentiment_node',
    'macro_governance_node',
];

export default function AnalyzePage({ params }: { params: Promise<{ ticker: string }> }) {
    const unwrappedParams = use(params);
    const ticker = unwrappedParams.ticker;
    const state = useAnalysis(ticker);

    const decodedName = decodeURIComponent(ticker);
    const isComplete = state.status === 'complete';
    const isAnalyzing = state.status === 'analyzing';

    // Build agent scores map for verdict panel
    const agentScores: Record<string, number> = {};
    for (const node of AGENT_NODES) {
        const report = state.agents[node];
        if (report?.score !== undefined) {
            agentScores[node] = report.score;
        }
    }

    // Timestamp
    const timestamp = new Date().toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });

    return (
        <div className="w-full min-h-screen relative z-10">
            <HistorySidebar />

            {/* Sticky Top Bar */}
            <TopBar
                ticker={decodedName}
                exchange="NSE"
                timestamp={isComplete ? timestamp : undefined}
            />

            {/* Main Content */}
            <div className="max-w-7xl mx-auto px-4 md:px-6 py-5 pb-20">

                {/* Top Section: PriceChart (left) + VerdictPanel (right) */}
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 mb-6">
                    <div className="lg:col-span-3">
                        <PriceChart ticker={decodedName} />
                    </div>
                    <div className="lg:col-span-2">
                        <div className="sticky top-14">
                            <VerdictPanel
                                decision={state.final_decision}
                                status={state.status}
                                agentScores={agentScores}
                            />
                        </div>
                    </div>
                </div>

                {/* Analyst Cards — 2 column grid */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {AGENT_NODES.map((nodeName, i) => {
                        const report = state.agents[nodeName];
                        const inProgress = (isAnalyzing || state.status === 'initializing') && !report;

                        return (
                            <AnalystCard
                                key={nodeName}
                                index={i}
                                report={{
                                    agent_name: report?.agent_name || nodeName.replace('_node', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) + ' Analyst',
                                    status: report ? 'complete' : inProgress ? 'running' : 'error',
                                    score: report?.score ?? 0,
                                    signal_line: report?.signal_line,
                                    data_table: report?.data_table,
                                    key_findings: report?.key_findings,
                                    risk_flags: report?.risk_flags,
                                    summary: report?.summary,
                                }}
                            />
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
