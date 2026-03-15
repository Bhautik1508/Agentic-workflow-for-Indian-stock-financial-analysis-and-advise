import { useState, useEffect, useCallback, useRef } from 'react';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────
export type AgentStatus = 'pending' | 'running' | 'complete' | 'error';

export interface AgentReport {
    agent_name: string;
    status: AgentStatus;
    summary: string;
    score: number;
    key_findings: string[];
    risk_flags: string[];
    signal_line: string;
    data_table: Array<{ label: string; value: string; signal: string }>;
    confidence: number;
    data: unknown;
}

export interface FinalDecision {
    decision: 'BUY' | 'HOLD' | 'SELL';
    confidence_score: number;
    investment_thesis: string;
    key_risks: string[];
}

export interface AnalysisState {
    status: 'idle' | 'initializing' | 'analyzing' | 'complete' | 'error';
    message: string;
    agents: Record<string, AgentReport>;
    final_decision: FinalDecision | null;
    run_id: string | null;
}

// ─────────────────────────────────────────────
// History types + localStorage helpers
// ─────────────────────────────────────────────
export interface HistoryItem {
    ticker: string;
    decision: 'BUY' | 'HOLD' | 'SELL' | null;
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
export function useAnalysis(ticker: string | null) {
    const [state, setState] = useState<AnalysisState>({
        status: 'idle',
        message: '',
        agents: {},
        final_decision: null,
        run_id: null,
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
        });

        const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === 'production' ? 'https://agentic-workflow-for-indian-stock.onrender.com' : 'http://127.0.0.1:8000');
        const eventSource = new EventSource(`${API_BASE_URL}/api/analyze/${encodeURIComponent(ticker)}`);

        // ── start ──────────────────────────────
        eventSource.addEventListener('start', (e) => {
            const data = JSON.parse((e as MessageEvent).data);
            setState((prev) => ({
                ...prev,
                status: 'analyzing',
                message: 'Analysis in progress...',
                run_id: data.run_id ?? null,
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
                    decision: nodeState.final_decision ?? 'HOLD',
                    confidence_score: nodeState.confidence_score ?? 0,
                    investment_thesis: nodeState.investment_thesis ?? '',
                    key_risks: nodeState.key_risks ?? [],
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

                // Hydrate from cached complete payload
                if (data.judge_report) {
                    fd = {
                        decision: data.judge_report.final_decision ?? 'HOLD',
                        confidence_score:
                            data.judge_report.confidence_score ??
                            (data.judge_report.confidence ?? 0) * 10,
                        investment_thesis:
                            data.judge_report.investment_thesis ??
                            data.judge_report.summary ??
                            '',
                        key_risks:
                            data.judge_report.key_risks ??
                            data.judge_report.risk_flags ??
                            [],
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
                    final_decision: fd,
                    agents,
                };
            });

            eventSource.close();
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
    }, [ticker]);

    // Persist to history once complete
    useEffect(() => {
        if (state.status === 'complete') {
            saveHistory(state.final_decision);
        }
    }, [state.status, state.final_decision, saveHistory]);

    return state;
}
