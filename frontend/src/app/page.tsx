'use client';

import { motion } from 'framer-motion';
import SearchBar from '@/components/SearchBar';
import { useRouter } from 'next/navigation';

const QUICK_STOCKS = [
  { name: 'Reliance', ticker: 'RELIANCE.NS' },
  { name: 'TCS', ticker: 'TCS.NS' },
  { name: 'HDFC Bank', ticker: 'HDFCBANK.NS' },
  { name: 'Infosys', ticker: 'INFY.NS' },
  { name: 'Wipro', ticker: 'WIPRO.NS' },
  { name: 'Bajaj Finance', ticker: 'BAJFINANCE.NS' },
];

const AGENT_BADGES = [
  { label: 'Financial', color: '#00ff9f', icon: '📊' },
  { label: 'Technical', color: '#4080ff', icon: '📈' },
  { label: 'Sentiment', color: '#ff9f00', icon: '🧠' },
  { label: 'Risk', color: '#ff4060', icon: '🛡️' },
  { label: 'Macro & Gov', color: '#c0c040', icon: '🏛️' },
];

export default function Home() {
  const router = useRouter();

  return (
    <div className="w-full flex-1 flex flex-col items-center justify-center pt-16 pb-32 px-4 relative z-10">
      {/* Background Orbs */}
      <div
        className="fixed top-[20%] left-[15%] w-[600px] h-[600px] rounded-full -z-10 pointer-events-none"
        style={{
          background: 'radial-gradient(circle, rgba(0,212,255,0.05) 0%, transparent 70%)',
          filter: 'blur(80px)',
        }}
      />
      <div
        className="fixed bottom-[10%] right-[10%] w-[500px] h-[500px] rounded-full -z-10 pointer-events-none"
        style={{
          background: 'radial-gradient(circle, rgba(123,47,255,0.05) 0%, transparent 70%)',
          filter: 'blur(80px)',
        }}
      />

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="flex items-center gap-3 mb-10"
      >
        <div
          className="w-8 h-8 rounded-lg"
          style={{
            background: 'linear-gradient(135deg, #00d4ff, #00ff9f)',
          }}
        />
        <span className="text-lg font-semibold tracking-wide text-foreground/80">
          StockSage AI
        </span>
      </motion.div>

      {/* Headline */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
        className="text-center max-w-4xl mx-auto mb-6"
      >
        <h1 className="text-5xl md:text-7xl font-bold tracking-tight leading-tight mb-6">
          <span className="text-gradient">6 AI Analysts.</span>
          <br />
          <span className="text-foreground">1 Verdict.</span>
        </h1>

        <p className="text-lg md:text-xl text-text-muted max-w-2xl mx-auto leading-relaxed">
          Institution-grade Indian equity research, in 30 seconds.
        </p>
      </motion.div>

      {/* Search Bar */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.15, ease: 'easeOut' }}
        className="w-full max-w-2xl mx-auto mt-8"
      >
        <SearchBar />
      </motion.div>

      {/* Quick Access Chips */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.8, delay: 0.35 }}
        className="flex flex-wrap justify-center gap-2 mt-6 max-w-2xl mx-auto"
      >
        <span className="text-xs text-text-dim mr-1 self-center">Try:</span>
        {QUICK_STOCKS.map((stock) => (
          <button
            key={stock.ticker}
            onClick={() => router.push(`/analyze/${encodeURIComponent(stock.name)}`)}
            className="px-3 py-1.5 text-xs font-medium rounded-full border border-border bg-surface/60 text-text-muted hover:text-primary hover:border-primary/40 transition-all duration-200 cursor-pointer hover:bg-surface-hover"
          >
            {stock.name}
          </button>
        ))}
      </motion.div>

      {/* Agent Badges */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1, delay: 0.6 }}
        className="mt-20 flex flex-wrap justify-center gap-4 max-w-3xl mx-auto"
      >
        {AGENT_BADGES.map((agent, i) => (
          <motion.div
            key={agent.label}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, delay: 0.7 + i * 0.08 }}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-surface/50 border border-border/50 backdrop-blur-sm"
          >
            <span className="text-base">{agent.icon}</span>
            <span className="text-sm font-medium text-text-muted">{agent.label}</span>
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: agent.color, boxShadow: `0 0 8px ${agent.color}40` }}
            />
          </motion.div>
        ))}
      </motion.div>

      {/* Bottom tagline */}
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: 1.2 }}
        className="mt-16 text-xs text-text-dim text-center font-mono-num tracking-wider"
      >
        POWERED BY MULTI-AGENT AI ARCHITECTURE &nbsp;·&nbsp; NSE + BSE COVERAGE
      </motion.p>
    </div>
  );
}
