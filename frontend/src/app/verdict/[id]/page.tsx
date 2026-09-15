'use client';

import { use, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Lock } from 'lucide-react';
import { getApiUrl } from '@/config';
import { VerdictHero } from '@/components/analysis/VerdictHero';
import { ScoreBreakdown } from '@/components/analysis/ScoreBreakdown';
import { ComparisonRow } from '@/components/analysis/ComparisonRow';
import { AnalystCard } from '@/components/analysis/AnalystCard';
import { CounterFactualPanel } from '@/components/analysis/CounterFactualPanel';
import { QualityPanel } from '@/components/analysis/QualityPanel';
import { RunStats } from '@/components/analysis/RunStats';
import { Disclaimer } from '@/components/analysis/Disclaimer';
import type {
    AgentReport, ExtendedRisk, FinalDecision, QualityMetrics,
    RelativeContext, RunTelemetry, Verdict,
} from '@/hooks/useAnalysis';

interface FrozenVerdictPayload {
    run_id: string;
    ticker: string;
    company_name: string;
    timestamp_ist?: string;
    duration_seconds?: number;
    risk_profile?: string;
    judge_report?: Record<string, unknown>;
    reports?: Record<string, AgentReport>;
    telemetry?: Record<string, unknown>;
    data_quality?: Record<string, unknown>;
    /** Same shape the SSE `complete` event carries, so this page hydrates the
     *  analytics panels through exactly the same path as a live run. Absent on
     *  run logs written before it was stored. */
    analytics?: {
        relative_context?: RelativeContext;
        quality_metrics?: QualityMetrics;
        extended_risk?: ExtendedRisk;
    };
}

const KEY_TO_NODE_MAP: Record<string, string> = {
    financial_report:        'financial_node',
    sentiment_report:        'sentiment_node',
    risk_report:             'risk_node',
    technical_report:        'technical_node',
    macro_governance_report: 'macro_governance_node',
};

const AGENT_NODES = [
    'financial_node', 'technical_node', 'risk_node', 'sentiment_node', 'macro_governance_node',
];

