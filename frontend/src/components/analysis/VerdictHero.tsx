'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, ArrowDown, Minus, ChevronsUp, ChevronsDown, AlertOctagon, Loader2, Database, Clock, RotateCw, Zap, ChevronDown } from 'lucide-react';
import type { AnalysisError, FinalDecision } from '@/hooks/useAnalysis';
import { inr } from '@/lib/format';
import { topStrengths, topRisks } from '@/lib/strengths';
import type { AgentReport } from '@/hooks/useAnalysis';

type Verdict = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL';

interface VerdictHeroProps {
    decision: FinalDecision | null;
    agents: Record<string, AgentReport | undefined>;
    status: string;
    /** Live narration of the run, straight from the backend's `status` events. */
    message?: string;
    /** Why the run stopped, when it did. */
    error?: AnalysisError | null;
    /** Re-opens the stream in place. Omitted on read-only views like /verdict. */
    onRetry?: () => void;
}

const VERDICT_CONFIG: Record<Verdict, {
    label: string;
    icon: typeof ArrowUp;
    fg: string;
    bg: string;
    border: string;
    dotBg: string;
}> = {
    STRONG_BUY: { label: 'Strong Buy', icon: ChevronsUp,   fg: 'text-strong-buy', bg: 'bg-strong-buy-soft', border: 'border-strong-buy-line', dotBg: 'bg-buy' },
    BUY:        { label: 'Buy',        icon: ArrowUp,      fg: 'text-buy', bg: 'bg-buy-soft', border: 'border-buy-line', dotBg: 'bg-buy' },
    HOLD:       { label: 'Hold',       icon: Minus,        fg: 'text-hold', bg: 'bg-hold-soft', border: 'border-hold-line', dotBg: 'bg-hold' },
    SELL:       { label: 'Sell',       icon: ArrowDown,    fg: 'text-sell', bg: 'bg-sell-soft', border: 'border-sell-line', dotBg: 'bg-sell' },
    STRONG_SELL:{ label: 'Strong Sell',icon: ChevronsDown, fg: 'text-strong-sell', bg: 'bg-strong-sell-soft', border: 'border-strong-sell-line', dotBg: 'bg-strong-sell' },
};

/**
 * The run in flight.
 *
 * A ~30-second wait with nothing but a shimmer reads as a hang. The backend
 * already narrates every stage of the pipeline over SSE, so the honest thing
 * is to show that narration rather than invent a progress bar we cannot
 * honour.
 */
function ProgressPanel({ message }: { message: string }) {
    return (
        <section className="card-paper px-6 py-8 md:px-10 md:py-10">
            <div className="flex items-center gap-3 mb-5">
                <Loader2 size={18} className="text-accent animate-spin" />
                <span className="heading-eyebrow">Verdict in progress</span>
            </div>

            <p
                role="status"
                aria-live="polite"
                aria-atomic="true"
                className="text-body text-ink-2 mb-6 min-h-[1.5em]"
            >
                {message}
            </p>

            <div className="space-y-3" aria-hidden="true">
                <div className="h-9 w-48 rounded skeleton-shimmer bg-paper-2" />
                <div className="h-4 w-3/4 rounded skeleton-shimmer bg-paper-2" />
                <div className="h-4 w-2/3 rounded skeleton-shimmer bg-paper-2" />
            </div>
        </section>
    );
}

/**
 * The run that stopped, and why.
 *
 * Every failure used to render as the words "Analysis Failed" over three
 * shimmer bars, while the reason — which the backend takes real trouble to
 * send through the stream — was parsed and dropped. A rate limit, a bad
 * ticker and a dead upstream all looked identical, and none of them looked
 * recoverable.
 */
