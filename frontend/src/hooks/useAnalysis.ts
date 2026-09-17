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
    /** The price the target and stop were computed against. Absent on runs
     *  cached before it was recorded. */
    current_price?: number | null;
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

/**
 * Verdict sensitivity: band thresholds, per-pillar fragility, veto triggers.
 *
 * Retained because the backend computes it and every run log carries it — the
 * backtest reads this shape. It is deliberately NOT rendered: the panel that
 * showed it led with a per-pillar table that was precise about something a
 * reader cannot observe (nobody watches a "Financial score"), and the section
 * as a whole asked more of a reader than it gave back. Removed on 2026-09-17.
 */
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

/** Stock vs an index over one window. `excess_pct` is the number that matters:
 *  it separates a company falling with its market from one falling on its own. */
export interface RelativeWindow {
    stock_pct: number | null;
    benchmark_pct?: number | null;
    sector_pct?: number | null;
    excess_pct: number | null;
}

export interface IndexSummary {
    symbol: string | null;
    last: number | null;
    change_pct_30d: number | null;
    change_pct_365d: number | null;
    pe: number | null;
    pb: number | null;
    dividend_yield: number | null;
}

export interface RelativeContext {
    vs_benchmark: Record<string, RelativeWindow>;
    benchmark_index: IndexSummary | Record<string, never>;
    sector_index_symbol: string | null;
    sector_index: IndexSummary | Record<string, never>;
    vs_sector: Record<string, RelativeWindow>;
    /** null when beta could not be measured — never computed against a fabricated 1.0. */
    alpha_1y_pct: number | null;
    volatility_regime: { india_vix: number | null; regime: string; note?: string };
}

export interface PiotroskiCriterion {
    name: string;
    /** null = not evaluable from the available statements, not "failed". */
    passed: boolean | null;
    detail: string;
}

export interface QualityMetrics {
    piotroski: {
        score: number | null;
        max_score: number;
        interpretation: string;
        criteria: PiotroskiCriterion[];
        unavailable: string[];
    };
    dupont: {
        roe: number | null;
        net_margin: number | null;
        asset_turnover: number | null;
        equity_multiplier: number | null;
        driver: string | null;
        reason?: string | null;
    };
    cash_quality: {
        cash_conversion: number | null;
        cash_conversion_3y_avg: number | null;
        accruals_ratio: number | null;
        flag: string | null;
        reason?: string | null;
    };
}

