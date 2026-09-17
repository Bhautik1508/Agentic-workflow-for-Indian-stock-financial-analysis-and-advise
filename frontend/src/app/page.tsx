'use client';

import { motion } from 'framer-motion';
import SearchBar from '@/components/SearchBar';
import { Watchlist } from '@/components/Watchlist';
import { useRouter } from 'next/navigation';
import { toRouteTicker } from '@/lib/route';

const QUICK_STOCKS = [
    { name: 'Reliance',     ticker: 'RELIANCE.NS' },
    { name: 'TCS',          ticker: 'TCS.NS' },
    { name: 'HDFC Bank',    ticker: 'HDFCBANK.NS' },
    { name: 'Infosys',      ticker: 'INFY.NS' },
    { name: 'Wipro',        ticker: 'WIPRO.NS' },
    { name: 'Bajaj Finance',ticker: 'BAJFINANCE.NS' },
];

const PILLARS = [
    { label: 'Financial',   colour: '#1E40AF', body: 'Valuation, profitability, balance-sheet quality.' },
    { label: 'Technical',   colour: '#166534', body: 'Trend, momentum, volume, volatility regime.' },
    { label: 'Risk',        colour: '#991B1B', body: 'Beta, Sharpe, drawdown, liquidity, leverage.' },
    { label: 'Sentiment',   colour: '#A16207', body: 'News tone, FII/DII flow, retail positioning.' },
    { label: 'Macro & Gov', colour: '#4A4D55', body: 'Interest rates, sector setup, governance flags.' },
];

export default function Home() {
    const router = useRouter();

    return (
        <div className="w-full flex-1 flex flex-col items-center pt-20 md:pt-32 pb-32 px-6">
            {/* Wordmark */}
            <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="flex items-center gap-2 mb-12"
            >
                <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                <span className="font-serif text-[16px] font-semibold tracking-tight text-ink">
                    StockSage
                </span>
                <span className="text-[10px] font-mono uppercase tracking-widest text-ink-3">research preview</span>
            </motion.div>

            {/* Headline */}
            <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.05, ease: 'easeOut' }}
                className="text-center max-w-3xl mx-auto mb-6"
            >
                <h1 className="font-serif text-[44px] md:text-[64px] leading-[1.05] font-semibold tracking-tight text-ink mb-5">
                    Five analysts. <br className="md:hidden" />
                    <span className="italic text-accent">One verdict.</span>
                </h1>
                <p className="text-lede max-w-xl mx-auto">
                    Institution-grade Indian equity research, generated from public data and structured
                    reasoning. No charts you can&rsquo;t explain.
                </p>
            </motion.div>

            {/* Search */}
            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.15 }}
                className="w-full max-w-2xl mt-10"
            >
                <SearchBar />
            </motion.div>

            {/* Quick chips */}
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6, delay: 0.3 }}
                className="flex flex-wrap items-center justify-center gap-2 mt-5 max-w-2xl"
            >
                <span className="text-micro mr-1">Try</span>
                {QUICK_STOCKS.map((s) => (
                    <button
                        key={s.ticker}
                        // Navigate by ticker, not display name: a name with a space
                        // ("HDFC Bank") round-trips through the route param and ends up
                        // double-encoded. SearchBar already navigates by symbol.
                        onClick={() => router.push(`/analyze/${encodeURIComponent(toRouteTicker(s.ticker))}`)}
                        className="px-2.5 py-1 text-[12px] rounded-full border border-rule bg-white text-ink-2 hover:border-accent/40 hover:text-accent transition cursor-pointer"
                    >
                        {s.name}
                    </button>
                ))}
            </motion.div>

            {/* Watchlist (renders only when localStorage has entries) */}
            <Watchlist />

            {/* Pillars panel — editorial 5-up */}
            <motion.section
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.7, delay: 0.45 }}
                className="mt-24 w-full max-w-5xl"
            >
                <h2 className="heading-eyebrow text-center mb-8">The five pillars of the verdict</h2>
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                    {PILLARS.map((p, i) => (
                        <div
                            key={p.label}
                            className="card-paper px-4 py-5 flex flex-col gap-3"
                        >
                            <div className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full" style={{ background: p.colour }} />
                                <span className="font-serif text-[16px] font-semibold text-ink">{p.label}</span>
                                <span className="ml-auto font-mono text-[10px] text-ink-4">0{i + 1}</span>
                            </div>
                            <p className="text-small text-ink-2">{p.body}</p>
                        </div>
                    ))}
                </div>
            </motion.section>

            {/* Footer wordmark */}
            <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.8, delay: 0.9 }}
                className="mt-24 text-micro tracking-widest"
            >
                NSE + BSE COVERAGE · MULTI-AGENT REASONING · NOT INVESTMENT ADVICE
            </motion.p>
        </div>
    );
}
