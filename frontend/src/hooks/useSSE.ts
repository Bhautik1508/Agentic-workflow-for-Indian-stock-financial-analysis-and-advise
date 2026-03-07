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

            // Ensure we extract the report dynamically based on the node name
            // e.g. 'financial_node' -> 'financial_report'
            let reportData = null;
            if (nodeState && typeof nodeState === 'object') {
                const reportKey = Object.keys(nodeState).find(k => k.endsWith('_report'));
                if (reportKey) reportData = nodeState[reportKey];

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
            }

            if (reportData) {
                setState(prev => ({
                    ...prev,
                    agents: {
                        ...prev.agents,
                        [nodeName]: reportData
                    }
                }));
            }
        });

        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse(e.data);
            setState(prev => ({ ...prev, status: 'complete', message: data.message || 'Analysis Complete' }));
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
