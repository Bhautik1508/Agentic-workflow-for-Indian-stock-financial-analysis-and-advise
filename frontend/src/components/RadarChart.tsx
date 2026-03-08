'use client';

import { Radar, RadarChart as RechartsRadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer } from 'recharts';
import { motion } from 'framer-motion';
import type { AgentReport } from '@/hooks/useSSE';

interface AnalystRadarProps {
    agents: Record<string, AgentReport>;
}

const AXIS_MAP: Record<string, string> = {
    'financial_node': 'Financial',
    'technical_node': 'Technical',
    'risk_node': 'Risk',
    'sentiment_node': 'Sentiment',
    'macro_governance_node': 'Macro+Gov',
};

export function AnalystRadar({ agents }: AnalystRadarProps) {
    const data = Object.entries(AXIS_MAP).map(([key, label]) => ({
        axis: label,
        score: agents[key]?.score ?? 0,
        fullMark: 10,
    }));

    const allComplete = Object.keys(AXIS_MAP).every((k) => agents[k]);
    if (!allComplete) return null;

    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="rounded-2xl border border-border/50 bg-surface/30 p-5"
        >
            <h3 className="text-[10px] font-mono uppercase tracking-[0.2em] text-text-dim mb-3 text-center">
                Analyst Score Radar
            </h3>
            <ResponsiveContainer width="100%" height={240}>
                <RechartsRadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
                    <PolarGrid stroke="rgba(26,37,64,0.8)" />
                    <PolarAngleAxis
                        dataKey="axis"
                        tick={{ fill: '#6b82a0', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                    />
                    <PolarRadiusAxis
                        angle={90}
                        domain={[0, 10]}
                        tick={{ fill: '#3a5070', fontSize: 9 }}
                        axisLine={false}
                    />
                    <Radar
                        name="Score"
                        dataKey="score"
                        stroke="#00d4ff"
                        fill="#00d4ff"
                        fillOpacity={0.15}
                        strokeWidth={2}
                    />
                </RechartsRadarChart>
            </ResponsiveContainer>
        </motion.div>
    );
}
