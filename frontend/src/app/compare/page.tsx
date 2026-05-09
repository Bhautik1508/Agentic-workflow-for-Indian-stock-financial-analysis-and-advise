'use client';

import Link from 'next/link';
import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { useAnalysis, type RiskProfile, type AgentReport, type FinalDecision } from '@/hooks/useAnalysis';
import { score as fmtScore } from '@/lib/format';
import { PILLAR_ORDER } from '@/lib/strengths';

const PROFILE_OPTIONS: RiskProfile[] = ['conservative', 'balanced', 'aggressive'];

function PillarRow({ label, leftScore, rightScore }: { label: string; leftScore: number | null; rightScore: number | null }) {
    const delta = (leftScore !== null && rightScore !== null) ? leftScore - rightScore : null;
    const tone = delta == null ? 'text-[#7A7F88]'
              : delta > 0.5 ? 'text-[#15803D]'
              : delta < -0.5 ? 'text-[#B91C1C]'
              : 'text-[#7A7F88]';

    return (
        <div className="grid grid-cols-12 gap-2 items-baseline py-2.5 border-b border-[#EFEDE5]">
            <span className="col-span-4 md:col-span-3 text-small text-[#1A1B1E] font-medium">{label}</span>
            <span className="col-span-3 md:col-span-3 text-small font-tnum text-[#1A1B1E] text-right">{fmtScore(leftScore)}</span>
            <span className={`col-span-2 md:col-span-3 text-small font-tnum text-center ${tone}`}>
                {delta == null ? '—' : (delta >= 0 ? '+' : '') + delta.toFixed(1)}
            </span>
            <span className="col-span-3 md:col-span-3 text-small font-tnum text-[#1A1B1E] text-right">{fmtScore(rightScore)}</span>
        </div>
    );
}

function VerdictPill({ d }: { d: FinalDecision | null }) {
    if (!d) return <span className="text-small text-[#7A7F88]">Analysing…</span>;
    const tone = d.decision.includes('BUY') ? 'text-[#15803D] bg-[#ECFDF3]'
              : d.decision.includes('SELL') ? 'text-[#B91C1C] bg-[#FEE7E7]'
              : 'text-[#A16207] bg-[#FEF7E0]';
    const conf = Math.round(Math.max(0, Math.min(1, d.confidence_score ?? 0)) * 100);
    return (
        <div className="flex flex-col gap-1">
            <span className={`inline-block w-fit font-serif text-[20px] px-2 py-0.5 rounded ${tone}`}>
                {d.decision.replace('_', ' ')}
            </span>
            <span className="text-micro">{conf}% conviction</span>
        </div>
    );
}