export interface ExtendedRisk {
    sortino_ratio: number | null;
    downside_deviation_pct: number | null;
    calmar_ratio: number | null;
    annual_return_pct: number | null;
    rolling_beta: {
        beta_1y: number | null;
        beta_2y: number | null;
        trend: string;
        note?: string;
    };
    week52_percentile: number | null;
    liquidity: {
        median_daily_value_cr: number | null;
        thin: boolean | null;
        tier: string;
        note?: string;
    };
    vwap_relative_pct: number | null;
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

/**
 * Why a run stopped.
 *
 * `message` says what is happening; this says why it isn't. They are kept
 * separate so the streaming status line and the failure panel can never
 * overwrite each other — which is exactly the bug that made every failure
 * read as a bare "Analysis Failed".
 *
 * The backend deliberately reports failures *through* the stream rather than
 * as an HTTP status, because EventSource cannot read the body of a non-200.
 * Keeping the whole payload (not just a string) is what makes the message
 * actionable: the rate-limit cooldown and the data-quality breakdown both
 * live here.
 */
export interface AnalysisError {
    detail: string;
    /** Rate limits are self-inflicted and self-resolving — worth saying plainly. */
    rateLimited: boolean;
    /** Seconds the caller must wait before a retry can succeed. */
    retryAfter: number | null;
    /** Set when the run aborted on a data-quality floor rather than a fault. */
    dataQuality: DataQuality | null;
}

export interface AnalysisState {
    status: 'idle' | 'initializing' | 'analyzing' | 'complete' | 'error';
    message: string;
    error: AnalysisError | null;
    agents: Record<string, AgentReport>;
    final_decision: FinalDecision | null;
    run_id: string | null;
    // Resolved exchange ticker (e.g. "RELIANCE.NS"). Populated once the
    // backend emits the `start` event.
    ticker: string | null;
    telemetry: RunTelemetry | null;
    /** When the verdict was actually produced (ISO). Null until a run completes,
     *  and null for cache entries written before this was recorded — which is
     *  shown as "no time" rather than as now. */
    generatedAt: string | null;
    /** True when this verdict was replayed from cache rather than computed. */
    cached: boolean;
    relative: RelativeContext | null;
    quality: QualityMetrics | null;
    extendedRisk: ExtendedRisk | null;
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
        error: null,
        agents: {},
        final_decision: null,
        run_id: null,
        ticker: null,
        telemetry: null,
        generatedAt: null,
        cached: false,
        relative: null,
        quality: null,
        extendedRisk: null,
    });

    const savedToHistory = useRef(false);

    // Bumping this re-enters the effect below, which tears down the old
    // EventSource and opens a fresh one. A full page reload would do the same
    // thing, but would also throw away the router state and the scroll
    // position for what is usually a transient upstream failure.
    const [retryNonce, setRetryNonce] = useState(0);
    const retry = useCallback(() => setRetryNonce((n) => n + 1), []);

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
            message: 'Connecting to the analysis engine\u2026',
            error: null,
            agents: {},
            final_decision: null,
            run_id: null,
            ticker: null,
            telemetry: null,
            generatedAt: null,
            cached: false,
            relative: null,
            quality: null,
            extendedRisk: null,
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
                cached: data.cached === true,
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
            const analytics: Partial<AnalysisState> = {};
            if (data.state?.relative_context) analytics.relative = data.state.relative_context;
            if (data.state?.quality_metrics) analytics.quality = data.state.quality_metrics;
            if (data.state?.extended_risk) analytics.extendedRisk = data.state.extended_risk;
            if (Object.keys(analytics).length > 0) {
                setState((prev) => ({ ...prev, ...analytics }));
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

                const cachedAnalytics = data.analytics ?? {};

                return {
                    ...prev,
                    relative: cachedAnalytics.relative_context ?? prev.relative,
                    quality: cachedAnalytics.quality_metrics ?? prev.quality,
                    extendedRisk: cachedAnalytics.extended_risk ?? prev.extendedRisk,
                    status: 'complete',
                    message: data.message ?? 'Analysis complete',
                    // The run's own completion time, not the browser's render
                    // time. A cache hit replays the original.
                    generatedAt: data.generated_at ?? prev.generatedAt,
                    cached: data.cached === true ? true : prev.cached,
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
            let err: AnalysisError = {
                detail: 'The analysis failed for an unknown reason.',
                rateLimited: false,
                retryAfter: null,
                dataQuality: null,
            };
            try {
                const msg = JSON.parse((e as MessageEvent).data);
                err = {
                    detail: msg.detail ?? err.detail,
                    rateLimited: msg.rate_limited === true,
                    retryAfter: typeof msg.retry_after === 'number' ? msg.retry_after : null,
                    dataQuality: msg.data_quality ?? null,
                };
            } catch { /* connection-level errors carry no payload */ }

            setState((prev) => ({ ...prev, status: 'error', message: err.detail, error: err }));
            eventSource.close();
        });

        // ── onerror (connection-level) ─────────
        eventSource.onerror = () => {
            setState((prev) => {
                if (prev.status === 'complete') return prev; // already done, ignore
                // A server-sent event named `error` dispatches an "error" event
                // at the EventSource, so this fires for those too — right after
                // the listener above, which has already recorded the real
                // reason. Without this guard the specific message ("rate
                // limited, wait 40s") is immediately overwritten by a generic
                // transport one, which is how every failure ended up looking
                // identical.
                if (prev.error) return prev;
                const detail = 'Lost the connection to the analysis engine.';
                return {
                    ...prev,
                    status: 'error',
                    message: detail,
                    error: { detail, rateLimited: false, retryAfter: null, dataQuality: null },
                };
            });
            eventSource.close();
        };

        return () => {
            eventSource.close();
        };
    }, [ticker, profile, retryNonce]);

    // Persist to history once complete
    useEffect(() => {
        if (state.status === 'complete') {
            saveHistory(state.final_decision);
        }
    }, [state.status, state.final_decision, saveHistory]);

    return { ...state, retry };
}