function ErrorPanel({ error, onRetry }: { error: AnalysisError; onRetry?: () => void }) {
    // A retry inside the cooldown just fails again, so hold the button until
    // the window the server named has actually passed. Seeded from the prop and
    // never synced back to it — a fresh error remounts this component via its
    // key, which re-seeds the countdown without an effect.
    const [waitLeft, setWaitLeft] = useState(error.retryAfter ?? 0);

    useEffect(() => {
        if (waitLeft <= 0) return;
        const t = window.setTimeout(() => setWaitLeft((v) => v - 1), 1000);
        return () => window.clearTimeout(t);
    }, [waitLeft]);

    const held = waitLeft > 0;
    const missing = error.dataQuality?.missing_critical_fields ?? [];
    const sparse = error.dataQuality?.sparse_sources ?? [];

    return (
        <section className="card-paper px-6 py-8 md:px-10 md:py-10" role="alert">
            <div className="flex items-center gap-3 mb-4">
                <AlertOctagon size={18} className="text-sell" />
                <span className="heading-eyebrow">
                    {error.rateLimited ? 'Rate limited' : 'Analysis could not complete'}
                </span>
            </div>

            <p className="text-lede text-ink max-w-2xl mb-5">{error.detail}</p>

            {(missing.length > 0 || sparse.length > 0) && (
                <div className="mb-5 pt-4 border-t border-rule space-y-2">
                    {missing.length > 0 && (
                        <p className="text-small text-ink-2">
                            <span className="text-ink-3">Missing:</span> {missing.join(' \u00b7 ')}
                        </p>
                    )}
                    {sparse.length > 0 && (
                        <p className="text-small text-ink-2">
                            <span className="text-ink-3">Sparse sources:</span> {sparse.join(' \u00b7 ')}
                        </p>
                    )}
                </div>
            )}

            {onRetry && (
                <button
                    onClick={onRetry}
                    disabled={held}
                    className="inline-flex items-center gap-1.5 text-[13px] font-medium px-3 py-1.5 rounded-md border
                        border-accent bg-accent-tint text-accent transition cursor-pointer
                        hover:bg-accent-soft disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <RotateCw size={14} />
                    {held ? `Try again in ${humanWait(waitLeft)}` : 'Try again'}
                </button>
            )}

            {error.rateLimited && (
                <p className="text-micro mt-3 max-w-xl">
                    The limit is per-IP and guards a shared model quota. Nothing is wrong with
                    this stock or with the analysis.
                </p>
            )}
        </section>
    );
}

/** "Try again in 1739s" is not a readable cooldown. Seconds below a minute
 *  and a half, m/s above it. */
function humanWait(sec: number): string {
    if (sec < 90) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return rm ? `${h}h ${rm}m` : `${h}h`;
}

/** One labelled figure with a plain sentence saying what it means. */
function Fact({ label, value, note, tone }: {
    label: string; value: string; note?: string; tone?: 'good' | 'bad';
}) {
    const colour = tone === 'good' ? 'text-buy' : tone === 'bad' ? 'text-sell' : 'text-ink';
    return (
        <div className="min-w-0">
            <p className="heading-eyebrow text-[10px] mb-1">{label}</p>
            <p className={`font-serif text-[20px] leading-tight font-tnum ${colour}`}>{value}</p>
            {note && <p className="text-micro mt-1 leading-snug">{note}</p>}
        </div>
    );
}

const UNKNOWN_FAILURE: AnalysisError = {
    detail: 'The analysis stopped before producing a verdict.',
    rateLimited: false,
    retryAfter: null,
    dataQuality: null,
};

function HeroSkeleton({ status, message, error, onRetry }: {
    status: string;
    message?: string;
    error?: AnalysisError | null;
    onRetry?: () => void;
}) {
    if (status === 'error') {
        const err = error ?? UNKNOWN_FAILURE;
        // Keyed on the failure itself so a different error restarts the
        // cooldown from scratch rather than inheriting the previous count.
        return <ErrorPanel key={`${err.detail}|${err.retryAfter}`} error={err} onRetry={onRetry} />;
    }
    return <ProgressPanel message={message || 'Connecting to the analysis engine\u2026'} />;
}

