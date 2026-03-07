'use client';

import { useSSE } from '@/hooks/useSSE';
import { use } from 'react';
import { motion } from 'framer-motion';
import { AgentCard } from '@/components/AgentCard';
import { Loader2, ArrowLeft, Target, TrendingDown, BookOpen } from 'lucide-react';
import Link from 'next/link';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function AnalyzePage({ params }: { params: Promise<{ ticker: string }> }) {
    const unwrappedParams = use(params);
    const ticker = unwrappedParams.ticker;
    const state = useSSE(ticker);

    const NODE_NAMES = [
        'financial_node',
        'sentiment_node',
        'risk_node',
        'technical_node',
        'macro_governance_node'
    ];

    const getDecisionColor = (decision: string) => {
        switch (decision) {
            case 'BUY': return 'text-success bg-success/10 border-success/30';
            case 'SELL': return 'text-danger bg-danger/10 border-danger/30';
            default: return 'text-warning bg-warning/10 border-warning/30';
        }
    };

    return (
        <div className="w-full max-w-6xl mx-auto px-4 py-8 pb-32">
            <div className="mb-8 flex items-center justify-between">
                <Link href="/" className="inline-flex items-center text-sm font-medium text-foreground/50 hover:text-primary transition-colors">
                    <ArrowLeft size={16} className="mr-2" /> Back to Search
                </Link>
                <div className="flex items-center gap-3">
                    <span className="text-xs uppercase tracking-widest font-mono text-foreground/40 border border-border px-3 py-1 rounded-full">
                        {state.status === 'error' ? 'SYSTEM ERROR' : state.status === 'complete' ? 'ANALYSIS COMPLETE' : 'LIVE FEED'}
                    </span>
                    {state.status !== 'complete' && state.status !== 'error' && (
                        <div className="w-2 h-2 rounded-full bg-danger animate-pulse" />
                    )}
                </div>
            </div>

            <header className="mb-12 border-b border-border/50 pb-8 relative">
                <h1 className="text-4xl md:text-5xl font-bold tracking-tight uppercase">
                    {decodeURIComponent(ticker)}
                </h1>
                <p className="mt-3 text-lg text-foreground/60 max-w-2xl font-mono">
                    {state.message || "Initializing deployment sequence..."}
                </p>
            </header>

            {/* Main Grid Layout */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">

                {/* Left Column: Flow of Agents */}
                <div className="lg:col-span-8 flex flex-col gap-6">
                    <h2 className="text-sm font-mono tracking-widest text-foreground/40 uppercase mb-2">Agent Swarm Activity</h2>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {NODE_NAMES.map(nodeName => {
                            const report = state.agents[nodeName];
                            const isRunning = state.status === 'analyzing' && !report && Object.keys(state.agents).length < NODE_NAMES.length;

                            return (
                                <AgentCard
                                    key={nodeName}
                                    nodeName={nodeName}
                                    report={report as any}
                                    isRunning={isRunning}
                                />
                            );
                        })}
                    </div>
                </div>

                {/* Right Column: Final Synthesizer */}
                <div className="lg:col-span-4">
                    <div className="sticky top-8">
                        <h2 className="text-sm font-mono tracking-widest text-foreground/40 uppercase mb-4">Final Verdict</h2>

                        {!state.final_decision ? (
                            <div className="rounded-2xl border border-border/50 bg-surface/30 p-8 text-center flex flex-col items-center justify-center min-h-[300px]">
                                <Loader2 size={32} className="text-primary/40 animate-spin mb-4" />
                                <p className="text-sm text-foreground/50">Awaiting consensus from specialist analysts.</p>
                                <p className="text-xs font-mono text-foreground/30 mt-2">The Judge will convene shortly...</p>
                            </div>
                        ) : (
                            <motion.div
                                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                                animate={{ opacity: 1, scale: 1, y: 0 }}
                                transition={{ type: "spring", stiffness: 100, damping: 20 }}
                                className={cn(
                                    "rounded-2xl border p-6 shadow-2xl relative overflow-hidden",
                                    state.final_decision.decision === 'BUY' ? "bg-success/5 border-success/20" :
                                        state.final_decision.decision === 'SELL' ? "bg-danger/5 border-danger/20" :
                                            "bg-warning/5 border-warning/20"
                                )}
                            >
                                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-current to-transparent opacity-20" />

                                <div className="flex flex-col items-center text-center space-y-2 mb-8">
                                    <p className="text-xs font-mono uppercase tracking-widest text-foreground/40">CIO Judgment</p>
                                    <h2 className={cn("text-6xl font-black tracking-tighter", getDecisionColor(state.final_decision.decision))}>
                                        {state.final_decision.decision}
                                    </h2>
                                    <div className="inline-flex items-center gap-1 mt-2 text-sm font-medium">
                                        <Target size={14} className="text-foreground/50" />
                                        <span>Confidence Score: {state.final_decision.confidence_score.toFixed(1)}/10</span>
                                    </div>
                                </div>

                                <div className="space-y-6">
                                    <div>
                                        <h4 className="text-sm font-semibold flex items-center gap-2 mb-2 text-foreground/80">
                                            <BookOpen size={16} /> Investment Thesis
                                        </h4>
                                        <p className="text-sm text-foreground/70 leading-relaxed bg-black/20 p-4 rounded-lg border border-white/5">
                                            {state.final_decision.investment_thesis}
                                        </p>
                                    </div>

                                    {state.final_decision.key_risks && state.final_decision.key_risks.length > 0 && (
                                        <div>
                                            <h4 className="text-sm font-semibold flex items-center gap-2 mb-2 text-danger/80">
                                                <TrendingDown size={16} /> Critical Drawdowns
                                            </h4>
                                            <ul className="space-y-2">
                                                {state.final_decision.key_risks.map((risk, i) => (
                                                    <li key={i} className="text-xs text-foreground/60 flex items-start gap-2">
                                                        <span className="text-danger font-bold mt-0.5">•</span>
                                                        <span>{risk}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}
                                </div>
                            </motion.div>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