function CompareInner() {
    const params = useSearchParams();
    const left = params.get('left') ?? '';
    const right = params.get('right') ?? '';
    const [profile, setProfile] = useState<RiskProfile>('balanced');

    const leftState = useAnalysis(left || null, profile);
    const rightState = useAnalysis(right || null, profile);

    if (!left || !right) {
        return (
            <div className="max-w-2xl mx-auto pt-32 px-6">
                <div className="card-paper p-8">
                    <h1 className="heading-section mb-3">Compare two stocks</h1>
                    <p className="text-body mb-5">
                        Open this page with both tickers in the URL — for example:
                    </p>
                    <code className="block text-small text-[#1E40AF] font-mono mb-4">
                        /compare?left=Reliance&amp;right=ONGC
                    </code>
                    <Link href="/" className="text-[12px] font-medium text-[#1E40AF] underline">Back to home</Link>
                </div>
            </div>
        );
    }

    const leftAgents: Record<string, AgentReport | undefined> = leftState.agents;
    const rightAgents: Record<string, AgentReport | undefined> = rightState.agents;

    return (
        <div className="w-full min-h-screen">
            <header className="sticky top-0 z-50 w-full bg-[#FAFAF7]/95 backdrop-blur border-b border-[#E5E3DB]">
                <div className="max-w-6xl mx-auto h-14 px-4 md:px-8 flex items-center justify-between gap-4">
                    <Link href="/" className="text-[#7A7F88] hover:text-[#1A1B1E] transition shrink-0" aria-label="Back to home">
                        <ArrowLeft size={16} />
                    </Link>
                    <span className="font-serif text-[16px] font-semibold text-[#1A1B1E]">Compare</span>
                    <div className="flex items-center gap-1">
                        {PROFILE_OPTIONS.map(p => (
                            <button
                                key={p}
                                onClick={() => setProfile(p)}
                                disabled={leftState.status === 'analyzing' || rightState.status === 'analyzing'}
                                className={`text-[11px] font-medium px-2 py-1 rounded border transition cursor-pointer
                                    ${profile === p
                                        ? 'border-[#1E40AF] bg-[#F0F4FB] text-[#1E40AF]'
                                        : 'border-[#E5E3DB] bg-white text-[#4A4D55]'}
                                    disabled:opacity-50 disabled:cursor-not-allowed`}
                            >
                                {p}
                            </button>
                        ))}
                    </div>
                </div>
            </header>

            <div className="max-w-6xl mx-auto px-4 md:px-8 py-8 md:py-10 pb-20">
                {/* Title row */}
                <div className="grid grid-cols-2 gap-6 mb-6">
                    <div className="card-paper px-5 py-4">
                        <p className="heading-eyebrow mb-1">Left</p>
                        <h2 className="font-serif text-[24px] font-semibold mb-2">{decodeURIComponent(left)}</h2>
                        <VerdictPill d={leftState.final_decision} />
                    </div>
                    <div className="card-paper px-5 py-4">
                        <p className="heading-eyebrow mb-1">Right</p>
                        <h2 className="font-serif text-[24px] font-semibold mb-2">{decodeURIComponent(right)}</h2>
                        <VerdictPill d={rightState.final_decision} />
                    </div>
                </div>

                {/* Pillar comparison table */}
                <section>
                    <h2 className="heading-eyebrow mb-3">Pillar by pillar</h2>
                    <div className="card-paper p-4 md:p-5">
                        <div className="grid grid-cols-12 gap-2 pb-2 border-b border-[#E5E3DB]">
                            <span className="col-span-4 md:col-span-3 heading-eyebrow">Pillar</span>
                            <span className="col-span-3 md:col-span-3 heading-eyebrow text-right truncate">
                                {decodeURIComponent(left)}
                            </span>
                            <span className="col-span-2 md:col-span-3 heading-eyebrow text-center">Δ</span>
                            <span className="col-span-3 md:col-span-3 heading-eyebrow text-right truncate">
                                {decodeURIComponent(right)}
                            </span>
                        </div>
                        {PILLAR_ORDER.map(({ node, label }) => (
                            <PillarRow
                                key={node}
                                label={label}
                                leftScore={leftAgents[node]?.score ?? null}
                                rightScore={rightAgents[node]?.score ?? null}
                            />
                        ))}
                    </div>
                </section>

                {/* Theses, side-by-side */}
                <section className="mt-8">
                    <h2 className="heading-eyebrow mb-3">Theses</h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="card-paper p-5">
                            <p className="text-lede text-[#1A1B1E]">
                                {leftState.final_decision?.investment_thesis || '—'}
                            </p>
                            <Link
                                href={`/analyze/${encodeURIComponent(left)}`}
                                className="mt-4 inline-flex items-center gap-1 text-[12px] font-medium text-[#1E40AF]"
                            >
                                Open full analysis <ArrowRight size={12} />
                            </Link>
                        </div>
                        <div className="card-paper p-5">
                            <p className="text-lede text-[#1A1B1E]">
                                {rightState.final_decision?.investment_thesis || '—'}
                            </p>
                            <Link
                                href={`/analyze/${encodeURIComponent(right)}`}
                                className="mt-4 inline-flex items-center gap-1 text-[12px] font-medium text-[#1E40AF]"
                            >
                                Open full analysis <ArrowRight size={12} />
                            </Link>
                        </div>
                    </div>
                </section>

                <p className="text-micro mt-10">
                    Both analyses run with profile <span className="font-medium">{profile}</span>.
                    Switch profile to see how weighting changes the deltas.
                </p>
            </div>
        </div>
    );
}

export default function ComparePage() {
    return (
        <Suspense fallback={<div className="pt-32 text-center text-small">Loading…</div>}>
            <CompareInner />
        </Suspense>
    );
}
