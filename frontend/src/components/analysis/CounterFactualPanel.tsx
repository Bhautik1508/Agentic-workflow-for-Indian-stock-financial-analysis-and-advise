'use client';

import { useState } from 'react';
import { ArrowDown, ArrowUp, AlertCircle, ChevronDown } from 'lucide-react';

interface PillarSensitivity {
    pillar:                 string;
    pillar_key:             string;
    current_score:          number;
    weight:                 number;
    score_at_downgrade:     number | null;
    drop_to_downgrade:      number | null;
    score_at_upgrade:       number | null;
    rise_to_upgrade:        number | null;
}

interface CounterFactual {
    current_band:           string;
    current_score:          number;
    next_worse_band:        string | null;
    next_better_band:       string | null;
    score_to_next_worse:    number | null;
    score_to_next_better:   number | null;
    pillar_sensitivity:     PillarSensitivity[];
    veto_risks:             string[];
    notes:                  string[];
}

interface CounterFactualPanelProps {
    counterFactual: CounterFactual | null | undefined;
}

function shortBand(b: string | null): string {
    if (!b) return '—';
    return b.replace('_', ' ');
}

/**
 * How close the verdict is to changing, and what would override it outright.
 *
 * The per-pillar table is deliberately collapsed. It is precise about
 * something a reader cannot observe — nobody watches a "Financial score", they
 * watch earnings and price — and at full width it read as four rows of
 * arithmetic, two of which usually say that nothing can happen. The two facts
 * worth leading with are the margin (how near the call is to flipping) and the
 * structural triggers, which are real-world conditions that override the score
 * entirely. The table stays available for anyone interrogating a verdict they
 * distrust.
 */
