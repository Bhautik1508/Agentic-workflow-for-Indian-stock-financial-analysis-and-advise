// Pure logic for picking the top strengths and risks displayed in the verdict
// hero. The hero shows max 3 of each, ordered by signal strength (the
// strongest pillar leads "Strengths"; the weakest pillar leads "Risks").
//
// We declare a minimal `AgentReportLike` so this file has no path-alias imports
// — keeps unit tests runnable under plain `node --test`.

export interface AgentReportLike {
    score:         number | null;
    signal_line?:  string;
    key_findings?: string[];
    risk_flags?:   string[];
    status?:       string;
    degraded?:     boolean;
}

export interface Pillar {
    node:  string;       // e.g. "financial_node"
    label: string;       // e.g. "Financial"
    score: number;       // 0..10
    signal_line?: string;
    key_findings?: string[];
    risk_flags?: string[];
}

export const PILLAR_ORDER: { node: string; label: string }[] = [
    { node: 'financial_node',         label: 'Financial' },
    { node: 'technical_node',         label: 'Technical' },
    { node: 'risk_node',              label: 'Risk' },
    { node: 'sentiment_node',         label: 'Sentiment' },
    { node: 'macro_governance_node',  label: 'Macro & Gov' },
];

export function livePillars(agents: Record<string, AgentReportLike | undefined>): Pillar[] {
    const out: Pillar[] = [];
    for (const { node, label } of PILLAR_ORDER) {
        const r = agents[node];
        if (!r) continue;
        if (r.score === null || r.score === undefined) continue; // degraded
        out.push({
            node,
            label,
            score:         r.score as number,
            signal_line:   r.signal_line,
            key_findings:  r.key_findings ?? [],
            risk_flags:    r.risk_flags ?? [],
        });
    }
    return out;
}

export interface Highlight {
    pillar: string;       // "Financial"
    score:  number;
    text:   string;       // human-readable line for the hero
}

/** Top strengths: highest-scoring pillars first; pull a finding line from each. */
export function topStrengths(agents: Record<string, AgentReportLike | undefined>, limit = 3): Highlight[] {
    return livePillars(agents)
        .filter(p => p.score >= 6)
        .sort((a, b) => b.score - a.score)
        .slice(0, limit)
        .map(p => ({
            pillar: p.label,
            score:  p.score,
            text:   firstNonEmpty(p.signal_line, p.key_findings?.[0], `${p.label} score ${p.score.toFixed(1)}`),
        }));
}

/** Top risks: lowest-scoring pillars first, plus any pillar with explicit risk_flags. */
export function topRisks(agents: Record<string, AgentReportLike | undefined>, limit = 3): Highlight[] {
    const live = livePillars(agents);

    // Bucket A — pillars below 5 (weakest first)
    const weakPillars = live.filter(p => p.score < 5).sort((a, b) => a.score - b.score);

    // Bucket B — pillars with explicit risk_flags but above 5 (still call them out)
    const flagPillars = live
        .filter(p => p.score >= 5 && (p.risk_flags?.length ?? 0) > 0)
        .sort((a, b) => a.score - b.score);

    const ordered = [...weakPillars, ...flagPillars];
    const seen = new Set<string>();
    const out: Highlight[] = [];

    for (const p of ordered) {
        if (out.length >= limit) break;
        if (seen.has(p.label)) continue;
        seen.add(p.label);
        out.push({
            pillar: p.label,
            score:  p.score,
            text:   firstNonEmpty(p.risk_flags?.[0], p.signal_line, `${p.label} score ${p.score.toFixed(1)}`),
        });
    }
    return out;
}

function firstNonEmpty(...candidates: Array<string | undefined>): string {
    for (const c of candidates) {
        if (c && c.trim()) return c.trim();
    }
    return '—';
}
