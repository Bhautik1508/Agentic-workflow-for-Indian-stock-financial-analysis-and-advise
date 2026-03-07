'use client';

import { motion } from 'framer-motion';
import SearchBar from '@/components/SearchBar';
import { Activity, Brain, ShieldAlert, TrendingUp, Cpu } from 'lucide-react';

export default function Home() {
  return (
    <div className="w-full flex-1 flex flex-col items-center justify-center pt-20 pb-32 px-4">
      {/* Background Orbs */}
      <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] bg-primary/20 rounded-full blur-[120px] -z-10 mix-blend-screen opacity-50" />
      <div className="absolute bottom-1/4 right-1/4 w-[600px] h-[600px] bg-secondary/10 rounded-full blur-[150px] -z-10 mix-blend-screen opacity-50" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="text-center max-w-4xl mx-auto mb-12"
      >
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 border border-white/10 mb-8 backdrop-blur-md">
          <Cpu size={16} className="text-primary" />
          <span className="text-sm font-mono tracking-wide text-foreground/80">MULTI-AGENT AI ARCHITECTURE</span>
        </div>

        <h1 className="text-5xl md:text-7xl font-semibold tracking-tight mb-8">
          Decode the Indian Market with <br className="hidden md:block" />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary via-accent to-secondary">
            StockSage AI
          </span>
        </h1>

        <p className="text-xl text-foreground/60 max-w-2xl mx-auto leading-relaxed">
          Deploy a swarm of 5 specialized AI analysts to evaluate fundamentals, technicals, sentiment, macroeconomic trends, and downside risks in real-time.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.2, ease: "easeOut" }}
        className="w-full"
      >
        <SearchBar />
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: 0.6 }}
        className="mt-24 grid grid-cols-2 md:grid-cols-4 gap-6 max-w-5xl mx-auto px-4"
      >
        {[
          { icon: TrendingUp, label: "Fundamentals", color: "text-primary" },
          { icon: Activity, label: "Technical Analysis", color: "text-accent" },
          { icon: Brain, label: "Market Sentiment", color: "text-secondary" },
          { icon: ShieldAlert, label: "Risk & Macro", color: "text-warning" }
        ].map((feature, i) => (
          <div key={i} className="flex flex-col items-center justify-center p-6 rounded-2xl bg-surface/40 border border-border/50 backdrop-blur-sm">
            <feature.icon size={28} className={`mb-4 ${feature.color}`} />
            <span className="text-sm text-foreground/80 font-medium text-center">{feature.label}</span>
          </div>
        ))}
      </motion.div>
    </div>
  );
}
