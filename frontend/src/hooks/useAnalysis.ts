import { useState, useEffect, useCallback, useRef } from 'react';
import { getApiUrl } from '@/config';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────
export type AgentStatus = 'pending' | 'running' | 'complete' | 'error';

export type Verdict = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL';

export interface AgentReport {
    agent_name: string;
    status: AgentStatus;
    summary: string;
    score: number | null;          // null when the agent is degraded
    key_findings: string[];
    risk_flags: string[];
    signal_line: string;
    data_table: Array<{ label: string; value: string; signal: string }>;
    confidence: number;            // 0..1
    data: unknown;
    degraded?: boolean;
    error?: string | null;
}

export type RiskProfile = 'conservative' | 'balanced' | 'aggressive';

export interface GroundedTargets {
    target_price: number | null;
    stop_loss: number | null;
    position_size_modifier: number;
    upside_pct: number | null;
    downside_pct: number | null;
    reward_to_risk: number | null;
    method: string;
    components: Record<string, number | null>;
}

export interface VetoInfo {
    triggered: boolean;
    forced_verdict: Verdict | null;
    forced_confidence: number | null;
    reasons: string[];
}

export interface DataQuality {
    fundamental_completeness: number;
    price_completeness: number;
    overall_completeness: number;
    missing_critical_fields: string[];
    sparse_sources: string[];
    abort: boolean;
    abort_reason?: string | null;
    warnings: string[];
}

export interface PillarSensitivity {
    pillar: string;
    pillar_key: string;
    current_score: number;
    weight: number;
    score_at_downgrade: number | null;
    drop_to_downgrade: number | null;
    score_at_upgrade: number | null;
    rise_to_upgrade: number | null;
}

export interface CounterFactual {
    current_band: string;
    current_score: number;
    next_worse_band: string | null;
    next_better_band: string | null;
    score_to_next_worse: number | null;
    score_to_next_better: number | null;
    pillar_sensitivity: PillarSensitivity[];
    veto_risks: string[];
    notes: string[];
}

export interface FinalDecision {
    decision: Verdict;
    confidence_score: number;      // 0..1 on the wire; UI renders as percent
    investment_thesis: string;
    key_risks: string[];
    key_catalysts?: string[];
    target_price?: number | null;
    stop_loss?: number | null;
    risk_profile?: RiskProfile | string | null;
    grounded_targets?: GroundedTargets | null;
    veto?: VetoInfo | null;
    dissent_summary?: string | null;
    // Phase 3
    data_quality?: DataQuality | null;
    stale_sources?: string[] | null;
    // Phase 5
    counter_factual?: CounterFactual | null;
}

/** Per-run LLM telemetry, emitted by the backend's `telemetry` SSE event. */
export interface RunTelemetry {
    total_calls: number;
    total_tokens: number;
    fallback_calls: number;
    failed_calls: number;
    /** null when no model in the chain has a configured price. */
    estimated_cost_usd: number | null;
    pricing_configured: boolean;
    unpriced_calls: number;
    primary_success_rate: number | null;
    by_provider: Record<string, {
        calls: number; successes: number; failures: number;
        tokens: number; duration_ms: number; cost_usd?: number;
    }>;
    latency: {
        overall: { p50: number; p95: number; max: number };
        by_agent: Record<string, { p50: number; p95: number; max: number; calls: number }>;
    };
}

export interface AnalysisState {
    status: 'idle' | 'initializing' | 'analyzing' | 'complete' | 'error';
    message: string;
    agents: Record<string, AgentReport>;
    final_decision: FinalDecision | null;
    run_id: string | null;
    // Resolved exchange ticker (e.g. "RELIANCE.NS"). Populated once the
    // backend emits the `start` event.
    ticker: string | null;
    telemetry: RunTelemetry | null;
}

// ─────────────────────────────────────────────
// History types + localStorage helpers
// ─────────────────────────────────────────────
export interface HistoryItem {
    ticker: string;
    decision: Verdict | null;
    confidence_score: number | null;
    timestamp: string; // ISO string
}

const HISTORY_KEY = 'stocksage_history';
const MAX_HISTORY = 10;

