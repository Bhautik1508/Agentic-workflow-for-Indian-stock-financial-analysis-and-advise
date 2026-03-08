import { useState, useEffect } from 'react';

export type AgentStatus = 'pending' | 'running' | 'complete' | 'error';

export interface AgentReport {
    agent_name: string;
    status: AgentStatus;
    summary: string;
    score: number;
    key_findings: string[];
    risk_flags: string[];
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
}

export function useSSE(ticker: string | null) {
    const [state, setState] = useState<AnalysisState>({
        status: 'idle',
        message: '',
        agents: {},
        final_decision: null
    });

    useEffect(() => {
        if (!ticker) return;

        // Connect to FastAPI SSE endpoint
        const eventSource = new EventSource(`http://127.0.0.1:8000/api/analyze/${ticker}`);

        eventSource.addEventListener('start', (e) => {
            const data = JSON.parse(e.data);
            setState(prev => ({ ...prev, status: 'analyzing', message: `Initializing run: ${data.run_id}` }));
        });

        eventSource.addEventListener('status', (e) => {
            const data = JSON.parse(e.data);
            setState(prev => ({ ...prev, message: data.message }));
        });

        eventSource.addEventListener('node_update', (e) => {
            const data = JSON.parse(e.data);
            const nodeName = data.node;
            const nodeState = data.state;

            if (nodeState && typeof nodeState === 'object') {
                // Handle Judge node which outputs direct final decision
                if (nodeName === 'judge_node') {
                    setState(prev => ({
                        ...prev,
                        final_decision: {
                            decision: nodeState.final_decision,
                            confidence_score: nodeState.confidence_score,
                            investment_thesis: nodeState.investment_thesis,
                            key_risks: nodeState.key_risks
                        }
                    }));
                    return;
                }

                // Map backend state keys directly to the pseudo node names expected by the UI
                const KEY_TO_NODE_MAP: Record<string, string> = {
                    'financial_report': 'financial_node',
                    'sentiment_report': 'sentiment_node',
                    'risk_report': 'risk_node',
                    'technical_report': 'technical_node',
                    'macro_governance_report': 'macro_governance_node'
                };

                const newAgents: Record<string, AgentReport> = {};
                for (const [key, reportData] of Object.entries(nodeState)) {
                    if (key.endsWith('_report') && reportData) {
                        const mappedNodeName = KEY_TO_NODE_MAP[key] || key;
                        newAgents[mappedNodeName] = reportData as AgentReport;
                    }
                }

                if (Object.keys(newAgents).length > 0) {
                    setState(prev => ({
                        ...prev,
                        agents: {
                            ...prev.agents,
                            ...newAgents
                        }
                    }));
                }
            }
        });

        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse(e.data);
            setState(prev => {
                const newState = { ...prev, status: 'complete' as const, message: data.message || 'Analysis Complete' };
                // If it's a cached response, it might include judge_report directly in complete
                if (data.judge_report) {
                    newState.final_decision = {
                        decision: data.judge_report.final_decision || 'HOLD',
                        confidence_score: data.judge_report.confidence_score || data.judge_report.confidence * 10 || 0,
                        investment_thesis: data.judge_report.investment_thesis || data.judge_report.summary || '',
                        key_risks: data.judge_report.key_risks || data.judge_report.risk_flags || []
                    };
                }

                // Hydrate individual agent cards from the cache
                if (data.reports) {
                    const KEY_TO_NODE_MAP: Record<string, string> = {
                        'financial_report': 'financial_node',
                        'sentiment_report': 'sentiment_node',
                        'risk_report': 'risk_node',
                        'technical_report': 'technical_node',
                        'macro_governance_report': 'macro_governance_node'
                    };
                    const newAgents: Record<string, AgentReport> = {};
                    for (const [key, reportData] of Object.entries(data.reports)) {
                        if (key.endsWith('_report') && reportData) {
                            const mappedNodeName = KEY_TO_NODE_MAP[key] || key;
                            newAgents[mappedNodeName] = reportData as AgentReport;
                        }
                    }
                    newState.agents = { ...prev.agents, ...newAgents };
                }

                return newState;
            });
            eventSource.close();
        });

        eventSource.addEventListener('error', (e: Event) => {
            let errorMessage = 'Unknown streaming error';
            try {
                const messageEvent = e as MessageEvent;
                const data = JSON.parse(messageEvent.data);
                errorMessage = data.detail || errorMessage;
            } catch { }

            setState(prev => ({ ...prev, status: 'error', message: errorMessage }));
            eventSource.close();
        });

        // Handle generic unhandled SSE errors (e.g., connection reset)
        eventSource.onerror = () => {
            setState(prev => ({ ...prev, status: 'error', message: 'SSE Connection Lost' }));
            eventSource.close();
        };

        return () => {
            eventSource.close();
        };
    }, [ticker]);

    return state;
}
