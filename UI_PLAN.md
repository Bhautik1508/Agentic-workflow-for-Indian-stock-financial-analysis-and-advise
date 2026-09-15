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

### Phase U2 — Stop corrupting the output

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

1. Scope the print rule so `ScoreBreakdown` and `AnalystCard` headers survive. Hide chrome by
   class (`.no-print`), not by tag.
2. Suppress the `a[href]::after` URL expansion on internal nav links — keep it for the share
   permalink, which is the one case it was written for.
3. Use the run's real completion timestamp instead of `new Date()` at render, and label a cache
   hit as one.

*Exit check:* print to PDF and confirm all five pillar scores and all five analyst names and
scores are present. Compare against a pre-fix PDF.

---

### Phase U3 — Surface what is already on the wire
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

### Phase U4 — Tokens, then contrast
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
