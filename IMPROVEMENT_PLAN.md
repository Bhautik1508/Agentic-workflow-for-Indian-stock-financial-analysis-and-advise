# StockSage AI — Improvement Plan

A phased blueprint to elevate this project from a working multi-agent demo into a **defensible, decision-grade Indian equity verdict engine** with a UI worthy of the analytics underneath.

---

## 1. What you have today (honest review)

### Backend — strong bones, leaky verdict

The agent graph is well-designed:

- 5 domain agents (Financial, Technical, Risk, Sentiment, Macro & Governance) → Judge synthesiser.
- Weighted score: Financial 30 / Technical 23 / Risk 22 / Macro-Gov 13 / Sentiment 12.
- Smart confidence redistribution: when sentiment has no news (`news_available=False`), its weight is halved and rolled into Financial. This is a real insight and should be celebrated.
- Decision rules in [judge_analyst.py:48-54](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/agents/judge_analyst.py#L48-L54) are sensible (e.g., "3+ analysts ≥ 6.5 → BUY unless Risk < 4.0").

But several things are working against verdict quality:

| # | Issue | Where |
|---|---|---|
| 1 | Five-band verdict (`STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL`) collapses to 3 bands in UI — `VerdictPanel` only knows `BUY/HOLD/SELL`. The judge's nuance is lost. | [VerdictPanel.tsx:7](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/frontend/src/components/VerdictPanel.tsx#L7), [judge_analyst.py:42-46](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/agents/judge_analyst.py#L42-L46) |
| 2 | "Parallel" analysts run **sequentially** with a 1-second sleep between calls (Groq rate-limit workaround). End-to-end latency for one verdict is ~25-40 s, not 30 s as advertised. | [workflow.py:21-27](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/graph/workflow.py#L21-L27) |
| 3 | `target_price` / `stop_loss` / `max_entry_price` come purely from the LLM. No grounding in technical levels (support/resistance, ATR-based stop) or fundamental fair-value math. | [judge_analyst.py:88-90](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/agents/judge_analyst.py#L88-L90) |
| 4 | When an analyst fails, the workflow stamps a `score=5.0` placeholder and the judge silently averages it in. A failed Risk agent shouldn't yield a confident BUY. | [workflow.py:34-44](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/graph/workflow.py#L34-L44) |
| 5 | No verdict provenance / citations — the user can't see *which* news article, *which* peer comparison, or *which* screener row drove the call. | All agents |
| 6 | Cache is 1 hour by ticker — but a NSE close at 15:30 should invalidate cache; intraday vs EOD verdicts shouldn't be mixed. | [cache.py:8](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/data/cache.py#L8) |
| 7 | No accuracy / backtest loop. No way to know if past verdicts were right. Without this, the verdict is a vibes-output. | — |
| 8 | Tests are 15+ ad-hoc scripts (`test_phase3.py`, `test_lupin_agents.py`, etc.) instead of a pytest suite. | `backend/test_*.py` |
| 9 | Single LLM provider (Groq) → single point of failure. No fallback to OpenAI / Anthropic / Gemini. | [base_agent.py](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/agents/base_agent.py) |
| 10 | Static weights, no investor-profile awareness. A retiree and a 25-yr-old shouldn't get the same verdict on a high-beta small-cap. | [judge_analyst.py:4-10](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/agents/judge_analyst.py#L4-L10) |
| 11 | `confidence_score` is multiplied by 10 in the workflow ([workflow.py:73](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/graph/workflow.py#L73)) then by another 10 in the UI ([VerdictPanel.tsx:83](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/frontend/src/components/VerdictPanel.tsx#L83)) — likely showing 0-100% with the wrong scale. | Cross-stack |
| 12 | The `/analyze/{company_name}` route uses the *company name* (URL-encoded) not the ticker. Ticker resolution happens server-side, but this means cache + history use the user's spelling, not a canonical key. | [routes.py:18](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/backend/api/routes.py#L18) |

### Frontend — the part you don't like

Specifically what is hurting it:

- **Aesthetic identity is "Bloomberg-noir cosplay"**: navy `#0c0f19`, micro mono fonts (9–11 px), emoji icons, tiny score bars. It signals "demo project" rather than "I trust this with my money."
- **Type ramp is too tight**: 9 px header labels and 10–11 px body copy strain readability and feel cramped on retina screens.
- **Emoji as agent icons** (`📊 📈 🧠 🛡️ 🏛️`) — clashes with the otherwise minimalist theme. ([page.tsx:17-22](Agentic-workflow-for-Indian-stock-financial-analysis-and-advise/frontend/src/app/page.tsx#L17-L22))
- **Verdict isn't readable in 5 seconds.** The big `BUY` badge is there, but the *why* (one-line thesis, biggest risk, target upside %) isn't visually privileged. The thesis sits in 11px gray text against gray background.
- **AnalystCards are collapsed by default** — to evaluate the verdict you need 5 clicks. A retail user won't make them.
- **No comparison context**: no "vs Nifty50 / vs sector" delta, no "where does this rank in your watchlist?".
- **No mobile design** — `lg:grid-cols-5` collapses but the chart, verdict, and 5 cards become an endless scroll with no hierarchy.
- **Loading state is opaque**: spinner + "Awaiting verdict" — but the SSE is already streaming partial agent results. The user should *see* the agents thinking.
- **`VerdictPanel` duplicates Score Breakdown** that's already shown on each AnalystCard.
- **Strong-Buy / Strong-Sell are invisible** — the UI only renders 3 bands (see issue #1 above).
- **No actionability**: no "add to watchlist", "set price alert", "share", or "export PDF".

---

## 2. Phased plan

Each phase produces a working release. Phases 1–3 are about *making the verdict trustworthy*; Phases 4–5 are about *making the user trust it*; Phase 6 is *making it production-ready*.

> **Implementation note:** nothing below is implemented yet. Phases are sized so each can be picked up independently — Phase 4 (UI redesign) can run in parallel with Phase 2 (verdict engine).

---

### Phase 1 — Foundation & Verdict Truthfulness  *(1 week)*

**Goal:** fix the bugs that silently corrupt verdicts; restore full nuance end-to-end.

**Backend**
- [ ] Restore the 5-band verdict end-to-end. Plumb `STRONG_BUY` / `STRONG_SELL` through the workflow → SSE payload → frontend types.
- [ ] Replace the placeholder `score=5.0` on agent failure with a `null` score *and* a `degraded: true` flag on the report. Judge must treat degraded reports as "weight=0, confidence penalty applied."
- [ ] Fix the double-multiplication of `confidence_score` (workflow ×10 then UI ×10). Pick one canonical representation: float 0–1 wire format, percent 0–100 in UI.
- [ ] Run analysts truly in parallel via `asyncio.gather` with a token-bucket rate limiter (≥ 5 req/s tolerated by Groq). Target end-to-end ≤ 12 s P50.
- [ ] Switch cache key from "company_name as typed" to canonical ticker; key should also include the trading-day bucket (e.g. `RELIANCE.NS:2026-05-07`) so EOD ≠ intraday.
- [ ] Add a structured run log written to disk (one JSON per analysis with inputs, prompts, outputs, scores, verdict). Foundation for Phase 6 backtesting.

**Frontend**
- [ ] Add `STRONG_BUY` / `STRONG_SELL` cases to `DECISION_CONFIG` with distinct colour treatments.
- [ ] Fix `confidence_score` rendering once backend is canonical.
- [ ] Wire SSE → progressive AnalystCard rendering so users *see* analysts complete one by one.

**Exit criteria:** 5 distinct verdicts visible; failed agents don't drag the verdict; ≥ 2× faster; zero "vibes-only" cached results.

---

### Phase 2 — Verdict Engine Upgrade  *(1.5 weeks)*

**Goal:** make the verdict *defensible* — every number can be explained and challenged.

**Hybrid scoring (LLM + math)**
- [ ] Compute `target_price` two ways and reconcile:
  - Fundamental: `target_pe × forward_eps` (sector-median PE × company forward EPS).
  - Technical: nearest cluster of resistance / Fib 1.618 / analyst median target.
  - LLM target = sanity check, not source of truth.
- [ ] Compute `stop_loss` from ATR (e.g. `entry – 2 × ATR_14`) instead of trusting the LLM.
- [ ] Compute `position_size_modifier` from realised volatility, not LLM intuition.

**Investor profile awareness**
- [ ] Add `risk_profile` query param: `conservative | balanced | aggressive`.
- [ ] Profile shifts the weight vector (e.g., conservative bumps Risk weight from 22 → 32, drops Sentiment to 6).
- [ ] Profile also shifts the verdict bands (conservative needs score ≥ 7.5 for BUY, not 6.0).
- [ ] Record profile in run log so verdicts are reproducible.

**Conflict resolution & explainability**
- [ ] Judge prompt should output `dissent_summary`: "Technical disagrees because X; we override because Y."
- [ ] Add `score_attribution_json` (already partly in prompt) — render this in UI as a "what drove the verdict" waterfall.
- [ ] Define a clear **veto list** in the judge: any of these forces SELL/HOLD regardless of weighted score —
  - Altman Z < 1.8
  - Promoter pledging > 50 %
  - NSE ASM/GSM Stage 2+
  - Going concern qualification in audit
  - Score < 3.0 on Risk

**Citations**
- [ ] Each `key_finding` and `risk_flag` must carry an evidence pointer: `{type: "news"|"screener"|"yfinance", id|url, value}`.
- [ ] Judge inherits and surfaces the top 3 evidence items per verdict.

**Exit criteria:** for any verdict, you can answer in ≤ 30 s "why did it call this BUY?" with concrete numbers and links. Conservative profile reliably refuses to BUY a small-cap with Risk < 5.

---

### Phase 3 — Data Trust  *(1 week)*

**Goal:** the verdict is only as good as the data. Make the data layer paranoid.

- [ ] **Freshness indicators per data source** — every analyst card surfaces `as_of: "2026-05-07 14:32 IST"`. If any source is older than 24 h on a trading day, render a yellow chip.
- [ ] **Fallback chains**: yfinance → yahooquery → screener.in scrape → NSE web. Today some agents silently get `N/A` and the LLM hallucinates around it.
- [ ] **Schema validation** with pydantic at the data-fetch boundary. If 30 %+ of fundamental fields are missing, abort the run with an honest error (don't pretend to give a verdict).
- [ ] **Deterministic cache** — the same `(ticker, trading_day, profile)` returns byte-identical results.
- [ ] **Multi-LLM routing**: Groq primary, OpenAI fallback (or vice versa). Add per-call cost + latency to run log.
- [ ] **Pluggable data adapter interface** — abstract yfinance behind `IFundamentalsProvider` so swapping in a paid feed (Tickertape API, Tijori) is a 1-file change.

**Exit criteria:** an analyst whose primary data source dies *gracefully degrades* rather than poisoning the verdict.

---

### Phase 4 — UI Redesign  *(1.5–2 weeks, can run alongside Phase 2)*

**Goal:** kill the "demo terminal" feel. Build a UI that makes a non-trader trust the verdict in 10 seconds and an analyst go deep in 60.

**Design direction (pick one — recommended below)**

| Direction | Vibe | Reference points |
|---|---|---|
| **A. Premium Research Brief** *(recommended)* | Editorial, calm, white/cream surfaces with one accent colour. Reads like a Morgan Stanley note. Type set in a serif for headlines + sans for data. | Stripe Atlas reports, Tijori, Smallcase memos |
| B. Modern Trader Console | Light-mode, structured grid, dense but breathable. Less "noir," more "Linear meets TradingView." | Linear app, Notion AI, Public.com |
| C. Mobile-first Robinhood-style | Big numbers, swipeable cards, bottom-sheet drilldown. Optimised for "should I buy this on my phone?" | Robinhood, Groww, INDmoney |

**Recommendation:** **Direction A.** Your differentiator is *six analysts that disagree well*. That deserves a premium-research aesthetic, not a HFT terminal cosplay.

**Layout (Direction A)**

```
┌──────────────────────────────────────────────────────────────┐
│ StockSage   Reliance Industries  RELIANCE.NS  ·  NSE  ·  21:32│
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   ●  STRONG BUY        ₹3,210 → ₹3,820   +19% upside in 6mo │
│      87% conviction     Stop ₹2,950   Position size: 1.5%   │
│                                                              │
│   "Reliance combines Jio's ARPU expansion with retail's      │
│    operating leverage; oil refining margins remain a hedge.  │
│    Fair value supported by both DCF and technical breakout." │
│                                                              │
│   STRENGTHS                       RISKS                      │
│   • Financial 8.2 — ROCE 14.5%   • Crude > $90 (Macro 5.5)  │
│   • Technical 7.8 — golden cross • FII selling 10d net -₹8k │
│   • Macro/Gov 7.1 — gov stable   • Earnings in 9 days       │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ [ Price chart 1Y, with target/stop overlays ]                │
├──────────────────────────────────────────────────────────────┤
│ HOW THE VERDICT WAS BUILT                                    │
│ Financial 8.2 ████████░░  Technical 7.8 ███████▉░  ...      │
│ Tap any analyst to see their full reasoning.                 │
├──────────────────────────────────────────────────────────────┤
│ [ AnalystCard ] [ AnalystCard ] [ AnalystCard ]             │
└──────────────────────────────────────────────────────────────┘
```

**Concrete changes**
- [ ] Replace dark navy with a layered light theme (`#FAFAF7` paper, `#1A1B1E` ink) *or* a cleaner dark (`#0E0F12` near-black, single accent). Either way: ditch the grid overlay and the tight neon-emoji palette.
- [ ] Replace emoji icons with a custom icon set (Lucide for UI, custom monogram per analyst).
- [ ] Type ramp: H1 32 px, H2 22 px, body 14–15 px, micro 12 px (never below). Tabular `font-feature-settings: "tnum"` for numbers.
- [ ] **Verdict block above the fold**: decision + target + stop + thesis sentence + top strength + top risk. Everything else is below.
- [ ] **Always-on score breakdown** visible without expansion; click an analyst row to deep-dive (don't hide signals behind chevrons).
- [ ] **Comparison row**: "vs Nifty50 1Y: +14%" / "vs sector median PE: −12%".
- [ ] **Mobile-first responsive**: single column under 768 px, sticky verdict header, swipeable analyst tabs.
- [ ] **Streaming UX**: agents render progressively as SSE delivers them, with shimmer rows showing "Risk Analyst — looking at volatility, Sharpe, drawdown…" instead of an opaque spinner.
- [ ] **Empty / error states**: when an agent fails, render a calm explanation, not a red dot. Currently failures look like UI bugs.

**Exit criteria:** non-financial user can read a verdict and explain it back; analyst user can drill 3 levels deep without losing context; design survives a screenshot review against Smallcase / Tijori.

---

### Phase 5 — Insight & Action Layer  *(1 week)*

**Goal:** verdict → workflow. Today the user reads and leaves. Make them come back.

- [ ] **Watchlist** persisted server-side (or localStorage v1, then DB). Verdict re-runs nightly; user gets a verdict-change diff.
- [ ] **Price / verdict alerts**: "tell me when STOCK crosses BUY threshold" or "tell me when the score moves > 1.0 in either direction."
- [ ] **Compare 2 tickers** side-by-side — same agents, deltas highlighted. (Killer feature for "Reliance vs ONGC for energy exposure".)
- [ ] **What would change the verdict?** counter-factual panel: "if Risk score drops below 4.0 OR India VIX > 22, this becomes HOLD." Generate from the judge rules.
- [ ] **Export PDF research note** styled like a real broker's note. (Direction A makes this trivial.)
- [ ] **Share link with frozen verdict** — `/verdict/{id}` returns the analysis as it was at run time; doesn't re-run.

**Exit criteria:** D7 retention metric exists and is non-zero; user has at least one reason to return.

---

### Phase 6 — Productionization  *(1 week)*

**Goal:** something you can put in front of strangers without losing sleep.

- [ ] **Auth** (NextAuth + simple email/Google). Watchlist and history attach to user.
- [ ] **Rate limit** by user, not by IP. Free tier: 5 verdicts/day.
- [ ] **Backtest harness**: replay historical verdicts against forward 1M / 3M / 6M returns. Target: hit-rate > 55 % on BUY/STRONG_BUY at 1M horizon.
- [ ] **Convert ad-hoc tests** (`test_phase3.py`, `test_lupin_agents.py`, `test_bpcl.py`, …) into a pytest suite split by layer: `tests/data/`, `tests/agents/`, `tests/integration/`. Add CI.
- [ ] **Observability**: structured logs (loguru/structlog) → file + remote sink. Metrics for LLM latency, error rate per source, cache hit rate.
- [ ] **Disclaimers & SEBI compliance line** ("Not investment advice. We are not a SEBI Registered Investment Advisor.") visible on every verdict.
- [ ] **README** at repo root describing architecture (currently only the boilerplate Next.js README is committed). Add a `docs/` folder with the agent prompt design doc.

**Exit criteria:** you can demo to a recruiter or a paying user and it doesn't fall over on the first off-Nifty-100 ticker.

---

## 3. Suggested order if you only have time for half of this

1. **Phase 1** (verdict bugs) — non-negotiable, 1 week.
2. **Phase 4** (UI redesign) — gives you a portfolio piece worth showing, 1.5 weeks.
3. **Phase 2** (verdict engine) — the actual differentiator over a "Claude-wrote-5-prompts" project, 1.5 weeks.
4. Then Phases 3, 5, 6 in any order based on whether you're optimising for *trust*, *retention*, or *production*.

That trio (1+4+2) is ~4 weeks and turns this from a portfolio demo into a thing you'd actually use.

---

## 4. What to *not* do

- Don't add more agents. Six is already past the point where each marginal agent adds noise faster than signal. The judge is the bottleneck, not analyst breadth.
- Don't switch to a full custom backend (Postgres + Redis + Celery). The current FastAPI + LangGraph + file cache stack is right-sized; productionise it, don't replace it.
- Don't chase "real-time intraday" verdicts. Indian retail traders already have Zerodha, Sensibull, Tijori for tick-level data. Your edge is *structured reasoning*, which is naturally EOD or hourly.
- Don't paywall before Phase 6. The verdict has to be demonstrably good first.
