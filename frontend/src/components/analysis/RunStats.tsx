'use client';

import type { RunTelemetry } from '@/hooks/useAnalysis';

interface RunStatsProps {
    telemetry: RunTelemetry | null;
}

function formatCost(t: RunTelemetry): string {
    // A missing price is shown as "not set", never as $0.00 — a fabricated
    // zero reads as "this run was free", which is worse than saying nothing.
    if (!t.pricing_configured || t.estimated_cost_usd === null) return 'not set';
    const usd = t.estimated_cost_usd;
    if (usd < 0.01) return `$${usd.toFixed(4)}`;
    return `$${usd.toFixed(3)}`;
}

function formatProviders(t: RunTelemetry): { label: string; warn: boolean } {
    const served = Object.entries(t.by_provider)
        .filter(([, v]) => v.successes > 0)
        .map(([name]) => name);
    if (served.length === 0) return { label: '—', warn: false };
    // More than one provider answering means the primary tier was failing over
    // mid-run; worth surfacing rather than hiding behind a green tick.
    return { label: served.join(' → '), warn: served.length > 1 };
}

/**
 * Compact strip: what the run cost, how slow it was, and which provider
 * actually answered. The last one matters most — a run silently served by the
 * fallback tier looks identical to a healthy one without it.
 */
export function RunStats({ telemetry }: RunStatsProps) {
    if (!telemetry || telemetry.total_calls === 0) return null;

    const providers = formatProviders(telemetry);
    const p50 = (telemetry.latency?.overall?.p50 ?? 0) / 1000;
    const p95 = (telemetry.latency?.overall?.p95 ?? 0) / 1000;
    const degraded = telemetry.failed_calls > 0 || telemetry.fallback_calls > 0;

    const items: { label: string; value: string; tone?: string; title?: string }[] = [
        {
            label: 'Model cost',
            value: formatCost(telemetry),
            tone: telemetry.pricing_configured ? undefined : 'text-[var(--color-ink-3)]',
            title: telemetry.pricing_configured
                ? `${telemetry.total_tokens.toLocaleString()} tokens across ${telemetry.total_calls} calls`
                : 'Set LLM_PRICING_JSON to report run cost',
        },
        {
            label: 'Tokens',
            value: telemetry.total_tokens.toLocaleString(),
            title: `${telemetry.total_calls} LLM calls`,
        },
        {
            label: 'Latency p50 / p95',
            value: `${p50.toFixed(1)}s / ${p95.toFixed(1)}s`,
            title: 'Per LLM call, not end-to-end',
        },
        {
            label: 'Served by',
            value: providers.label,
            tone: providers.warn ? 'text-warn' : undefined,
            title: providers.warn
                ? 'More than one provider answered — the primary tier was failing over'
                : 'Primary provider served every call',
        },
    ];

    return (
        <section className="mt-6 no-print" aria-label="Run diagnostics">
            <div className="card-paper flex flex-wrap items-center gap-x-8 gap-y-3 px-4 py-3">
                {items.map((item) => (
                    <div key={item.label} className="flex flex-col" title={item.title}>
                        <p className="heading-eyebrow text-[10px] mb-1">{item.label}</p>
                        <p className={`text-[14px] font-medium tabular-nums ${item.tone ?? ''}`}>
                            {item.value}
                        </p>
                    </div>
                ))}

                {degraded && (
                    <div
                        className="flex flex-col"
                        title={`${telemetry.failed_calls} failed, ${telemetry.fallback_calls} answered by a fallback model`}
                    >
                        <p className="heading-eyebrow text-[10px] mb-1">Retries</p>
                        <p className="text-[14px] font-medium tabular-nums text-warn">
                            {telemetry.failed_calls} failed · {telemetry.fallback_calls} fell back
                        </p>
                    </div>
                )}
            </div>
        </section>
    );
}
