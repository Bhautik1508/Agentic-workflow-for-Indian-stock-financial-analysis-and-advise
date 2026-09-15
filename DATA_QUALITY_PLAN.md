# Data Quality & Analysis Calculations — Improvement Plan

**Constraint: free data sources only.** Every source named here is free, and each is marked
✅ verified (I called it during this audit) or ⚠️ unverified (plausible, confirm before relying on it).

**Audience:** the developer maintaining this repo.

Companion to [IMPROVEMENTS.md](IMPROVEMENTS.md), which covered infrastructure (providers, caching,
hardening). That work made the system *reliable*. This plan is about making the numbers it produces
*correct* — a different problem, and the more important one for an equity tool.

---

## 1. What the audit found

Four defects where the system reports a number that is not a measurement. These matter more than
any new data source, because a wrong number presented confidently is worse than a missing one.

### 1.1 🔴 Beta is always exactly 1.00 — it is measured against itself

[backend/graph/runner.py:59](backend/graph/runner.py#L59):

```python
nifty_mock = hist_df.copy() if not hist_df.empty else None   # the stock's OWN history
...
fetch_risk_data(ticker, hist_df, nifty_mock)
```

The beta calculation is `cov(stock, benchmark) / var(benchmark)`
([market_data.py:529](backend/data/market_data.py#L529)). With the benchmark set to the stock
itself that reduces to `var(x)/var(x)` = **1.0, for every stock, always**.

This is why every risk report in this repo's run logs says `Beta 1.00` and
`beta_category: market_like`. It is not a coincidence and it is not the market being unremarkable.
The comment calls it a "mock … to prevent crashing if offline", but it does not degrade to
*unknown* — it degrades to a **confident wrong answer** that then feeds `position_size_modifier`
and the risk pillar score.

**No real benchmark data is fetched anywhere in the codebase.**

### 1.2 🔴 The Altman Z veto can never fire

`scoring/vetos.py` reads `fundamental_data["altman_z_score"]` and forces a SELL below 1.8. The risk
prompt prints it too. **Nothing ever computes it** — the key is never written. So the veto is dead
code, the prompt always shows `N/A`, and a distressed balance sheet passes the safety net silently.

Every input (working capital, retained earnings, EBIT, equity, sales, total assets) is already
available free from Screener.in's balance sheet, which this app scrapes today.

### 1.3 🟠 Fundamental completeness is 0.2 in production — while richer free data sits unused

Production reports `fundamental_completeness: 0.2`, with 8 of 10 critical fields missing:
`market_cap, sector, current_ratio, roe, ebitda_margin, profit_margins, revenue_growth,
free_cashflow`.

The cause is not that the data is unavailable. It is that:

- `data_quality` measures **only** `fundamental_data`, which is populated **only** from yfinance;
- yfinance is rate-limited from Render's IPs (`Crumb fetch rate-limited (HTTP 429)` →
  `401 Invalid Crumb` in the deploy logs);
- meanwhile **Screener.in is scraped successfully on the same run** and returns 12–13 years of P&L,
  balance sheet and ratios — ROCE, OPM, Sales, Borrowings, Reserves, Debtor Days — none of which is
  mapped into `fundamental_data`.

So the app already has much of the missing data. It just does not put it where the gate looks.

### 1.4 🟠 Free sources configured but never called; a hardcoded macro input

- `ALPHA_VANTAGE_KEY` is set in `.env` and **used nowhere in the codebase**.
- The Sharpe risk-free rate is hardcoded to `0.065`
  ([market_data.py:544](backend/data/market_data.py#L544)) — while `fetch_rbi_repo_rate()` already
  fetches the live policy rate and is passed to the macro agent.

---

## 2. Free data sources — what is used, what is available

| Source | Cost | Status | Good for |
|---|---|---|---|
| **NSE India** (`nseindia.com/api/*`) | Free, no key | ✅ used (13 endpoints) | Indices, FII/DII, ASM/GSM, insider trades, option chain |
| **Screener.in** (scrape) | Free | ✅ used | 12yr P&L, balance sheet, ratios — **under-used** |
| **yfinance / yahooquery** | Free | ✅ used, rate-limited on cloud IPs | Prices, fundamentals, **indices (`^NSEI`)** |
| **BSE India** (`api.bseindia.com`) | Free, no key | ✅ used | Corporate announcements, governance |
| **World Bank** | Free, no key | ✅ used | GDP, CPI |
| **GDELT** | Free, no key | ✅ used | News tone |
| **Marketaux / NewsAPI** | Free tier | ✅ used | Headlines + sentiment |
| **Alpha Vantage** | Free tier | 🔴 **key set, never called** | Backup fundamentals, FX, economic series |
| **NSE `allIndices`** | Free, no key | ✅ verified working | Nifty 50 + **sectoral indices** for relative strength |
| **yfinance `^NSEI`** | Free | ✅ verified — 247 rows | **The beta fix** |
| **RBI** (`rbi.org.in`) | Free | partly used | Policy rate, 10Y G-sec for a real risk-free rate |
| **AMFI** | Free, no key | ⚠️ not used | Domestic fund flows |
| **data.gov.in** | Free, key | ⚠️ not used | IIP, inflation, sector output |
| ~~stooq.com~~ | — | ❌ **tested: now behind a JS proof-of-work wall** — do not use | — |

> I checked stooq specifically because it is the usual "free EOD CSV, no key" recommendation. It
> returns a browser challenge now, not data. Verifying beats assuming.

---

## 3. Phase-wise plan

### Phase A — Stop reporting fabricated numbers ✅ *(done)*

- [x] **Real benchmark, real beta.** `fetch_index_history("^NSEI")` added and cached by trading day
      (one fetch shared by every analysis). `runner.py` no longer passes `nifty_mock`.
- [x] **Beta is `None` when it cannot be measured** — never 1.0. Three guards: no benchmark, fewer
      than 30 overlapping sessions, or a benchmark correlating >0.999 with the stock (which is the
      old bug, not a finding — it logs `ERROR` and refuses).
- [x] **Altman Z computed** (`scoring/altman.py`), emerging-market Z'' variant, written into
      `fundamental_data` so the veto finally has something to read.
- [x] **One sourced risk-free rate.** The literal `0.065` inside Sharpe and the separate hardcoded
      `6.50` in `fetch_rbi_repo_rate()` are now a single `risk_free_rate_pct()`, overridable via
      `RISK_FREE_RATE_PCT` and range-checked so a typo cannot warp every Sharpe ratio.

**A second bug surfaced while verifying the first.** With the real index wired in, beta came back
at 0.13 / 0.02 with near-zero correlation — impossible for large caps. Two causes, both found only
because the numbers were checked against expectation rather than assumed fixed:

1. Both price series carried a positional `RangeIndex`, so pandas joined them **by row number**.
   A stock with 252 sessions against an index with 247 was offset by five.
2. After indexing by date, yfinance stamps Indian daily bars midnight **IST**
   (`2025-09-12 00:00:00+05:30`); converting to UTC gives 18:30 on the 11th, which normalises to
   **the previous day**. Every stock date sat one day behind the benchmark.

Fixed by joining on the local calendar date. Overlap went 187 → 246 sessions.

**Result — beta before and after:**

| Ticker | Before | After | Correlation |
|---|---|---|---|
| TCS | 1.00 | **0.85** | 0.39 |
| HDFC Bank | 1.00 | **1.25** | 0.77 |
| ITC | 1.00 | **0.64** | 0.42 |
| Infosys | 1.00 | **0.77** | 0.34 |
| Reliance | 1.00 | **0.91** | 0.59 |

Verified end to end — the risk reports now read `Beta 0.85` for TCS and `Beta 1.25` for HDFC Bank.
A defensive bank at 0.64 and a private bank at 1.25 is the shape you would expect; 1.00 for
everything never was.

**Altman Z across sectors:**

| Ticker | Sector | Z'' | Zone | Veto-eligible |
|---|---|---|---|---|
| TCS | Technology | 7.14 | safe | yes |
| ITC | Consumer Defensive | 8.75 | safe | yes |
| Reliance | Energy | 2.06 | grey | yes |
| HDFC Bank | Financial Services | — | — | **no — financials excluded** |

The veto now keys off the model's own zone. It previously compared against **1.8**, the distress
line of the *original* 1968 Z-score, while computing nothing at all — and had the field been
populated with a Z'', that threshold would have flagged healthy companies, since Z'' distress
begins below 1.1.

**Exit criteria met.** Beta varies across stocks and matches hand-checks; Altman Z is a number for
non-financials and `None` where it is not meaningful; no hardcoded macro constant remains in the
risk maths. 339 tests passing (was 309).

---

### Phase B — Close the completeness gap ✅ *(done)*

- [x] **Screener mapped into `fundamental_data`** via `data/fundamentals_adapter.py`, using the
      tolerant key matching from `screener_summary.py` and a value parser that survives
      `'₹\n  8,13,988\n\n  Cr.'`.
- [x] **Per-field merge with provenance.** Every field records its source
      (`_provenance`, `_source_counts`), so a scraped estimate is never mistaken for an official
      figure — by a reader or an agent. Merging per field means a partial yfinance response is
      topped up rather than discarded because it answered at all.
- [x] **Sector and industry scraped from Screener's own taxonomy.** Worth more than one field:
      `sector` gates both peer comparison and the Altman financial-exclusion check, and yfinance
      routinely omits it in production. Screener returns "Financial Services" for HDFC Bank, which
      is exactly what Phase A's Altman guard needs.
- [x] **Quality gate re-tuned**: abort 0.30 → **0.50**, warn 0.50 → **0.70**. The old line was
      calibrated around broken plumbing, where 0.44 was normal.
- [ ] ~~Alpha Vantage as a third tier~~ — **tested and rejected, see below.**

**Three faults were keeping the data out**, not one:

1. `scrape_screener` sliced the P&L and balance sheet to `rows[1:6]` — five rows each — dropping
   Net Profit, EPS, Interest, Depreciation and Total Assets, **and never read the cash-flow
   statement at all**. Removing the cap took the P&L from 5 → 12 rows, the balance sheet 5 → 10,
   and added 6 cash-flow rows *including Free Cash Flow directly*.
2. The extractor looked up exact keys (`"pl_Sales"`) against Screener's actual labels
   (`"pl_Sales\xa0+"`) — the same non-breaking-space bug that made CAGR "N/A" in every prompt.
3. Values were parsed with a plain `float()`, which cannot read a scraped currency string.

Prompt size is unaffected: `screener_summary.py` already caps what reaches the model, so the
scraper can return everything while the prompt stays bounded.

**Result — completeness with yfinance unavailable (i.e. production conditions):**

| Ticker | Before | Screener-only now | Still missing |
|---|---|---|---|
| TCS | 0.2 | **0.9** | current_ratio |
| Reliance | 0.2 | **0.9** | current_ratio |
| ITC | 0.2 | **0.9** | current_ratio |
| HDFC Bank | 0.2 | **0.7** | debt_to_equity, ebitda_margin, current_ratio |

Full pipeline, both sources live: TCS **1.0** with zero missing fields; HDFC Bank **0.8**
(fundamental) / 0.86 (overall). `current_ratio` is a genuine gap — Screener does not split current
assets from current liabilities, and inventing it would be worse than leaving it null. The bank's
extra gaps are the bank P&L format, not a failure.

> **Alpha Vantage: tested, not wired.** The plan called for it as a third tier since the key was
> already configured and idle. It does not earn its place: `TCS.BSE` returns an **empty** payload
> (no Indian fundamentals coverage on the free OVERVIEW endpoint) and further calls immediately hit
> a free-tier throttle. Building a tier on it would add a maintained code path that never
> contributes. The key can be removed from `.env`. Screener at 0.9 is the tier that actually works.

**Exit criteria met** for non-financials: ≥0.8 with yfinance down, 1.0 with both sources, every
field carrying a source, and no abort on a large cap. 370 tests passing (was 339).

---

### Phase C — Benchmark-relative context ✅ *(done)*

- [x] **Relative strength vs Nifty 50** over 1M/3M/6M/1Y, with the excess stated explicitly.
- [x] **Sector-relative performance** via NSE `allIndices`. One request returns **139 indices**
      carrying `perChange30d` / `perChange365d` each, so the sector comparison costs no extra
      history fetch. Sector→index mapping handles both vocabularies that reach us — Screener's
      ("Information Technology") and yfinance's ("Technology") — and prefers industry over sector
      so "Private Sector Bank" routes to NIFTY PVT BANK rather than the broader NIFTY BANK.
- [x] **CAPM alpha** alongside the beta and correlation from Phase A. Alpha returns `None` when
      beta is unmeasured, rather than quietly computing against a fabricated 1.0 — which would be
      the excess return wearing a more authoritative name.
- [x] **India VIX** from the same NSE payload, banded into calm / normal / elevated / stressed with
      an actionable note per regime.
- [x] Surfaced in the **Technical and Risk prompts** through one shared renderer, so both agents
      phrase the comparison identically and both are told "unavailable" where a number is genuinely
      missing — an agent told nothing invents something.

**A window bug surfaced during verification.** The 1Y comparison and the alpha both came back
`unavailable`: `fetch_index_history` requested `period="1y"`, which returns ~247 sessions — one
short of the 251 closes a 250-session lookback needs. The benchmark now fetches two years (495
sessions). Worth noting the guard worked as designed: `period_return_pct` returned `None` rather
than reporting a partial window as a full year.

**What the agents now see** (real output):

```
Versus NIFTY 50:
  1Y   stock   -24.66%   NIFTY 50    -7.04%   excess   -17.62%
Versus sector index NIFTY IT:
  1Y   stock   -24.66%   NIFTY IT   -17.68%   excess    -6.98%
  sector index P/E 18.85, P/B 5.2, yield 2.72%
CAPM alpha (1Y): -19.68%
India VIX 13.27 — regime NORMAL
```

And for HDFC Bank, the number that best justifies the phase: **1Y −24.68% against NIFTY BANK
+1.65%, an excess of −26.33%.** A bank falling 25% while its sector rose is a completely different
call from a bank falling with its sector — and the judge had no way to tell those apart before.

**Exit criteria met:** every verdict now states the stock's move against both the index and its
sector. 402 tests passing (was 370).

---

### Phase D — Deeper fundamental quality ✅ *(done)*

`scoring/quality_metrics.py`. All of it computed in Python and handed to the agents as inputs —
a model asked to derive a Piotroski score from a table produces something plausible and
unverifiable. The agents interpret; they do not calculate.

- [x] **Piotroski F-Score**, scored out of the criteria actually evaluable. Eight of the nine are
      computable from Screener; the ninth (change in current ratio) needs a current-assets split
      Screener does not publish, so it is reported as **unavailable rather than failed** — counting
      it as a failure would understate every company by a point. Each criterion carries its own
      explanation (`debt/assets 5.92% to 6.23%`), so a FAIL is auditable.
- [x] **DuPont decomposition** of ROE into margin × turnover × leverage, naming which lever
      dominates.
- [x] **Cash conversion** (CFO / net profit), latest and 3-year average — a single year of
      divergence is noise.
- [x] **Accruals ratio** `(NI − CFO) / total assets` as the second earnings-quality lens.
- [x] Fed to the **Financial and Risk** prompts through one renderer.
- [ ] **Promoter pledge *trend* — not built.** `promoter_trend` (holding direction) already exists
      in `governance_data`, but pledge *history* is not in the shareholding scrape, and a trend
      cannot be derived from a single snapshot. Deriving one would be inventing data.

**DuPont earns its place immediately.** Two real companies:

| | TCS | Reliance |
|---|---|---|
| ROE | **46.1%** | **10.6%** |
| Net margin | 18.5% | 9.1% |
| Asset turnover | 1.47x | 0.49x |
| Equity multiplier | **1.69x** | **2.41x** |
| Driver | **margin** | **leverage** |

A single ROE number says TCS is four times better. The decomposition says *why*, and that
Reliance's is substantially borrowed — exactly the distinction the phase existed to make.

Piotroski is similarly differentiating: TCS 5/8 (falling ROA and asset turnover despite high
absolute profitability) against Reliance 6/8 (improving ROA, falling leverage). Neither is obvious
from the headline ratios.

**A caching bug surfaced here.** `fetch_rbi_repo_rate` was wrapped in `@cached_fetch` despite doing
no I/O — it only reads a constant. The cache made a `RISK_FREE_RATE_PCT` change invisible for a day,
so the macro agent could report a different rate from the one the Sharpe calculation had already
used. Now uncached.

**Exit criteria met:** F-Score and cash conversion appear in every financial report, and the judge
can cite an accounting-quality reason. 426 tests passing (was 402).

---

### Phase E — Risk & technical calculation upgrades *(2–3 days)*

- [ ] **Sortino ratio and downside deviation** — Sharpe punishes upside volatility, which is not
      risk. For a BUY call this is the more honest measure.
- [ ] **Calmar ratio** (return / max drawdown) — pairs with the drawdown already computed.
- [ ] **Rolling beta** (1Y vs 3Y) to expose a changing risk profile.
- [ ] **Volume-profile / VWAP-relative** positioning to complement the existing indicator set
      (RSI, MACD, ADX, Bollinger, Stochastic, OBV, ROC, ATR are already there and are adequate).
- [ ] **52-week position as a percentile**, not just distance from high/low.
- [ ] **Liquidity screen** — median traded value. A verdict on an illiquid small cap deserves a
      different position size, and this is the input the existing `position_size_modifier` lacks.

**Exit criteria:** risk reports distinguish upside from downside volatility; no risk metric depends
on a hardcoded constant.

---

### Phase F — Validate that any of this helped *(ongoing)*

The harness from Phase 5 of IMPROVEMENTS.md already exists. Point it at this work.

- [ ] **Re-run the backtest after each phase.** Baseline today: **1M hit-rate 17% (1/6), 3M 33%
      (2/6)**, n=6 — far too small to conclude anything, which is precisely why it must accumulate
      before any weight is tuned on it.
- [ ] **Field-coverage regression test** — fail the build if `fundamental_completeness` for a
      Nifty-50 name drops below a floor. Coverage regressions are otherwise invisible until a
      verdict is already wrong.
- [ ] **Golden-set drift check** after each calculation change. A real beta *will* move some
      verdicts; the set tells you which, so the change is a decision rather than a surprise.
- [ ] **Only then re-tune the pillar weights** (`scoring/profiles.py`). Tuning weights against
      n=6 would be fitting noise.

**Exit criteria:** ≥50 scored verdicts before any weight is changed on backtest evidence.

---

## 4. Suggested order

1. **Phase A** — one day, and it stops three fabricated numbers reaching users. Non-negotiable.
2. **Phase B** — the completeness fix that makes every other pillar better, using data already fetched.
3. **Phase C** — the largest perceived-quality gain per line of code; "vs the index" is what a reader wants.
4. Then **D → E**, with **F** running continuously.

## 5. What not to do

- **Don't add a paid feed yet.** Phase B shows the free data is largely already arriving and simply
  not being used. Pay only once free sources are genuinely exhausted.
- **Don't ask the LLM to compute ratios.** Anything deterministic belongs in Python, where it is
  testable and reproducible. The agents should interpret numbers, not derive them.
- **Don't scrape more sites for redundancy's sake.** Each scrape is a maintenance liability — the
  non-breaking-space bug in Screener's keys silently produced "N/A" CAGR in *every prompt ever
  sent* until this audit. Prefer depth on sources you already parse.
- **Don't tune weights on the current backtest.** n=6 is noise.
