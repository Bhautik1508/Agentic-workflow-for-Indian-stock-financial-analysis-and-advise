'use client';

import { motion } from 'framer-motion';
import { AgentReport } from '@/hooks/useSSE';
import { ShieldAlert, TrendingUp, Brain, FileText, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

const getIcon = (name: string) => {
    const n = name.toLowerCase();
    if (n.includes('risk')) return <ShieldAlert size={20} className="text-warning" />;
    if (n.includes('techni')) return <TrendingUp size={20} className="text-accent" />;
    if (n.includes('senti')) return <Brain size={20} className="text-secondary" />;
    if (n.includes('financ')) return <FileText size={20} className="text-primary" />;
    return <CheckCircle2 size={20} className="text-foreground/50" />;
}

export function AgentCard({ nodeName, report, isRunning }: { nodeName: string, report?: AgentReport, isRunning: boolean }) {

    // Extract a readable name
    const displayName = report?.agent_name || nodeName.replace('_node', '').replace('_', ' ').toUpperCase();

    if (!report && !isRunning) {
        return (
            <div className="flex items-center gap-4 p-4 rounded-xl border border-border/50 bg-surface/20 opacity-40">
                <div className="w-10 h-10 rounded-full bg-black/50 flex items-center justify-center">
                    {getIcon(displayName)}
                </div>
                <div>
                    <p className="text-sm font-medium text-foreground/50">{displayName}</p>
                    <p className="text-xs text-foreground/30">Waiting for deployment...</p>
                </div>
            </div>
        );
    }

    if (isRunning && !report) {
        return (
            <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex items-center gap-4 p-4 rounded-xl border border-primary/30 bg-primary/5 shadow-[0_0_15px_rgba(0,212,255,0.05)] relative overflow-hidden"
            >
                <motion.div
                    className="absolute inset-0 w-full h-full bg-gradient-to-r from-transparent via-primary/10 to-transparent -translate-x-full"
                    animate={{ translateX: ['100%'] }}
                    transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
                />
                <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                    <Loader2 size={18} className="text-primary animate-spin delay-150" />
                </div>
                <div>
                    <p className="text-sm font-medium text-primary">{displayName}</p>
                    <p className="text-xs text-foreground/50 font-mono tracking-wider">ANALYZING DATA...</p>
                </div>
            </motion.div>
        );
    }

    const isError = report!.status === 'error';

    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className={cn(
                "flex flex-col gap-3 p-5 rounded-xl border bg-surface/80 backdrop-blur-md shadow-lg",
                isError ? "border-danger/30" : "border-border"
            )}
        >
            <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-black/30 flex items-center justify-center border border-white/5">
                        {isError ? <XCircle size={20} className="text-danger" /> : getIcon(displayName)}
                    </div>
                    <div>
                        <h3 className="font-semibold text-foreground/90">{displayName}</h3>
                        <div className="flex items-center gap-2 mt-0.5">
                            <span className={cn(
                                "text-xs px-2 py-0.5 rounded-sm font-mono",
                                isError ? "bg-danger/10 text-danger" : "bg-success/10 text-success"
                            )}>
                                {report!.status.toUpperCase()}
                            </span>
                            {!isError && (
                                <span className="text-xs text-foreground/50 font-mono">
                                    SCORE: {report!.score}/10
                                </span>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            <div className="mt-2 text-sm text-foreground/70 leading-relaxed border-l-2 border-border/50 pl-3">
                {report!.summary}
            </div>

            {!isError && report!.risk_flags && report!.risk_flags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                    {report!.risk_flags.map((risk, idx) => (
                        <span key={idx} className="inline-flex items-center gap-1 text-[10px] uppercase font-mono tracking-wider px-2 py-1 rounded bg-danger/10 text-danger/80 border border-danger/20">
                            <ShieldAlert size={10} /> {risk}
                        </span>
                    ))}
                </div>
            )}
        </motion.div>
    );
}