export function CounterFactualPanel({ counterFactual: cf }: CounterFactualPanelProps) {
    const [showPillars, setShowPillars] = useState(false);
    if (!cf) return null;

    const hasDowngrade = cf.next_worse_band && cf.score_to_next_worse != null;
    const hasUpgrade = cf.next_better_band && cf.score_to_next_better != null;

    // Pillars with at least one direction of sensitivity. The rest cannot move
    // the verdict alone, which is why they are absent — stated below rather
    // than left as a silent gap in the table.
    const live = cf.pillar_sensitivity.filter(
        p => p.drop_to_downgrade != null || p.rise_to_upgrade != null
    );
    const hiddenCount = cf.pillar_sensitivity.length - live.length;

    // The single fact most readers would extract from the whole table: which
    // pillar is nearest to breaking the verdict.
    const fragile = live
        .filter(p => p.drop_to_downgrade != null)
        .sort((a, b) => (a.drop_to_downgrade ?? 0) - (b.drop_to_downgrade ?? 0))[0];

    const buffer = hasDowngrade && cf.score_to_next_worse != null
        ? cf.current_score - cf.score_to_next_worse
        : null;

    return (
        <section className="mt-8">
            <h2 className="heading-eyebrow mb-3">What would change this verdict?</h2>
            <div className="card-paper p-5 md:p-6">
                {/* ── How close is the call ── */}
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-small text-ink-2">
                    <span>
                        <span className="text-ink-3">Current</span>{' '}
                        <span className="font-tnum font-medium text-ink">{cf.current_score.toFixed(2)}</span>{' '}
                        <span className="text-ink-3">→</span>{' '}
                        <span className="font-medium">{shortBand(cf.current_band)}</span>
                    </span>
                    {hasDowngrade && (
                        <span>
                            <span className="text-ink-3">Downgrade to</span>{' '}
                            <span className="font-medium text-sell">{shortBand(cf.next_worse_band)}</span>{' '}
                            <span className="text-ink-3">at</span>{' '}
                            <span className="font-tnum text-sell">&lt; {cf.score_to_next_worse?.toFixed(2)}</span>
                        </span>
                    )}
                    {hasUpgrade && (
                        <span>
                            <span className="text-ink-3">Upgrade to</span>{' '}
                            <span className="font-medium text-buy">{shortBand(cf.next_better_band)}</span>{' '}
                            <span className="text-ink-3">at</span>{' '}
                            <span className="font-tnum text-buy">≥ {cf.score_to_next_better?.toFixed(2)}</span>
                        </span>
                    )}
                </div>

                {buffer != null && (
                    <p className="text-small text-ink-2 mt-2">
                        <span className="text-ink-3">Margin</span>{' '}
                        <span className="font-tnum font-medium text-ink">{buffer.toFixed(2)}</span>{' '}
                        <span className="text-ink-3">
                            {buffer < 0.5 ? 'points — a marginal call' : 'points before the band changes'}
                        </span>
                    </p>
                )}

                {/* ── The one line the table was really for ── */}
                {fragile && fragile.drop_to_downgrade != null && (
                    <p className="text-small text-ink-2 mt-4 pt-4 border-t border-rule-soft">
                        <span className="text-ink-3">Most fragile pillar:</span>{' '}
                        <span className="font-medium text-ink">{fragile.pillar}</span>
                        {' — a '}
                        <span className="font-tnum text-sell">{fragile.drop_to_downgrade.toFixed(1)}-point</span>
                        {' fall would downgrade this to '}
                        <span className="font-medium">{shortBand(cf.next_worse_band)}</span>.
                    </p>
                )}

                {/* ── Full table, on request ── */}
                {live.length > 0 && (
                    <>
                        <button
                            onClick={() => setShowPillars(v => !v)}
                            aria-expanded={showPillars}
                            className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-accent
                                hover:opacity-80 transition cursor-pointer no-print"
                        >
                            {showPillars ? 'Hide' : 'Show'} per-pillar sensitivity
                            <ChevronDown size={13} className={`transition-transform ${showPillars ? 'rotate-180' : ''}`} />
                        </button>

                        {showPillars && (
                            <div className="mt-3">
                                <ul className="divide-y divide-rule-soft">
                                    {live.map((p) => (
                                        <li key={p.pillar_key} className="py-2.5 grid grid-cols-12 gap-3 items-baseline">
                                            <span className="col-span-3 md:col-span-2 text-small text-ink font-medium">
                                                {p.pillar}
                                            </span>
                                            <span className="col-span-2 md:col-span-2 text-small font-tnum text-ink-2">
                                                {p.current_score.toFixed(1)}
                                            </span>
                                            {p.drop_to_downgrade != null && p.score_at_downgrade != null ? (
                                                <span className="col-span-7 md:col-span-4 text-small text-ink-2">
                                                    <ArrowDown size={11} className="inline text-sell mr-1" />
                                                    Drops to <span className="font-tnum text-sell">{p.score_at_downgrade.toFixed(1)}</span>
                                                    {' '}
                                                    <span className="text-ink-3">(−{p.drop_to_downgrade.toFixed(1)} pts)</span>
                                                </span>
                                            ) : (
                                                <span className="col-span-7 md:col-span-4 text-micro text-ink-4">
                                                    Cannot downgrade alone
                                                </span>
                                            )}
                                            {p.rise_to_upgrade != null && p.score_at_upgrade != null ? (
                                                <span className="col-span-12 md:col-span-4 text-small text-ink-2">
                                                    <ArrowUp size={11} className="inline text-buy mr-1" />
                                                    Rises to <span className="font-tnum text-buy">{p.score_at_upgrade.toFixed(1)}</span>
                                                    {' '}
                                                    <span className="text-ink-3">(+{p.rise_to_upgrade.toFixed(1)} pts)</span>
                                                </span>
                                            ) : (
                                                <span className="hidden md:inline col-span-4 text-micro text-ink-4">
                                                    Cannot upgrade alone
                                                </span>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                                <p className="text-micro mt-3">
                                    Each pillar&rsquo;s sensitivity assumes the others stay constant.
                                    {hiddenCount > 0 && ` ${hiddenCount} pillar${hiddenCount > 1 ? 's are' : ' is'} not listed: neither direction can change the verdict alone.`}
                                </p>
                            </div>
                        )}
                    </>
                )}

                {/* ── Structural triggers: observable, and they override the score ── */}
                {cf.veto_risks.length > 0 && (
                    <div className="mt-5 pt-4 border-t border-rule-soft">
                        <h3 className="heading-eyebrow mb-2">Structural triggers (override score)</h3>
                        <ul className="space-y-1.5">
                            {cf.veto_risks.map((r, i) => (
                                <li key={i} className="text-small text-ink-2 flex gap-2 items-start">
                                    <AlertCircle size={12} className="text-hold mt-0.5 shrink-0" />
                                    <span>{r}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </section>
    );
}