export function loadHistory(): HistoryItem[] {
    if (typeof window === 'undefined') return [];
    try {
        const raw = localStorage.getItem(HISTORY_KEY);
        return raw ? (JSON.parse(raw) as HistoryItem[]) : [];
    } catch {
        return [];
    }
}

export function saveToHistory(item: HistoryItem): void {
    if (typeof window === 'undefined') return;
    try {
        const current = loadHistory();
        // Remove duplicate for same ticker
        const filtered = current.filter((h) => h.ticker !== item.ticker);
        // Prepend new item, cap at MAX_HISTORY
        const updated = [item, ...filtered].slice(0, MAX_HISTORY);
        localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
    } catch {
        // ignore storage errors
    }
}

// ─────────────────────────────────────────────
// Key mapping
// ─────────────────────────────────────────────
const KEY_TO_NODE_MAP: Record<string, string> = {
    financial_report: 'financial_node',
    sentiment_report: 'sentiment_node',
    risk_report: 'risk_node',
    technical_report: 'technical_node',
    macro_governance_report: 'macro_governance_node',
};

// ─────────────────────────────────────────────
// Main hook
// ─────────────────────────────────────────────
export function useAnalysis(ticker: string | null, profile: RiskProfile = 'balanced') {
    const [state, setState] = useState<AnalysisState>({
        status: 'idle',
        message: '',
        agents: {},
        final_decision: null,
        run_id: null,
        ticker: null,
    telemetry: null,
    });

    const savedToHistory = useRef(false);

    const saveHistory = useCallback(
        (decision: FinalDecision | null) => {
            if (!ticker || savedToHistory.current) return;
            savedToHistory.current = true;
            saveToHistory({
                ticker,
                decision: decision?.decision ?? null,
                confidence_score: decision?.confidence_score ?? null,
                timestamp: new Date().toISOString(),
            });
        },
        [ticker]
    );

    useEffect(() => {
        if (!ticker) return;

        savedToHistory.current = false;

        setState({
            status: 'initializing',
            message: 'Connecting to analysis engine...',
            agents: {},
            final_decision: null,
            run_id: null,
            ticker: null,
    telemetry: null,
        });

        const API_BASE_URL = getApiUrl();
        const eventSource = new EventSource(
            `${API_BASE_URL}/api/analyze/${encodeURIComponent(ticker)}?profile=${encodeURIComponent(profile)}`
        );

        // ── start ──────────────────────────────
        eventSource.addEventListener('start', (e) => {
            const data = JSON.parse((e as MessageEvent).data);
            setState((prev) => ({
                ...prev,
                status: 'analyzing',
                message: 'Analysis in progress...',
                run_id: data.run_id ?? null,
                ticker: data.ticker ?? prev.ticker,
            }));
        });

        // ── status ─────────────────────────────
        eventSource.addEventListener('status', (e) => {
            const data = JSON.parse((e as MessageEvent).data);
            setState((prev) => ({ ...prev, message: data.message ?? prev.message }));
        });

        // ── node_update ────────────────────────
        eventSource.addEventListener('node_update', (e) => {
            const data = JSON.parse((e as MessageEvent).data);
            const nodeState = data.state;

            if (!nodeState || typeof nodeState !== 'object') return;

            // Judge node → final decision
            if (data.node === 'judge_node') {
                const fd: FinalDecision = {
                    decision: (nodeState.final_decision ?? 'HOLD') as Verdict,
                    confidence_score: nodeState.confidence_score ?? 0,
                    investment_thesis: nodeState.investment_thesis ?? '',
                    key_risks: nodeState.key_risks ?? [],
                    key_catalysts: nodeState.key_catalysts ?? [],
                    target_price: nodeState.target_price_inr ?? null,
                    stop_loss: nodeState.stop_loss_inr ?? null,
                    risk_profile: nodeState.risk_profile ?? null,
                    grounded_targets: nodeState.grounded_targets ?? null,
                    veto: nodeState.veto ?? null,
                    dissent_summary: nodeState.dissent_summary ?? null,
                    data_quality: nodeState.data_quality ?? null,
                    stale_sources: nodeState.stale_sources ?? null,
                    counter_factual: nodeState.counter_factual ?? null,
                };
                setState((prev) => ({ ...prev, final_decision: fd }));
                return;
            }

            // Agent nodes → accumulate reports
            const newAgents: Record<string, AgentReport> = {};
            for (const [key, reportData] of Object.entries(nodeState)) {
                if (key.endsWith('_report') && reportData) {
                    const mapped = KEY_TO_NODE_MAP[key] ?? key;
                    newAgents[mapped] = reportData as AgentReport;
                }
            }
            if (Object.keys(newAgents).length > 0) {
                setState((prev) => ({
                    ...prev,
                    agents: { ...prev.agents, ...newAgents },
                }));
            }
        });

        // ── complete ───────────────────────────
        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse((e as MessageEvent).data);

            setState((prev) => {
                let fd = prev.final_decision;

                // Hydrate from cached complete payload (canonical wire format = confidence in [0,1])
                if (data.judge_report) {
                    fd = {
                        decision: (data.judge_report.final_decision ?? 'HOLD') as Verdict,
                        confidence_score:
                            data.judge_report.confidence_score ??
                            data.judge_report.confidence ??
                            0,
                        investment_thesis:
                            data.judge_report.investment_thesis ??
                            data.judge_report.summary ??
                            '',
                        key_risks:
                            data.judge_report.key_risks ??
                            data.judge_report.risk_flags ??
                            [],
                        key_catalysts: data.judge_report.key_catalysts ?? [],
                        target_price: data.judge_report.target_price_inr ?? data.judge_report.target_price ?? null,
                        stop_loss: data.judge_report.stop_loss_inr ?? data.judge_report.stop_loss ?? null,
                        risk_profile: data.judge_report.risk_profile ?? null,
                        grounded_targets: data.judge_report.grounded_targets ?? null,
                        veto: data.judge_report.veto ?? null,
                        dissent_summary: data.judge_report.dissent_summary ?? null,
                        data_quality: data.judge_report.data_quality ?? data.data_quality ?? null,
                        stale_sources: data.judge_report.stale_sources ?? null,
                        counter_factual: data.judge_report.counter_factual ?? null,
                    };
                }

                // Hydrate agent cards from cached reports
                let agents = { ...prev.agents };
                if (data.reports) {
                    for (const [key, reportData] of Object.entries(data.reports)) {
                        if (key.endsWith('_report') && reportData) {
                            const mapped = KEY_TO_NODE_MAP[key] ?? key;
                            agents[mapped] = reportData as AgentReport;
                        }
                    }
                }

                return {
                    ...prev,
                    status: 'complete',
                    message: data.message ?? 'Analysis complete',
                    // Cache hits ship the original run_id so /verdict/{id} can find the run log.
                    run_id: data.run_id ?? prev.run_id,
                    ticker: data.ticker ?? prev.ticker,
                    final_decision: fd,
                    agents,
                };
            });

            eventSource.close();
        });

        // ── telemetry (cost / latency / which provider served) ──
        eventSource.addEventListener('telemetry', (e) => {
            try {
                const data = JSON.parse((e as MessageEvent).data) as RunTelemetry;
                setState((prev) => ({ ...prev, telemetry: data }));
            } catch { /* telemetry is informational; never break the run for it */ }
        });

        // ── error (named SSE event) ────────────
        eventSource.addEventListener('error', (e) => {
            let errorMessage = 'Analysis failed';
            try {
                const msg = JSON.parse((e as MessageEvent).data);
                errorMessage = msg.detail ?? errorMessage;
            } catch { /* no data on connection errors */ }

            setState((prev) => ({ ...prev, status: 'error', message: errorMessage }));
            eventSource.close();
        });

        // ── onerror (connection-level) ─────────
        eventSource.onerror = () => {
            setState((prev) => {
                if (prev.status === 'complete') return prev; // already done, ignore
                return { ...prev, status: 'error', message: 'SSE connection lost' };
            });
            eventSource.close();
        };

        return () => {
            eventSource.close();
        };
    }, [ticker, profile]);

    // Persist to history once complete
    useEffect(() => {
        if (state.status === 'complete') {
            saveHistory(state.final_decision);
        }
    }, [state.status, state.final_decision, saveHistory]);

    return state;
}