export function VerdictHero({ decision, agents, status, message, error, onRetry }: VerdictHeroProps) {
    // Declared before the early return below — a hook after it would run
    // conditionally.
    const [showQuality, setShowQuality] = useState(false);

    if (!decision) {
        return <HeroSkeleton status={status} message={message} error={error} onRetry={onRetry} />;
    }

    const cfg = VERDICT_CONFIG[decision.decision] ?? VERDICT_CONFIG.HOLD;
    const VerdictIcon = cfg.icon;

    const confidenceRaw = decision.confidence_score ?? 0;
    const confidenceNorm = confidenceRaw > 1 ? confidenceRaw / 100 : confidenceRaw;
    const confidencePct = Math.round(confidenceNorm * 100);

    // `target` and `upside` are read but deliberately NOT displayed.
    //
    // The target is a mean of two anchors measured in different units: a
    // sector-median-multiple fair value (answering "is this expensive?") and a
    // technical resistance level (answering "where is the next ceiling?"). The
    // average of those is not a worse estimate of either — it is an estimate of
    // nothing, and for any premium-multiple stock it lands far below the market
    // price. Titan: (1,491 + 5,304) / 2 = 3,398 against a price of 4,909, while
    // the analyst consensus (5,422) and the model's own number (5,600) were
    // discarded by the blend.
    //
    // They are kept here only to derive `spot` on runs cached before the
    // backend sent it. Re-introduce the display when reconcile_targets stops
    // averaging incompatible anchors — not before.
    const target = decision.target_price ?? null;
    const stop = decision.stop_loss ?? null;
    const upside = decision.grounded_targets?.upside_pct ?? null;
    const downside = decision.grounded_targets?.downside_pct ?? null;
    const positionSize = decision.grounded_targets?.position_size_modifier ?? null;
    // The anchor every other figure is relative to. Sent by the backend now;
    // older cached runs predate it, so fall back to deriving it from the target
    // and its percentage rather than showing nothing.
    const spot = decision.grounded_targets?.current_price
        ?? (target != null && upside != null && upside !== -100
            ? target / (1 + upside / 100)
            : null);
    const horizonRaw = (decision as { time_horizon?: string }).time_horizon;
    const horizon = horizonRaw === 'short_term' ? 'short term'
                  : horizonRaw === 'medium_term' ? '6 months'
                  : horizonRaw === 'long_term' ? '12 months'
                  : null;

    const catalysts = (decision.key_catalysts ?? []).filter((c) => c && c.trim()).slice(0, 3);
    const dq = decision.data_quality ?? null;
    const dqMissing = dq?.missing_critical_fields ?? [];
    const dqSparse = dq?.sparse_sources ?? [];
    const dqWarnings = dq?.warnings ?? [];
    const dqHasDetail = dqMissing.length + dqSparse.length + dqWarnings.length > 0;

    const strengths = topStrengths(agents, 3);
    const risks = topRisks(agents, 3);

    return (
        <AnimatePresence>
            <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: 'easeOut' }}
                className="card-paper px-6 py-8 md:px-10 md:py-10"
            >
                {/* ── Veto banner ── */}
                {decision.veto?.triggered && (
                    <div className="mb-5 -mx-6 md:-mx-10 px-6 md:px-10 py-3 border-y border-sell-line bg-sell-soft flex items-start gap-2">
                        <AlertOctagon size={15} className="text-sell mt-0.5 shrink-0" />
                        <p className="text-small text-veto-ink">
                            <span className="font-semibold">Veto fired — </span>
                            {decision.veto.reasons.slice(0, 2).join(' · ')}
                        </p>
                    </div>
                )}

                {/* ── Verdict ── */}
                <div className="flex items-center gap-3 mb-5">
                    <span className={`w-2 h-2 rounded-full ${cfg.dotBg}`} />
                    <h1 className={`heading-display ${cfg.fg} flex items-center gap-2`}>
                        <VerdictIcon size={28} className="opacity-80" strokeWidth={2.5} />
                        {cfg.label}
                    </h1>
                </div>

                {/* ── The numbers, labelled and anchored ──
                    This was a run-on chip row: "to Rs841 -16.4% · Conviction 80% ·
                    Stop Rs967 -3.9% · Size 0.80x". Three problems. It never showed
                    what the stock costs today, so every percentage hung off an
                    invisible anchor. "Stop", "spot" and "conviction" are trade-desk
                    words. And "0.80x" gave no clue what it was 0.8 of. Each figure
                    now carries its own label and a plain sentence saying what it
                    means. */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-5 pb-6 mb-6 border-b border-rule">
                    {spot != null && (
                        <Fact
                            label="Trading now"
                            value={inr(spot)}
                            note="Today's market price. Everything here is measured from it."
                        />
                    )}
                    {stop != null && (
                        <Fact
                            label="Stop loss"
                            value={inr(stop)}
                            note={`Sell here to cap the loss${downside != null ? ` · ${downside.toFixed(1)}% below today` : ''}`}
                        />
                    )}
                    <Fact
                        label="Confidence"
                        value={`${confidencePct}%`}
                        note="How strongly the five analysts agreed with this call"
                    />
                    {positionSize != null && (
                        <Fact
                            label="Position size"
                            value={`${positionSize.toFixed(2)}×`}
                            note={
                                positionSize < 0.95
                                    ? "Smaller than a normal position — this stock moves a lot"
                                    : positionSize > 1.05
                                        ? 'Larger than a normal position — this stock is steady'
                                        : 'A normal-sized position for this profile'
                            }
                        />
                    )}
                </div>

                {/* ── Meta: profile, data completeness, staleness ── */}
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-small text-ink-2 mb-6">
                    {horizon && (
                        <span>
                            <span className="text-ink-3">Time horizon</span> {horizon}
                        </span>
                    )}
                    {decision.risk_profile && (
                        <span
                            className="px-1.5 py-0.5 rounded border border-rule bg-paper-2 text-[11px] font-mono uppercase tracking-wider text-ink-2"
                            title="The investor profile this run was weighted for"
                        >
                            {decision.risk_profile}
                        </span>
                    )}
                    {dq && (
                        <DataQualityChip
                            overall={dq.overall_completeness}
                            expandable={dqHasDetail}
                            expanded={showQuality}
                            onToggle={() => setShowQuality((v) => !v)}
                        />
                    )}
                    {decision.stale_sources?.slice(0, 2).map((s, i) => (
                        <span key={i} className="inline-flex items-center gap-1 text-[11px] text-hold" title="This source was older than the freshness window">
                            <Clock size={11} /> {s}
                        </span>
                    ))}
                </div>

                {/* ── What the completeness figure is actually missing ── */}
                {showQuality && dqHasDetail && (
                    <div className="-mt-3 mb-6 px-3 py-2.5 rounded-md border border-rule bg-paper-hover space-y-1.5">
                        {dqMissing.length > 0 && (
                            <p className="text-small text-ink-2">
                                <span className="text-ink-3">Missing:</span> {dqMissing.join(' · ')}
                            </p>
                        )}
                        {dqSparse.length > 0 && (
                            <p className="text-small text-ink-2">
                                <span className="text-ink-3">Sparse sources:</span> {dqSparse.join(' · ')}
                            </p>
                        )}
                        {dqWarnings.map((w, i) => (
                            <p key={i} className="text-small text-hold">{w}</p>
                        ))}
                    </div>
                )}

                {/* ── Thesis (editorial lede) ── */}
                {decision.investment_thesis && (
                    <p className="text-lede mb-7 max-w-3xl">
                        &ldquo;{decision.investment_thesis}&rdquo;
                    </p>
                )}

                {/* ── Strengths + Risks columns ── */}
                <div className={`grid grid-cols-1 md:grid-cols-2 ${catalysts.length > 0 ? 'lg:grid-cols-3' : ''} gap-x-10 gap-y-6 pt-6 border-t border-rule`}>
                    <div>
                        <h3 className="heading-eyebrow mb-1">Strengths</h3>
                        <p className="text-micro mb-3">The pillars that scored highest, out of 10</p>
                        {strengths.length === 0 ? (
                            <p className="text-small text-ink-3">No pillar above 6.0 yet.</p>
                        ) : (
                            <ul className="space-y-2">
                                {strengths.map((h, i) => (
                                    <li key={i} className="flex gap-3">
                                        <span className="font-tnum text-buy font-medium w-12 shrink-0">
                                            {h.score.toFixed(1)}<span className="text-ink-3 font-normal text-[11px]">/10</span>
                                        </span>
                                        <div className="min-w-0">
                                            <span className="text-small text-ink font-medium">{h.pillar}</span>
                                            <span className="text-small text-ink-2"> — {h.text}</span>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                    <div>
                        <h3 className="heading-eyebrow mb-1">Risks</h3>
                        <p className="text-micro mb-3">The pillars that scored lowest, or raised a flag</p>
                        {risks.length === 0 && (decision.key_risks?.length ?? 0) === 0 ? (
                            <p className="text-small text-ink-3">No flagged risks.</p>
                        ) : (
                            <ul className="space-y-2">
                                {risks.length > 0
                                    ? risks.map((h, i) => (
                                        <li key={i} className="flex gap-3">
                                            <span className="font-tnum text-sell font-medium w-12 shrink-0">
                                                {h.score.toFixed(1)}<span className="text-ink-3 font-normal text-[11px]">/10</span>
                                            </span>
                                            <div className="min-w-0">
                                                <span className="text-small text-ink font-medium">{h.pillar}</span>
                                                <span className="text-small text-ink-2"> — {h.text}</span>
                                            </div>
                                        </li>
                                    ))
                                    : decision.key_risks?.slice(0, 3).map((r, i) => (
                                        <li key={i} className="flex gap-3">
                                            <span className="text-sell w-3 shrink-0">·</span>
                                            <span className="text-small text-ink-2">{r}</span>
                                        </li>
                                    ))
                                }
                            </ul>
                        )}
                    </div>

                    {/* The forward half of the thesis. The judge produces these
                        and nothing rendered them. */}
                    {catalysts.length > 0 && (
                        <div>
                            <h3 className="heading-eyebrow mb-1">Catalysts</h3>
                            <p className="text-micro mb-3">What could move this in the thesis&rsquo;s favour</p>
                            <ul className="space-y-2">
                                {catalysts.map((c, i) => (
                                    <li key={i} className="flex gap-3">
                                        <Zap size={12} className="text-hold mt-1 shrink-0" />
                                        <span className="text-small text-ink-2">{c}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>

                {/* ── Dissent (small) ── */}
                {decision.dissent_summary && (
                    <div className="mt-6 pt-5 border-t border-rule">
                        <h4 className="heading-eyebrow mb-1">Dissent</h4>
                        <p className="text-micro mb-2">Where the analysts disagreed with the final call</p>
                        <p className="text-small text-ink-2 italic">{decision.dissent_summary}</p>
                    </div>
                )}
            </motion.section>
        </AnimatePresence>
    );
}

/**
 * Completeness, and — when there is something behind it — what is missing.
 *
 * A bare "Data 62%" invites the question "which 62%?" and then refuses to
 * answer it, while the backend has been sending the list of missing fields all
 * along. A number that cannot be interrogated is worse than no number.
 */
function DataQualityChip({ overall, expandable, expanded, onToggle }: {
    overall: number;
    expandable?: boolean;
    expanded?: boolean;
    onToggle?: () => void;
}) {
    const p = Math.round((overall ?? 0) * 100);
    const tone = p >= 85 ? 'text-buy'
              : p >= 70 ? 'text-hold'
              : 'text-sell';
    const body = <><Database size={11} /> Data {p}%</>;

    if (!expandable) {
        return <span className={`inline-flex items-center gap-1 text-[11px] ${tone}`}>{body}</span>;
    }
    return (
        <button
            onClick={onToggle}
            aria-expanded={expanded}
            title={expanded ? 'Hide what is missing' : 'Show what is missing'}
            className={`inline-flex items-center gap-1 text-[11px] cursor-pointer underline
                decoration-dotted underline-offset-2 hover:opacity-80 transition ${tone}`}
        >
            {body}
            <ChevronDown size={10} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </button>
    );
}
