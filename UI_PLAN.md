# UI Audit & Improvement Plan

**Audience:** the developer maintaining this repo.

Third plan in the series. [IMPROVEMENTS.md](IMPROVEMENTS.md) made the system reliable.
[DATA_QUALITY_PLAN.md](DATA_QUALITY_PLAN.md) made its numbers correct. This one is about whether
any of that reaches the person reading the screen.

Every claim below was verified by reading the source during this audit. Contrast ratios were
computed, not estimated. Where I am guessing, I say so.

---

## 1. The finding that matters most

**The backend narrates the entire run. The UI throws the narration away.**

[backend/graph/runner.py](backend/graph/runner.py) emits seven `status` events describing exactly
what the pipeline is doing:

```python
yield {"event": "status", "data": f"Resolving ticker for {company_name}..."}          # line 46
yield {"event": "status", "data": f"Fetching core fundamental & price data..."}       # line 52
yield {"event": "status", "data": "Compiling technical indicators, risk models..."}   # line 59
yield {"event": "status", "data": "Scraping Sentiment, News & FII/DII datastreams..."}# line 88
yield {"event": "status", "data": "Fetching Macroeconomic, Governance & Options..."}  # line 93
yield {"event": "status", "data": "Data quality OK but with warnings..."}             # line 228
yield {"event": "status", "data": "Deploying specialist agents..."}                   # line 232
```

