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

### Phase A — Stop reporting fabricated numbers *(~1 day)*

> Nothing else on this list improves the output as much as removing three numbers that are
> confidently wrong.

- [ ] **Fetch a real benchmark and fix beta.** Add `fetch_index_history("^NSEI")` (yfinance,
      ✅ verified: 247 rows). Cache it with the existing `@cached_fetch` — it is one series shared by
      every analysis, so the cost is one fetch per trading day for the whole app.
      Replace `nifty_mock` in `runner.py`.
- [ ] **When the benchmark is genuinely unavailable, return `beta: None`** — never 1.0. The
      degraded-report machinery already handles missing values; a null is honest, a 1.0 is a lie.
      Have the risk prompt say "unavailable" rather than print a number.
- [ ] **Compute Altman Z** (`scoring/altman.py`) from Screener balance-sheet rows, using the
      emerging-market variant where inputs allow. Write it into `fundamental_data["altman_z_score"]`
      so the existing veto finally has something to read. Return `None` when inputs are missing —
      a veto that cannot be evaluated must not silently pass.
- [ ] **Use the live risk-free rate** from `fetch_rbi_repo_rate()` (or the 10Y G-sec) in the Sharpe
      calculation instead of the hardcoded 6.5%.

**Exit criteria:** beta varies across stocks and matches a hand-check for two names; Altman Z is a
number for large caps and `None` where inputs are absent; no hardcoded macro constants in the risk
math.

---

### Phase B — Close the completeness gap with data already being fetched *(2–3 days)*

- [ ] **Map Screener.in into `fundamental_data`.** A `screener_adapter` that derives
      `roe, roce, debt_to_equity, current_ratio, profit_margins, ebitda_margin, revenue_growth,
      market_cap, book_value` from rows already scraped. Use `data/screener_summary.py`'s tolerant
      key matching — remember Screener's labels carry a non-breaking space.
- [ ] **Make it a real fallback chain** behind the `IFundamentalsProvider` seam built in Phase 4 of
      IMPROVEMENTS.md: `yfinance → yahooquery → screener → alpha_vantage`. First non-empty wins,
      per field rather than per provider, so a partial yfinance response is topped up rather than
      discarded.
- [ ] **Record provenance per field** (`{"roe": {"value": 0.518, "source": "screener.in"}}`). Without
      it you cannot tell a scraped estimate from an official filing, and the agents currently cannot
      either.
- [ ] **Wire up Alpha Vantage** as the third tier — the key is already configured and idle. Respect
      its free-tier request budget (verify the current daily limit) and let the fetch cache absorb
      repeats.
- [ ] **Re-tune the data-quality gate once completeness rises.** The 0.30 abort threshold was set
      when 0.44 was normal; with better coverage it should be raised, or thin tickers will keep
      slipping through.

**Exit criteria:** `fundamental_completeness ≥ 0.8` on Nifty-50 names in production; every field
carries a source; no abort on a large cap.

---

### Phase C — Benchmark-relative context *(2–3 days)*

Nothing in the current output answers "compared to what?" — the single most common question about
any equity call.

- [ ] **Relative strength vs Nifty 50** over 1M/3M/6M/1Y, from the benchmark series added in Phase A.
- [ ] **Sector-relative performance** using NSE `allIndices` (✅ verified working) — map the
      company's sector to its sectoral index (NIFTY IT, NIFTY BANK, …). "Down 8% while its sector is
      down 15%" is a different call from "down 8%".
- [ ] **Alpha and correlation** alongside beta, now that a real benchmark exists.
- [ ] **India VIX** from NSE as a market-regime input, replacing prose about "market regime" with a
      number.
- [ ] Surface all of it in the Technical and Risk prompts, and in the UI's existing `ComparisonRow`.

**Exit criteria:** every verdict states the stock's move against both the index and its sector.

---

### Phase D — Deeper fundamental quality *(3–4 days)*

All computable from data Phase B makes available. No new sources.

- [ ] **Piotroski F-Score (0–9)** — profitability, leverage, efficiency. A compact, well-understood
      quality signal, and a strong input to the financial pillar.
- [ ] **DuPont decomposition** of ROE (margin × turnover × leverage) — distinguishes a genuinely
      profitable business from a levered one, which a single ROE number hides.
- [ ] **Cash conversion** (CFO / net profit, multi-year). The most practical accounting-quality
      check available from free data; persistent divergence is the classic warning sign.
- [ ] **Accruals ratio** as a second earnings-quality lens.
- [ ] **Promoter pledge trend**, not just the level — the veto already reads pledge %, but direction
      matters more than a snapshot.
- [ ] Feed these to the Financial and Risk agents as *computed inputs*, not as things the model is
      asked to infer. Deterministic maths belongs in Python; judgement belongs in the prompt.

**Exit criteria:** F-Score and cash conversion appear in every financial report; the judge can cite
an accounting-quality reason.

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
