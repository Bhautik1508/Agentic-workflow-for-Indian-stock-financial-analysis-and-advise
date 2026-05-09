'use client';

import { ArrowDown, ArrowUp, AlertCircle } from 'lucide-react';

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

export function CounterFactualPanel({ counterFactual: cf }: CounterFactualPanelProps) {
    if (!cf) return null;

    const hasDowngrade = cf.next_worse_band && cf.score_to_next_worse != null;
    const hasUpgrade = cf.next_better_band && cf.score_to_next_better != null;

    // Show only pillars with at least one direction of sensitivity
    const live = cf.pillar_sensitivity.filter(
        p => p.drop_to_downgrade != null || p.rise_to_upgrade != null
    );

    return (
        <section className="mt-8">
            <h2 className="heading-eyebrow mb-3">What would change this verdict?</h2>
            <div className="card-paper p-5 md:p-6">
                {/* Band thresholds line */}
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-small text-[#4A4D55] mb-5">
                    <span>
                        <span className="text-[#7A7F88]">Current</span>{' '}
                        <span className="font-tnum font-medium text-[#1A1B1E]">{cf.current_score.toFixed(2)}</span>{' '}
                        <span className="text-[#7A7F88]">→</span>{' '}
                        <span className="font-medium">{shortBand(cf.current_band)}</span>
                    </span>
                    {hasDowngrade && (
                        <span>
                            <span className="text-[#7A7F88]">Downgrade to</span>{' '}
                            <span className="font-medium text-[#B91C1C]">{shortBand(cf.next_worse_band)}</span>{' '}
                            <span className="text-[#7A7F88]">at</span>{' '}
                            <span className="font-tnum text-[#B91C1C]">&lt; {cf.score_to_next_worse?.toFixed(2)}</span>
                        </span>
                    )}
                    {hasUpgrade && (
                        <span>
                            <span className="text-[#7A7F88]">Upgrade to</span>{' '}
                            <span className="font-medium text-[#15803D]">{shortBand(cf.next_better_band)}</span>{' '}
                            <span className="text-[#7A7F88]">at</span>{' '}
                            <span className="font-tnum text-[#15803D]">≥ {cf.score_to_next_better?.toFixed(2)}</span>
                        </span>
                    )}
                </div>

                {/* Per-pillar sensitivity */}
                {live.length > 0 ? (
                    <ul className="divide-y divide-[#EFEDE5]">
                        {live.map((p) => (
                            <li key={p.pillar_key} className="py-2.5 grid grid-cols-12 gap-3 items-baseline">
                                <span className="col-span-3 md:col-span-2 text-small text-[#1A1B1E] font-medium">
                                    {p.pillar}
                                </span>
                                <span className="col-span-2 md:col-span-2 text-small font-tnum text-[#4A4D55]">
                                    {p.current_score.toFixed(1)}
                                </span>
                                {p.drop_to_downgrade != null && p.score_at_downgrade != null ? (
                                    <span className="col-span-7 md:col-span-4 text-small text-[#4A4D55]">
                                        <ArrowDown size={11} className="inline text-[#B91C1C] mr-1" />
                                        Drops to <span className="font-tnum text-[#B91C1C]">{p.score_at_downgrade.toFixed(1)}</span>
                                        {' '}
                                        <span className="text-[#7A7F88]">(−{p.drop_to_downgrade.toFixed(1)} pts)</span>
                                    </span>
                                ) : (
                                    <span className="col-span-7 md:col-span-4 text-micro text-[#B6B8B8]">
                                        Cannot downgrade alone
                                    </span>
                                )}
                                {p.rise_to_upgrade != null && p.score_at_upgrade != null ? (
                                    <span className="col-span-12 md:col-span-4 text-small text-[#4A4D55]">
                                        <ArrowUp size={11} className="inline text-[#15803D] mr-1" />
                                        Rises to <span className="font-tnum text-[#15803D]">{p.score_at_upgrade.toFixed(1)}</span>
                                        {' '}
                                        <span className="text-[#7A7F88]">(+{p.rise_to_upgrade.toFixed(1)} pts)</span>
                                    </span>
                                ) : (
                                    <span className="hidden md:inline col-span-4 text-micro text-[#B6B8B8]">
                                        Cannot upgrade alone
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-small text-[#7A7F88]">No pillar sensitivities to surface.</p>
                )}

                {/* Veto risks */}
                {cf.veto_risks.length > 0 && (
                    <div className="mt-5 pt-4 border-t border-[#EFEDE5]">
                        <h3 className="heading-eyebrow mb-2">Structural triggers (override score)</h3>
                        <ul className="space-y-1.5">
                            {cf.veto_risks.map((r, i) => (
                                <li key={i} className="text-small text-[#4A4D55] flex gap-2 items-start">
                                    <AlertCircle size={12} className="text-[#A16207] mt-0.5 shrink-0" />
                                    <span>{r}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                <p className="text-micro mt-4">
                    Each pillar&rsquo;s sensitivity assumes the others stay constant.
                </p>
            </div>
        </section>
    );
}
