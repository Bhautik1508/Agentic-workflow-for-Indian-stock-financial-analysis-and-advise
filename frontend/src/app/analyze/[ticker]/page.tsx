'use client';

import { useAnalysis } from '@/hooks/useAnalysis';
import { use } from 'react';
import { motion } from 'framer-motion';
import { AgentCard } from '@/components/AgentCard';
import { VerdictPanel } from '@/components/VerdictPanel';
import { AnalystRadar } from '@/components/RadarChart';
import { StockChart } from '@/components/StockChart';
import { HistorySidebar } from '@/components/HistorySidebar';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import Link from 'next/link';

const NODE_NAMES = [
    'financial_node',
    'technical_node',
    'sentiment_node',
    'risk_node',
    'macro_governance_node',
];

export default function AnalyzePage({ params }: { params: Promise<{ ticker: string }> }) {
    const unwrappedParams = use(params);
    const ticker = unwrappedParams.ticker;
    const state = useAnalysis(ticker);

    const decodedName = decodeURIComponent(ticker);
    const completedCount = Object.keys(state.agents).length;
    const totalAgents = NODE_NAMES.length;
    const isAnalyzing = state.status === 'analyzing';
    const isComplete = state.status === 'complete';

    return (
        <div className="w-full min-h-screen relative z-10">
            <HistorySidebar />
            {/* Sticky Top Bar */}
            <div className="sticky top-0 z-40 w-full bg-background/80 backdrop-blur-xl border-b border-border/40">
                <div className="max-w-7xl mx-auto px-4 md:px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <Link
                            href="/"
                            className="text-text-dim hover:text-primary transition-colors"
                        >
                            <ArrowLeft size={18} />
                        </Link>

                        <div className="flex items-center gap-3">
                            <h1 className="text-lg font-bold tracking-tight">{decodedName}</h1>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                                NSE
                            </span>
                        </div>
                    </div>

                    <div className="flex items-center gap-4">
                        {/* Status indicator */}
                        <div className="flex items-center gap-2">
                            {isAnalyzing && (
                                <>
                                    <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                                    <span className="text-xs font-mono text-primary">
                                        LIVE {completedCount}/{totalAgents}
                                    </span>
                                </>
                            )}
                            {isComplete && (
                                <span className="text-xs font-mono text-success">
                                    ✓ COMPLETE
                                </span>
                            )}
                            {state.status === 'error' && (
                                <span className="text-xs font-mono text-danger">
                                    ✗ ERROR
                                </span>
                            )}
                        </div>

                        {/* Timestamp */}
                        <span className="hidden md:block text-[10px] font-mono text-text-dim">
                            {new Date().toLocaleString('en-IN', {
                                day: '2-digit', month: 'short', year: 'numeric',
                                hour: '2-digit', minute: '2-digit',
                            })}
                        </span>

                        {/* Re-analyze button */}
                        {isComplete && (
                            <button
                                onClick={() => window.location.reload()}
                                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface border border-border hover:border-primary/40 hover:text-primary transition-all cursor-pointer"
                            >
                                <RefreshCw size={12} />
                                Re-analyze
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Main Content */}
            <div className="max-w-7xl mx-auto px-4 md:px-6 py-6 pb-24">
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

                    {/* Left Column — Agent Cards Feed (60%) */}
                    <div className="lg:col-span-3 flex flex-col gap-3">
                        <h2 className="text-[10px] font-mono tracking-[0.2em] text-text-dim uppercase mb-1">
                            Agent Analysis Feed
                        </h2>

                        <div className="flex flex-col gap-3">
                            {NODE_NAMES.map((nodeName, i) => {
                                const report = state.agents[nodeName];
                                const isRunning =
                                    isAnalyzing &&
                                    !report &&
                                    completedCount < totalAgents;

                                return (
                                    <motion.div
                                        key={nodeName}
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1 }}
                                        transition={{ delay: i * 0.05 }}
                                    >
                                        <AgentCard
                                            nodeName={nodeName}
                                            report={report}
                                            isRunning={isRunning}
                                        />
                                    </motion.div>
                                );
                            })}
                        </div>
                    </div>

                    {/* Right Column — Verdict + Radar (40%) */}
                    <div className="lg:col-span-2">
                        <div className="sticky top-20 flex flex-col gap-4">
                            <h2 className="text-[10px] font-mono tracking-[0.2em] text-text-dim uppercase mb-1">
                                Final Verdict
                            </h2>

                            <VerdictPanel
                                decision={state.final_decision}
                                status={state.status}
                                errorMessage={state.message}
                            />

                            {/* Radar chart — shows after all agents complete */}
                            <AnalystRadar agents={state.agents} />

                            {/* Price chart */}
                            <StockChart ticker={decodedName} />
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
}