export default function FrozenVerdictPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = use(params);
    const [data, setData] = useState<FrozenVerdictPayload | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const url = `${getApiUrl()}/api/verdict/${encodeURIComponent(id)}`;
        fetch(url)
            .then(async (res) => {
                if (!res.ok) {
                    throw new Error(res.status === 404 ? 'Verdict not found' : `Server error (${res.status})`);
                }
                return res.json() as Promise<FrozenVerdictPayload>;
            })
            .then(setData)
            .catch((e) => setError((e as Error).message ?? 'Failed to load verdict'));
    }, [id]);

    if (error) {
        return (
            <ErrorPanel error={error} runId={id} />
        );
    }

    if (!data) {
        return (
            <div className="w-full max-w-2xl mx-auto pt-32 px-6">
                <div className="card-paper p-8">
                    <p className="heading-eyebrow mb-3">Loading frozen verdict</p>
                    <p className="text-small">Reading run {id}…</p>
                </div>
            </div>
        );
    }

    const judge = data.judge_report ?? {};
    const decision: FinalDecision = {
        decision: ((judge['final_decision'] as Verdict) ?? 'HOLD'),
        confidence_score: (judge['confidence_score'] as number) ?? 0,
        investment_thesis: (judge['investment_thesis'] as string) ?? '',
        key_risks: (judge['key_risks'] as string[]) ?? [],
        key_catalysts: (judge['key_catalysts'] as string[]) ?? [],
        target_price: (judge['target_price_inr'] as number | null) ?? null,
        stop_loss: (judge['stop_loss_inr'] as number | null) ?? null,
        risk_profile: (data.risk_profile as string) ?? null,
        grounded_targets: judge['grounded_targets'] as FinalDecision['grounded_targets'] ?? null,
        veto: judge['veto'] as FinalDecision['veto'] ?? null,
        dissent_summary: judge['dissent_summary'] as string ?? null,
        data_quality: judge['data_quality'] as FinalDecision['data_quality'] ?? null,
        stale_sources: judge['stale_sources'] as string[] ?? null,
        counter_factual: judge['counter_factual'] as FinalDecision['counter_factual'] ?? null,
    };

    // A shared permalink is the one view built for an audience, and it was the
    // one missing every analytic the live page shows.
    const analytics = data.analytics ?? {};

    // Re-key reports under the analyze-page node-name convention.
    const agents: Record<string, AgentReport | undefined> = {};
    for (const [k, rep] of Object.entries(data.reports ?? {})) {
        const node = KEY_TO_NODE_MAP[k] ?? k;
        agents[node] = rep;
    }

    const tsLine = data.timestamp_ist
        ? new Date(data.timestamp_ist).toLocaleString('en-IN', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        })
        : '';

    return (
        <div className="w-full min-h-screen">
            {/* Frozen banner */}
            <header className="sticky top-0 z-50 w-full bg-[#FAFAF7]/95 backdrop-blur border-b border-[#E5E3DB]">
                <div className="max-w-6xl mx-auto h-14 px-4 md:px-8 flex items-center justify-between">
                    <Link href="/" className="text-[#7A7F88] hover:text-[#1A1B1E] transition shrink-0" aria-label="Back to home">
                        <ArrowLeft size={16} />
                    </Link>
                    <div className="flex items-baseline gap-3 min-w-0">
                        <span className="font-serif text-[17px] font-semibold text-[#1A1B1E] truncate">
                            {data.company_name || data.ticker}
                        </span>
                        <span className="text-[10px] font-mono tracking-widest text-[#7A7F88] border border-[#E5E3DB] rounded px-1.5 py-0.5 shrink-0">
                            {data.ticker}
                        </span>
                    </div>
                    <span className="inline-flex items-center gap-1.5 text-[11px] text-[#A16207] font-mono shrink-0">
                        <Lock size={11} /> Frozen {tsLine}
                    </span>
                </div>
            </header>

            <div className="max-w-6xl mx-auto px-4 md:px-8 py-8 md:py-10 pb-20">
                <div className="mb-4 px-3 py-2 rounded-md border border-[#E8C56A] bg-[#FEF7E0] text-small text-[#7A1F1F]/80">
                    <span className="font-medium text-[#A16207]">Frozen view — </span>
                    this verdict was generated on {tsLine} and will not be re-run. To get the latest verdict,{' '}
                    <Link href={`/analyze/${encodeURIComponent(data.company_name || data.ticker)}`} className="underline text-[#1E40AF]">
                        run a fresh analysis
                    </Link>.
                </div>

                <VerdictHero decision={decision} agents={agents} status="complete" />
                <ComparisonRow agents={agents} relative={analytics.relative_context ?? null} />
                <ScoreBreakdown agents={agents} />
                <CounterFactualPanel counterFactual={decision.counter_factual} />

                <section className="mt-10">
                    <h2 className="heading-section mb-5">Analyst notes</h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {AGENT_NODES.map((node, i) => {
                            const r = agents[node];
                            return (
                                <AnalystCard
                                    key={node}
                                    index={i}
                                    report={{
                                        agent_name: r?.agent_name ?? node.replace('_node', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) + ' Analyst',
                                        status: r ? (r.degraded || r.status === 'error' ? 'error' : 'complete') : 'error',
                                        score: r?.score ?? null,
                                        signal_line: r?.signal_line,
                                        data_table: r?.data_table,
                                        key_findings: r?.key_findings,
                                        risk_flags: r?.risk_flags,
                                        summary: r?.summary,
                                        degraded: r?.degraded,
                                        error: r?.error ?? null,
                                    }}
                                />
                            );
                        })}
                    </div>
                </section>

                <QualityPanel
                    quality={analytics.quality_metrics ?? null}
                    extendedRisk={analytics.extended_risk ?? null}
                />

                <RunStats telemetry={(data.telemetry as RunTelemetry | undefined) ?? null} />

                <Disclaimer />
            </div>
        </div>
    );
}

function ErrorPanel({ error, runId }: { error: string; runId: string }) {
    return (
        <div className="w-full max-w-2xl mx-auto pt-32 px-6">
            <div className="card-paper p-8">
                <p className="heading-eyebrow mb-3">Verdict unavailable</p>
                <p className="text-body mb-4">{error}</p>
                <p className="text-micro mb-6">Run id: <code className="font-mono">{runId}</code></p>
                <Link href="/" className="inline-block text-[12px] font-medium text-[#1E40AF] underline">Back to home</Link>
            </div>
        </div>
    );
}