[backend/api/routes.py:236](backend/api/routes.py#L236) forwards them correctly.
[useAnalysis.ts:317](frontend/src/hooks/useAnalysis.ts#L317) receives them correctly and writes
them to `state.message`.

`state.message` is **never rendered anywhere in the application.** Grepping every `.tsx` file for
it returns two unrelated matches (`PriceChart`'s own fetch error, and the frozen-verdict page's).

Two consequences, and the second is the serious one:

1. During a ~31-second run the reader watches a generic shimmer that says "Verdict in progress"
   while a play-by-play of the actual work is arriving and being discarded.

2. **On failure, the reason is discarded too.** The error handler at
   [useAnalysis.ts:461](frontend/src/hooks/useAnalysis.ts#L461) carefully unpacks `msg.detail`,
   and even has a dedicated branch for rate-limiting —

   ```ts
   // Rate limiting is self-inflicted and self-resolving, so say so
   // plainly rather than letting it read as a broken analysis.
   if (msg.rate_limited) { errorMessage = msg.detail; }
   ```

   — and then stores it in `state.message`, which nothing reads.
   [VerdictHero.tsx:38](frontend/src/components/analysis/VerdictHero.tsx#L38) takes only `status`,
   so the user sees the words **"Analysis Failed"** above three shimmer bars. Nothing else.

This is the same symptom reported during Phase 5 testing ("still getting 'analysis failed' message
for 5 analysis"). The diagnosis then was a Gemini timeout. It was only diagnosable from the Render
logs, because the UI had already dropped the sentence that said so. The comment above is right
about what should happen; the wiring to make it happen was never finished.

**There is also no retry.** On error the EventSource closes and the only recourse is a browser
reload — which re-runs a 31-second pipeline from scratch.

---

## 2. What else the UI receives and discards

Each of these is parsed into a typed field and then never read by any component. Verified by
grepping each identifier across `src/`.

| Field | Parsed at | Rendered |
|---|---|---|
| `key_catalysts` | [useAnalysis.ts:354](frontend/src/hooks/useAnalysis.ts#L354), :416, verdict page :80 | **nowhere** |
| `grounded_targets.reward_to_risk` | [useAnalysis.ts:34](frontend/src/hooks/useAnalysis.ts#L34) | **nowhere** |
| `data_quality.missing_critical_fields` | [useAnalysis.ts:50](frontend/src/hooks/useAnalysis.ts#L50) | **nowhere** |
| `data_quality.sparse_sources` | [useAnalysis.ts:51](frontend/src/hooks/useAnalysis.ts#L51) | **nowhere** |
| `data_quality.warnings` | [useAnalysis.ts:55](frontend/src/hooks/useAnalysis.ts#L55) | **nowhere** |

The judge is asked to produce catalysts — the events that would make the thesis work — and the
reader never sees one. Reward-to-risk is arguably the single most decision-relevant number a
trade view can carry, and it is computed and dropped.

The data-quality case is the worst of the three, because a *partial* version is shown. The hero
renders a `Data 62%` chip ([VerdictHero.tsx:208](frontend/src/components/analysis/VerdictHero.tsx#L208))
with no way to find out which 38% is missing, when the backend sent exactly that list. A number
that invites a question it refuses to answer is worse than no number.

**Related: a failed analyst cannot be inspected.**
[AnalystCard.tsx:70](frontend/src/components/analysis/AnalystCard.tsx#L70) disables the expand
button when `isDegraded`, and surfaces `report.error` only through a `title=` attribute — a
hover tooltip, which does not exist on touch devices. On a phone, "Excluded — data unavailable"
is the end of the conversation.

---

## 3. Two places the output is actually broken

### 3.1 🔴 Printing deletes the scores and the analyst names

[globals.css:287](frontend/src/app/globals.css#L287) hides all buttons in print:

```css
@media print {
  .no-print, header, nav, button, [role="button"] { display: none !important; }
}
```

Both of these render as `<button>`:

- Every pillar in [ScoreBreakdown.tsx:31](frontend/src/components/analysis/ScoreBreakdown.tsx#L31)
  — so the **entire "How the verdict was built" section vanishes from the PDF**, all five scores
  and bars with it.
- Every card header in [AnalystCard.tsx:69](frontend/src/components/analysis/AnalystCard.tsx#L69)
  — which holds the **analyst's name, their score, and their signal line**. The printed card keeps
  its expanded body (if it happened to be open) and loses its title.

The print stylesheet is described as collapsing the page "to a one-page broker-style note". It
currently produces a note with no scores and unlabelled analyst sections. The fix is to scope the
rule (`button:not(.print-keep)`, or hide by class) rather than by tag.

Verified by inspection of both files; worth confirming with an actual print preview before and
after, since that is cheap.

### 3.2 🟠 The permalink is a downgrade

`ShareButton` exists, so links are meant to be shared. What the recipient gets at
[/verdict/[id]](frontend/src/app/verdict/[id]/page.tsx) is missing, relative to the live page:

- `ComparisonRow` is called **without the `relative` prop** ([page.tsx:161](frontend/src/app/verdict/[id]/page.tsx#L161)) — so no vs-index, no vs-sector, no CAPM alpha, no VIX regime
- No `QualityPanel` — no Piotroski, DuPont, Sortino, rolling beta, liquidity
- No `CounterFactualPanel` — no "what would change this verdict"
- No `PriceChart`, no `RunStats`

That is all five phases of Phase G analytics, absent from the one view built for an audience.
Whether the frozen payload carries these fields needs checking against the run-log schema — if
it does not, that is a backend change and this drops to Phase U3.

### 3.3 🟡 The timestamp is not the run's timestamp

[analyze/[ticker]/page.tsx:47](frontend/src/app/analyze/[ticker]/page.tsx#L47) computes
`new Date()` during render and labels it as the analysis time. It is the *render* time. For a
cache hit — where the verdict may be hours old — the header confidently states it is current.
The `complete` event carries the real one.

---

## 4. Accessibility

### 4.1 🔴 Contrast (computed, not estimated)

| Token | Hex | vs card `#FFFFFF` | Uses in TSX | Verdict |
|---|---|---|---|---|
| `--color-ink-2` | `#4A4D55` | 8.45:1 | 25 | pass |
| `--color-ink-3` | `#7A7F88` | **4.02:1** | **51** | **fails AA** (needs 4.5) |
| `--color-ink-4` | `#B6B8B8` | **1.99:1** | **18** | **fails badly** |

`ink-3` is `.heading-eyebrow` — *every section label in the application* — at 11px, uppercase,
monospace, letter-spaced. That combination is already the hardest thing on the page to read, and
it is under the AA floor.

`ink-4` is worse in a specific way: it is used for the **explanatory notes**. In
[QualityPanel.tsx](frontend/src/components/analysis/QualityPanel.tsx) and
[ComparisonRow.tsx](frontend/src/components/analysis/ComparisonRow.tsx), the sentences doing the
actual teaching — "Return beyond what its beta implies", "0 = at the low, 100 = at the high",
"Profit not backed by cash — lower is better" — are rendered at 1.99:1. The interpretation is
the most valuable text on the page and it is the least legible. That inverts the intent of the
Phase G work.

`#B6B8B8` at 1.99:1 is roughly the contrast of a pencil smudge. This is not a subtle miss.

### 4.2 🟠 The search box is invisible to screen readers

[SearchBar.tsx](frontend/src/components/SearchBar.tsx) implements a full combobox — arrow-key
navigation, a highlighted index, Enter-to-select, Escape-to-dismiss — with **zero ARIA**. No
`role="combobox"`, no `aria-expanded`, no `aria-controls`, no `aria-activedescendant`, no
`role="listbox"`/`role="option"`. A screen reader announces a bare text input; the results that
appear below it are not announced at all, and the highlighted item is not communicated.

The keyboard logic is already correct and complete. This is annotation, not rework — perhaps
fifteen lines.

Separately, results are selected via `onMouseDown` with no keyboard-equivalent handler on the
element itself, and dismissal relies on `setTimeout(..., 200)` in `onBlur`, which is a race.

### 4.3 🟠 Other

- `AnalystCard`'s expand toggle has no `aria-expanded` / `aria-controls`
  ([AnalystCard.tsx:69](frontend/src/components/analysis/AnalystCard.tsx#L69))
- **No `prefers-reduced-motion` handling anywhere.** Zero matches across `src/`. Framer Motion
  transitions, `skeleton-shimmer`, and `pulse-dot` all run unconditionally.
- Section headings are inconsistent landmarks: `ScoreBreakdown` uses `<h2>`, `QualityPanel` and
  `RunStats` use `<p>` for the same visual role. Heading-only navigation skips half the page.
- Live-region: nothing is marked `aria-live`, so the streaming verdict updates silently.

---

## 5. The design system is decorative

[globals.css](frontend/src/app/globals.css) defines a complete, well-considered token set — 60+
custom properties across surfaces, ink, rules, accent, verdict tones, chart palette, plus a
"legacy aliases" block explicitly kept "so old refs keep compiling".

The components ignore it. **299 hardcoded hex literals** across the `.tsx` files:

```
 51 [#7A7F88]    34 [#1A1B1E]    29 [#1E40AF]    25 [#4A4D55]
 24 [#B91C1C]    22 [#E5E3DB]    22 [#15803D]    18 [#B6B8B8]
```

Each of those is a token that already exists. The practical cost is concrete: the contrast fix in
§4.1 should be two variable edits. As things stand it is ~70 edits across a dozen files, with no
way to be sure you got them all.

**`HistorySidebar` is the exception, and it proves the point.** It is the one component still
written against token classes (`bg-surface`, `text-text-dim`, `border-border`) — because it was
never migrated to the Phase 4 editorial light theme. It still carries its dark-theme styling:

```tsx
className="... hover:bg-white/[0.04] ..."     // 4% white on a cream background
className="... bg-background/95 backdrop-blur-xl ... shadow-2xl"
className="... text-foreground/90 ..."
```

A 4%-white hover on `#FAFAF7` is invisible. The sidebar's hover state does not exist. It is a
surviving fragment of the pre-Phase-4 design, and it looks like one.

---

## 6. Flow and product

- **🟠 `/compare` is unreachable.** A complete 188-line comparison page with pillar deltas,
  side-by-side theses and profile switching — and **no link to it exists anywhere in the
  application**. Grepping for `compare` outside its own directory returns one match: an unrelated
  string in `QualityPanel`. The page's own empty state tells you to hand-edit the URL with two
  query parameters. This is a finished feature with no front door.

- **🟠 Changing risk profile silently re-runs everything.** `profile` is in the `useEffect`
  dependency array ([useAnalysis.ts:295](frontend/src/hooks/useAnalysis.ts#L295)), so clicking
  "Aggressive" tears down the EventSource, discards all loaded state, and starts a fresh
  ~31-second run with five LLM calls. The control looks like a filter toggle. It costs a full
  analysis. The buttons are correctly disabled *during* a run, but nothing warns before one.

- **🟡 The copy contradicts itself.** The landing page headline is "Five analysts. One verdict."
  ([page.tsx:56](frontend/src/app/page.tsx#L56)); the site metadata says "Six AI analysts"
  ([layout.tsx:19](frontend/src/app/layout.tsx#L19)). Five analysts plus a judge — both are
  defensible, but not in the same product.

- **🟡 Shared links preview as nothing.** No `generateMetadata`, no `openGraph`, no OG image;
  `public/` still contains only the Next.js starter SVGs. Every shared verdict — and sharing is a
  built feature — unfurls in Slack or WhatsApp as the generic site title. A verdict permalink is
  exactly the thing that should unfurl as "HDFC Bank — HOLD, 62% conviction".

- **🟡 Duplicate price fetch.** `TopBar` fetches `/api/price-history?period=5d` and `PriceChart`
  fetches the same endpoint at `?period=1y`, on the same page, for the same ticker. One request
  can serve both.

---

## 7. Phases

Ordered so that each phase is independently shippable, and so the phases that change what a user
can *learn* come before the ones that change how it *looks*.

### Phase U1 — Say what is happening and what went wrong ✅ BUILT

**A second bug was found while building this, and it is the reason the first one was invisible.**

The audit said the error reason was never *rendered*. It is also never *retained*. In the DOM, a
server-sent event named `error` dispatches an event of type `"error"` at the EventSource — and
`es.onerror` is simply a listener for that type. So both handlers fire for the same payload, in
registration order: the specific one first, the generic one immediately after.

```
1. addEventListener('error') fires, data present -> message = "Rate limit reached, try again in 40s"
2. onerror fires, data present                   -> message = "SSE connection lost"
```

Verified against Node's EventSource with the real handler shape, including the `close()` call the
old code made (`close()` does not cancel an in-flight dispatch, so it does not help):

```
OLD code  -> user sees: "Lost the connection to the analysis engine."
NEW code  -> user sees: "Rate limit reached — try again in 40 seconds."
NEW code  -> retry held for: 40 seconds; rateLimited = true
```

Rendering `state.message` alone would have fixed nothing — every failure would still have read
"SSE connection lost". The guard in `onerror` (`if (prev.error) return prev`) is what makes the
reason survivable.

**Built:**

1. **Live status line** in a new `ProgressPanel`, fed by the seven `status` events. Marked
   `role="status"` / `aria-live="polite"`; the shimmer bars are now `aria-hidden`.
2. **A real error panel** (`ErrorPanel`) replacing the "Analysis Failed" shimmer — states the
   reason, and for a data-quality abort also names `missing_critical_fields` and `sparse_sources`
   from the abort payload.
3. **Retry** that re-opens the stream in place via a nonce in the effect's dependency array —
   no page reload, no lost scroll position.
4. **Cooldown-aware retry.** The rate-limit payload carries `retry_after`, so the button holds
   and counts down ("Try again in 37s") instead of firing a retry guaranteed to fail.
5. **`AnalysisError`** as a distinct field from `message`, so the status narration and the failure
   reason can never overwrite one another again.

**Two additions beyond the four bullets above,** both because the page otherwise contradicts the
error it is now displaying:

- `ScoreBreakdown` shimmered forever on a failed run. It takes `status` now and shows "Not run".
- Analyst cards said *"Excluded — data unavailable"* for a run that never reached them, which
  states something we do not know. They now distinguish `notRun` from genuinely degraded.

**Verified:** `tsc` clean · production build clean · 34 frontend tests pass · no new lint errors
(4 pre-existing remain in `HistorySidebar`, `PriceChart` and `useAnalysis` — untouched, out of
scope).

**Run locally against the real backend** (uvicorn on :8000, Next dev on :3000, headless Chrome
over CDP). Both paths exercised:

*Live run* — HDFC Bank, 27.8s, 6 LLM calls, 0 fallbacks, 0 failures. All seven `status` events
arrived and rendered. Note the pacing, which is the argument for the whole phase:

```
[   1.6s] Resolving ticker for HDFC Bank...
[   2.8s] Compiling technical indicators, risk models & earnings data locally...
[   5.7s] Scraping Sentiment, News & FII/DII datastreams...
[  18.7s] Fetching Macroeconomic, Governance & Options context...      <- 13s gap
[  20.9s] Data quality OK but with warnings — verdict confidence will be capped.
[  20.9s] Deploying specialist agents...
[  27.8s] complete
```

That 13-second gap was previously a featureless shimmer, as was the whole 27.8s.

*Failure path* — rate limit tripped deliberately with `ANALYZE_BURST_LIMIT=2`. Rendered:

```
RATE LIMITED
Rate limit reached: 2 analyses per 30 minutes. Please try again in 1745 seconds.
[ Try again in 27m ]   (held, counting down)
The limit is per-IP and guards a shared model quota. Nothing is wrong with this stock…
```

The reason **survived to the screen** — confirming the `onerror` guard, since without it this
read "Lost the connection to the analysis engine." `ScoreBreakdown` showed "Not run" on all five
pillars instead of shimmering, and the analyst cards read "Not run — the analysis stopped first".

One fix came out of seeing it rendered: the cooldown said "Try again in 1739s". Now `humanWait()`
formats anything over 90s as minutes.

**Still unverified:** the ticker-resolution error and the data-quality abort were confirmed on the
wire but not screenshotted. Keyboard and screen-reader behaviour of the new `aria-live` region is
untested.

---

### Phase U2 — Stop corrupting the output ✅ BUILT

**🔴 New, found by running locally: the header reports every stock as down 100%.**

`TopBar` shows `— -100.00% ▼` for every ticker tested — Reliance, TCS, HDFC Bank, Infosys, four
for four. Two causes compound:

1. [TopBar.tsx:34](frontend/src/components/analysis/TopBar.tsx#L34) requests `?period=5d`. The
   endpoint's allow-list is `{"1mo","3mo","6mo","1y"}`
   ([routes.py](backend/api/routes.py)), so `5d` **silently falls back to `1y`** — 251 rows
   downloaded to compute a one-day change, and the §6 duplicate-fetch finding is worse than it
   looked: both requests pull the same full year.
2. The final row carries `close: null` (yfinance's incomplete current-session bar) with a real
   volume. TopBar then does `latest.close - prev.close`, and **JS coerces `null` to `0`**:

   ```
   change   = null - 1257.5  ->  -1257.5
   changePct = -1257.5 / 1257.5 * 100  ->  -100.00%
   ```

So the price reads "—" while the change beside it reads a confident, fabricated −100%. This is
the same defect class the data-quality work was about, this time in the UI. Fix: add `5d` to the
allow-list (or ask for `1mo`), and skip trailing rows with a null close instead of arithmetic on
them.

> **The same bad row also crashed the whole page, and that half is now fixed.** With Phase G
> streaming `extended_risk`, the NaN close made `annual_return_pct` NaN — and `json.dumps` writes
> that as the bare token `NaN`, which is valid Python and invalid JSON. The browser threw
> `Unexpected token 'N'` on parse, so one non-finite number took down the entire analysis rather
> than blanking one field. Fixed in two places: `market_data.py` now drops the still-forming
> session row before anything anchors on `Close.iloc[-1]` (the benchmark fetch ten lines above had
> always done this; the stock's own history never did), and every SSE payload now goes through a
> `_json_safe` sanitiser. Four regression tests added.
>
> **A cache hit bypassed the fetch-time guard.** `@cached_fetch` returns the stored payload
> without re-running the fetch body, so a payload captured mid-session carried the bad row into
> every later run that day — which is why one ticker kept failing after the rest were fine. The
> guard is now a named `drop_incomplete_sessions()` applied at *both* the fetch and the point of
> use in `runner.py`.
>
> **The wrong numbers mattered more than the crash.** Sanitising the wire stopped the page dying
> but left the values it had corrupted. With the bad row present, TCS reported:
>
> | | poisoned | corrected |
> |---|---|---|
> | `annual_return_pct` | `None` | **−26.3** |
> | `calmar_ratio` | `None` | **−0.684** |
> | `week52_percentile` | **100.0** | **18.6** |
>
> A stock down 26% on the year was reporting itself at the *top* of its 52-week range. A sanitiser
> alone would have shipped that silently — the same "confident wrong number" the data-quality work
> existed to kill.
>
> **The `/api/price-history` endpoint is a separate code path and still has the bad row**, which
> is why the −100% above survives. That is the remaining work in this item.

1. ✅ **Print rule scoped.** `button` and `[role="button"]` removed from the hide list; chrome is
   marked `.no-print` instead, and the chart's period selector gained that class. Measured under
   emulated print media, before and after:

   | | before | after |
   |---|---|---|
   | pillar scores visible | **0** | **5** |
   | analyst names visible | **0** | **5** |
   | chart period buttons | 0 | 0 (still hidden) |
   | nav header | hidden | hidden |

2. ✅ **`a[href]::after` restricted to `a[href^="http"]`.** Internal navigation is relative, so the
   unrestricted rule stamped a bare `(/)` after every in-app link — now 0. The dead
   `.no-href-print` escape hatch went with it.

3. ✅ **Real completion timestamp.** The backend stamps `generated_at` when a run finishes and
   stores it in the cached payload; a cache hit replays the original and flags `cached: true`.
   Verified round-trip on Cipla:

   ```
   FIRST RUN (live) : ... | 16 Sept 2026, 01:08 am
   SECOND LOAD (cache): ... | cached · 16 Sept 2026, 01:08 am
   ```

   A cache entry written before `generated_at` existed has no time to show, so it reads
   "from cache" rather than inventing one.

4. ✅ **The −100% header.** `5d` added to the endpoint's allow-list, and
   `drop_incomplete_sessions()` applied there too. `TopBar` now narrows to rows with a finite
   close via a type predicate, so the arithmetic cannot run on null.

   ```
   RELIANCE.NS  period=5d rows=  3  ->  ₹1257.50  -1.30%
   TCS.NS       period=5d rows=  3  ->  ₹2200.80  -0.15%
   HDFCBANK.NS  period=5d rows=  3  ->  ₹ 708.25  +2.08%
   INFY.NS      period=5d rows=  3  ->  ₹1037.70  +0.12%
   ```

   3 rows, not 251 — the §6 duplicate-fetch cost drops with it.

**Follow-on, fixed after the phase:** the target and stop `ReferenceLine` labels used
`position: 'right'`, which is exactly where the right-oriented Y axis sits. The text landed on the
price ticks (`Stop ₹1,638` over `₹1647`) and was clipped by the chart edge (`Target ₹2,71`, last
digit gone). Removed rather than repositioned: no fixed position is collision-proof across
arbitrary data, and the legend directly above already names both values, colour-matched to the
dashes.

**🔴 Still open, found while checking that fix — the price chart does not draw the price.**

[PriceChart.tsx:209](frontend/src/components/analysis/PriceChart.tsx#L209) renders the series as
`<Bar dataKey="close">`. That is a **column chart of closing prices**, drawn from the axis floor up
to the close — not a candlestick. Consequences:

- Each bar's *length* is distance from an arbitrary axis minimum, so it encodes nothing. Change the
  Y domain and every bar changes height while the data is identical.
- Open, high and low are fetched, computed, and shown in the tooltip, but **never drawn**. The
  chart cannot show a range, a gap, or a wick.
- It only *looks* like a candlestick chart when the Y domain happens to be much wider than the
  price range — which is what the target overlay was accidentally doing. With a target 60% above
  spot the domain stretches, the bars shrink, and they read as candles. On a stock whose target is
  near spot the same code renders a solid wall of bars.

Either draw real candles (a custom shape using O/H/L/C) or drop to a close line with the range as
a band. Both are honest; the current one is a chart whose most prominent visual dimension is
meaningless.

*Exit check met.* Printed brief verified end-to-end: verdict, comparison tiles, chart, all five
pillar scores with bars, all five analyst cards, quality panel, disclaimer.

**One gotcha worth recording:** the first print test reported 0 pillars and 0 analyst names *after*
the fix. The CSS on disk was correct; the Next dev server had never recompiled `globals.css` — it
was serving a chunk 50 minutes stale. Restarting it changed nothing about the code and everything
about the result. Check what the server is serving before concluding a fix failed.

**Not fixed here:** a cached verdict written before these fixes still replays its old numbers —
e.g. HDFC Bank showing `52-week position 100th pctile` while the same page says it is at 52-week
lows. A fresh run returns 6.9. Cache entries expire within the hour.

---

### Phase U3 — Surface what is already on the wire ✅ BUILT
No backend work except where noted; every field already arrives.

1. **Catalysts** — render `key_catalysts` in the hero beside Strengths and Risks. It is the
   forward-looking half of the thesis and it is currently invisible.
2. **Reward:risk** — add `grounded_targets.reward_to_risk` to the hero chip row, next to target
   and stop, where a reader is already doing that arithmetic.
3. **Data-quality detail** — make the `Data 62%` chip expand to name `missing_critical_fields`
   and `sparse_sources`. The list is already in the payload.
4. **Degraded-analyst errors** — let a failed card expand to show `report.error` as text. Remove
   the `title`-only path; it does not exist on touch.
5. **Permalink parity** — pass `relative` to `ComparisonRow` on the frozen page and add
   `QualityPanel`, `CounterFactualPanel`, `RunStats`. *First confirm the run-log payload carries
   `analytics` and `counter_factual`; if it does not, that is a backend change and belongs here
   rather than being quietly skipped.*

---

**All five built. Checking item 5 first, as instructed, turned up more than expected.**

**`analytics` was not stored at all**, so `write_run_log` gained an `analytics` argument and
`/api/verdict/{id}` now returns it under the same key the SSE `complete` event uses — the frozen
page hydrates through the identical path as a live run.

**`_scrub_reports` was also dropping `data_table` and `data`.** The scrub exists to keep bulky
upstream blobs out of the log, which is right, but `data_table` is display content — a handful of
label/value/signal rows — and its loss made every analyst card on a permalink read *"No signals
returned"*. Four scalars from `data` (`pe_premium_discount_pct`, `beta_category`, `trend`,
`macro_environment`) feed comparison tiles. Both are now kept, `data` through an explicit
whitelist. The existing test asserting the raw blob is not stored still passes unmodified: when
nothing survives the whitelist the key is omitted entirely, so "the blob is not stored" stays
literally true rather than becoming "stored, but empty".

**🔴 And `counter_factual` had never worked anywhere.** Not the run log — *anywhere*. No cache
entry, no run log, and not the live page either. Phase 5's "What would change this verdict?" had
never rendered once.

`judge_node` returns it. `JUDGE_FIELDS` streams it. But **LangGraph merges a node's return into
state by key and silently discards keys the state schema does not declare**, and
`StockAnalysisState` declared none of these five:

```
counter_factual      judge_score      score_attribution
strongest_pillar     weakest_pillar
```

Nothing errored. The judge computed all five and they evaporated between the judge and the
stream. Declaring them in `state.py` fixed it; a fresh run now returns:

```
counter_factual: band BUY, score 6.17, downgrade at < 5.5, upgrade at >= 7.0, 5 sensitivities
judge_score 6.5 | strongest_pillar financial | weakest_pillar technical
```

The regression test asserts the *whole* set — every `JUDGE_FIELDS` entry must be declared in
`StockAnalysisState` — rather than the five, because the next field added will fail the same
silent way.

**Rendering honestly, forced by what the data turned out to be.** Titan came back as a BUY with
`reward_to_risk = -9.62`. Since `rr = upside / downside` with `downside > 0`, a negative means the
target sits *below* spot — confirmed: target ₹3,397.68 against a spot of ~₹4,855.86, with the stop
₹4,704.36 *above* the target. So:

- reward:risk renders as a ratio only when it is one; otherwise it says **"Target at or below
  spot"**.
- the upside percentage beside the target was hardcoded `text-[#15803D]`, printing **−30.0% in the
  gain colour**. Now red when negative.

**🔴 Out of scope, needs its own fix:** those targets are incoherent. A BUY whose target is 30%
below spot and whose stop sits above its target is not a rendering problem — the blend in
`grounded_pricing` is dragged down by a fundamental anchor of ₹1,491 against technical ₹5,304,
analyst ₹5,421 and LLM ₹5,600. The UI now states this honestly instead of dressing it up, but the
number itself belongs in a pricing-logic phase.

*Verified:* catalysts render in a 3-column grid; the data-quality chip carries `aria-expanded` and
opens to `Missing: current_ratio · Sparse sources: news`; a failed analyst card opens to its error
text; the permalink shows the comparison tiles, accounting quality, risk profile, run stats,
analyst signals and the counter-factual. Tiles whose data is genuinely absent stay absent.

**One process note:** the first browser check reported catalysts and run stats as missing. Both
were present. `heading-eyebrow` sets `text-transform: uppercase` and `innerText` returns the
*rendered* text, so the assertions were matching "Catalysts" against a DOM saying "CATALYSTS".
Verify the verification before believing a failure.

---

#### U3 addendum — the counter-factual panel was too much, once it finally rendered

Making it work exposed that the per-pillar table was the weakest thing on the page:

- It is precise about something a reader cannot observe. Nobody watches a "Financial score"; they
  watch earnings, news and price.
- Rows routinely say nothing can happen — "Drops to 0.0 (−6.8 pts)" beside "Cannot upgrade alone"
  spends a line to report irrelevance.
- Pillars with no sensitivity in either direction were filtered out **silently**, so the table was
  quietly incomplete (four rows where there are five pillars).
- The current-score column duplicates `ScoreBreakdown` directly above it.

Collapsed rather than deleted — it is genuinely useful when interrogating a verdict you distrust.
The default view now leads with the two things worth reading:

```
Current 5.40 → HOLD   Downgrade to SELL at < 4.50   Upgrade to BUY at ≥ 6.00
Margin 0.90 points before the band changes
Most fragile pillar: Financial — a 3.0-point fall would downgrade this to SELL.
[ Show per-pillar sensitivity ⌄ ]
STRUCTURAL TRIGGERS (OVERRIDE SCORE)
  Risk score must stay ≥ 3.0; currently 6.5 (buffer 3.5).
```

The margin answers the question a reader actually has — *how close is this call?* — and the
structural triggers are the strongest content in the panel, because `Altman Z < 1.8` and
`promoter pledge > 50%` are real-world conditions that override the score outright. The expanded
table now also states how many pillars are omitted and why, instead of leaving a silent gap.

---

### Phase U4 — Tokens, then contrast ✅ BUILT
Sequenced deliberately: the migration is what makes the contrast fix a two-line change instead of
a seventy-site sweep. Doing U4b first means doing it twice.

**U4a — Migrate to tokens.** Replace the 299 hex literals with the existing token classes. Largely
mechanical and scriptable, but verify visually per component rather than trusting a regex.
Finish by re-styling `HistorySidebar` for the light theme — including that dead 4%-white hover.

**U4b — Fix contrast and motion.**
1. Darken `--color-ink-3` until it clears 4.5:1 on white (≈`#6A6F78`), and `--color-ink-4` until
   it clears 4.5:1 for the note text (≈`#767A7A`). Keep a genuinely-decorative tier if one is
   needed for rules and dividers, but stop using it for prose.
2. Re-check every ratio after the change; do not assume the new hex passes.
3. Add a `prefers-reduced-motion` block that disables shimmer, pulse, and Framer transitions.

*Exit check:* recompute all ratios; no text token below 4.5:1 on `#FFFFFF` or `#FAFAF7`.

---

**U4a — done.** 337 hex literals (not 299; the count grew across U1–U3) replaced across 20 files,
**0 remaining**. Eight tokens were missing and are now defined rather than left as one-offs: the
five verdict chip borders, `--color-paper-hover`, `--color-veto-ink`, `--color-warn`. No composite
arbitrary values contained a hex, so the substitution was safe to do mechanically.

Token resolution was verified by measuring a fresh single-class element per token, not by trusting
the build — a mistyped token name produces *no rule*, which compiles silently and renders
unstyled. All twelve resolve exactly, including the two new ones.

`HistorySidebar` was the last component still on the legacy aliases, because it had never been
migrated off the pre-Phase-4 dark theme. Now on canonical tokens, with its dead hover fixed:
`hover:bg-white/[0.04]` — 4% white, invisible on a cream page — is now `hover:bg-paper-hover`
at `#F8F7F2`. Its `shadow-2xl`, `bg-black/30` scrim and `text-foreground/90` went too. **No legacy
alias class remains anywhere in `src/`.**

---

**🔶 A correction to §4.1 of this document.**

The audit said the explanatory notes render at `#B6B8B8`, 1.91:1. They did not. `.text-micro` is
plain CSS written after `@import "tailwindcss"`, so it sits outside the utilities layer and
**wins the cascade** over the colour utility on the same element. Measured:

```
text-micro + text-ink-4  ->  rgb(122,127,136)     i.e. ink-3, not ink-4
```

So those notes were rendering at **3.85:1**, not 1.91:1. Still below the 4.5 floor, but a
materially smaller problem than I reported. Twelve of the twenty `ink-4` usages were overridden
this way; only eight took effect, and of those just three were prose (the search placeholder, the
sector label, the "· why?" affordance).

The fix is unchanged in shape but better targeted: the real problem was `ink-3` at 3.85:1 carrying
*every* `.text-micro` note and *every* `.heading-eyebrow` label.

**U4b — done.**

| token | was | now | paper | card | role |
|---|---|---|---|---|---|
| `--color-ink-3` | `#7A7F88` | **`#6E727A`** | 4.62:1 | 4.83:1 | lightest tier prose may use |
| `--color-ink-4` | `#B6B8B8` | **`#909191`** | 3.02:1 | 3.16:1 | **non-text only** — icons, decorative glyphs |

`ink-4` is reclassified rather than merely darkened. Two grey tiers cannot both clear 4.5:1 and
stay visually distinct, so it keeps a lighter value at the 3:1 floor for meaningful graphics and
is documented as off-limits for prose; the three places that used it for text now use `ink-3`.
Rules and dividers already had their own tier (`--color-rule*`), so no decorative text tier was
needed. The legacy `--color-text-tertiary` / `--color-text-dim` aliases were moved in step.

*Exit check:* **PASS.** Every text token ≥ 4.5:1 on both `#FAFAF7` and `#FFFFFF`; `ink-4` ≥ 3:1;
`veto-ink` on `sell-soft` 8.71:1. Confirmed in the browser: `.text-micro` and `.heading-eyebrow`
both render `rgb(110,114,122)`.

**Reduced motion** added. Under `prefers-reduced-motion: reduce` the shimmer and pulse animations
resolve to `animation-name: none`, transitions collapse, and Framer's inline transitions are
neutralised by the duration override. Verified both ways — motion returns under `no-preference`,
so the block is a response to the preference rather than a permanent disable.

#### U4 addendum — the hero's numbers were unreadable to a non-trader

Raised on looking at a real verdict:

```
— Hold    to ₹841  -16.4%
Conviction 80%   Stop ₹967 −3.9%   ⚠ Target at or below spot   Size 0.80×
```

Four problems, and the first is the worst:

1. **It never said what the stock costs today.** Every percentage hung off an invisible anchor.
   `current_price` was computed inside `reconcile_targets` and thrown away; it is now a field on
   `GroundedTargets` and reaches the page. Runs cached before that fall back to deriving it from
   the target and its percentage, which is the exact inverse of how the percentage was computed.
2. **Trade-desk vocabulary** — "spot", "stop", "conviction" — used without explanation.
3. **`Size 0.80×` gave no clue what it was 0.8 of.**
4. **`to ₹841`** reads as a destination, when for a negative target it is the opposite of one.

Replaced with a labelled grid, each figure carrying a sentence saying what it means:

```
TRADING NOW   PRICE TARGET        STOP LOSS            CONFIDENCE        POSITION SIZE
₹4,909        ₹3,399              ₹4,756               80%               0.94×
Today's       30.8% below today   Sell here to cap     How strongly      Smaller than a
market price. — this target is    the loss · 3.1%      the five          normal position
Everything    lower than the      below today          analysts agreed   — this stock
here is       current price                            with this call    moves a lot
measured
from it.
```

And where the target sits below the current price, the contradiction is stated rather than
compressed into a chip reading "Target at or below spot":

> The price target sits **below** today's price, so there is no gain to aim at here. The stop loss
> is above the target, which means the stop would trigger first. Treat the target as a valuation
> estimate, not a destination.

Also captioned the things a reader had to infer: pillar scores now read `6.8/10` rather than a
bare `6.8`, and Strengths / Risks / Catalysts / Dissent each say in one line what they contain.
`Reward vs risk 10.3 : 1` now carries "potential gain per unit risked".

The verdict word itself was left exactly as it was.

#### Then the price target was removed entirely

Writing that caveat banner was the tell. When a headline number needs a paragraph explaining why
it does not mean what it says, the number has already failed.

**The target is a mean of two anchors measured in different units.** `reconcile_targets` averages:

- a **fundamental** anchor — `forward EPS × sector-median P/E`, answering *"is this expensive?"*
- a **technical** anchor — the median of resistance levels above spot, answering *"where is the
  next ceiling?"*

Their average is not a worse estimate of either. It is an estimate of nothing; there is no question
to which it is the answer. And because the fundamental anchor prices every stock at its sector's
median multiple, it lands far below the market for any premium-multiple company — which is most of
what this tool rates a Buy.

Titan, measured:

```
fundamental  1,491.25   <- 50% weight   (spot 4,909 / 3.256; a 225.6% P/E premium to sector)
technical    5,304.10   <- 50% weight
analyst      5,421.50   <- discarded by the precedence rule
llm          5,600.00   <- discarded by the precedence rule
                 mean = 3,397.68   against a price of 4,909
```

Three anchors agree within 6%. The one that disagrees by 3× takes half the weight, and the other
two are dropped entirely whenever fundamental and technical both exist. There is an irony in the
code: `compute_technical_target` uses a **median** precisely because it is *"robust to one wild
outlier"* — and then the final reconciliation uses a mean of two, which is the one place the
outlier actually bites.

**Removed from the UI**, along with everything derived from it: the hero figure, the below-spot
caveat banner, `Reward vs risk` (a ratio computed from a number no longer stood behind — this is
where the `-9.6 : 1` came from), and the chart's target line and legend entry. The time horizon was
preserved as a meta item so it was not lost as collateral. The disclaimer no longer promises a
price target.

`target` and `upside` are still read in `VerdictHero` — solely to derive `Trading now` on runs
cached before the backend sent `current_price`. The reason for the absence is recorded at each
call site so it is not helpfully re-added.

A side effect worth noting: the chart's Y-axis domain no longer has to stretch to include a target
60% away from spot, so the price action occupies the full plot height instead of being squashed
into the bottom third.

**Still open:** the backend keeps computing it, so run logs retain it for analysis and nothing was
lost. Re-introduce the display when `reconcile_targets` stops averaging incompatible anchors —
take the median of all available anchors, and emit no target at all when their spread is too wide
to state one. Titan's median of all four is **₹5,363**, above spot and coherent with the verdict.

**Process note, third time this session.** The first U4b verification reported the old colours and
no reduced-motion block. Both were wrong: the source was correct and the Next dev server was
serving a `globals.css` chunk that still read `--color-ink-3: #7a7f88`. Turbopack does not reliably
pick up `@theme` edits. `rm -rf .next/dev` and restart before believing any CSS result.

---

### Phase U5 — Accessibility completion
1. Full combobox ARIA on `SearchBar` (`role`, `aria-expanded`, `aria-controls`,
   `aria-activedescendant`, `role="option"` per result). The keyboard logic is already correct.
2. `aria-expanded` / `aria-controls` on `AnalystCard`.
3. Normalise heading levels so `<h2>` marks every section; keep `.heading-eyebrow` as styling
   only, never as the element.
4. Replace the `onBlur` `setTimeout` dismissal with a pointer-outside/focus-outside handler.

*Exit check:* traverse the analyze page by keyboard alone and by headings alone, and confirm
search results are announced.

---

### Phase U6 — Flow and reach
1. **Give `/compare` a front door.** A "Compare with…" action on the analyze page, and a
   two-stock picker on its own empty state instead of instructions to edit the URL.
2. **Warn before a profile re-run**, or make the cost visible on the control ("re-runs analysis,
   ~30s"). Cheaper alternative worth considering first: if the backend can re-weight a completed
   run without re-calling the models, this becomes instant and the whole problem disappears.
   Needs checking before committing to either.
3. **Per-page metadata and OG images** via `generateMetadata` on `/analyze` and `/verdict`, so a
   shared verdict unfurls as the verdict. Replace the starter SVGs in `public/`.
4. **Reconcile "Five" vs "Six" analysts.**
5. **Deduplicate the price fetch** between `TopBar` and `PriceChart`.

---

### Phase U7 — Density polish
Lowest value; listed for completeness rather than recommended.

- `/compare` uses `grid-cols-2` at every width and a 12-column table that is cramped on a phone.
- `PriceChart` is `h-[42vh]` — short in mobile landscape.
- `QualityPanel` stat grids are `grid-cols-2` unconditionally; long values wrap awkwardly at
  narrow widths.

---

## 8. Sequencing

```
U1  ──> ships alone, ~half a day, fixes a live complaint
U2  ──> ships alone, small
U3  ──> ships alone; item 5 may need a backend check first
U4a ──> mechanical, must precede U4b
U4b ──> two-line fix once U4a lands
U5  ──> independent of U4
U6  ──> independent
U7  ──> optional
```

**If only one phase is built, build U1.** It is the smallest diff in this document and the only
one that fixes a problem the user has already hit in production.

---

## 9. What this plan does not cover

- **Visual redesign.** The editorial direction is coherent and well executed — the serif/mono
  pairing, the paper palette, the restraint with the single accent. Nothing here proposes changing
  it. Every finding is about the design being undermined by wiring, not about the design.
- **Dark mode.** `colorScheme: light` is forced in [layout.tsx:29](frontend/src/app/layout.tsx#L29).
  For a document that deliberately reads as printed paper, that is a defensible choice, not an
  oversight.
- **Performance.** Not measured. Bundle size, hydration cost and Lighthouse scores were outside
  this audit. If they matter, measure before planning — the same rule the data-quality work
  followed.
- **Anything requiring a browser.** Findings here come from reading source and computing ratios.
  Real-device testing, actual print previews and screen-reader passes will surface things static
  reading cannot.
