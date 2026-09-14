# StockSage AI — Improvements v2

Successor to [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md), whose Phases 1–5 are largely shipped
(5-band verdicts, degraded-agent handling, grounded pricing, risk profiles, vetos, freshness,
data-quality gate, telemetry, watchlist/compare/share).

This document covers what a fresh audit of the running system found — including **two live
incidents** — plus ten ranked improvements and a phase-wise plan to land them.

**Audience:** the developer maintaining this repo.

---

## 0. Shipped in this pass — Gemini is now the primary model

Gemini is primary, Groq is the fallback tier, and the router fails over **between providers**,
not just between models on one provider.

| File | Change |
|---|---|
| [backend/llm/providers.py](backend/llm/providers.py) | **New.** `GeminiProvider` (google-genai), `GroqProvider`, `OpenAICompatProvider`, and `build_default_chain()`. Each vendor normalises onto one `complete()` coroutine returning `CompletionResult`. |
| [backend/llm/router.py](backend/llm/router.py) | **Rewritten.** Walks an ordered `(provider, model)` chain and returns the first success. |
| [backend/llm/telemetry.py](backend/llm/telemetry.py) | `LLMCallRecord` gains `provider` + `attempt`; adds `by_provider()` and `primary_provider_success_rate()`. |
| [backend/agents/base_agent.py](backend/agents/base_agent.py) | `get_llm()` now returns the provider chain rather than a single vendor client. No agent call-site changed. |
| [backend/requirements.txt](backend/requirements.txt) | `+google-genai`, `aiohttp>=3.10.6` (see below), `-langchain-google-genai` (unused, and it pins an old `google-generativeai` that fights `google-genai`). |
| [backend/tests/test_llm_providers.py](backend/tests/test_llm_providers.py) | **New**, 20 tests: chain order, key-missing behaviour, Gemini message translation, cross-provider failover, credential-skip. |

Default chain: `gemini-3.6-flash` → `gemini-3.5-flash-lite` → `openai/gpt-oss-120b` → `openai/gpt-oss-20b`.
A tier with no API key is skipped, so the app still runs on one provider.

Every model ID below was measured against this account, not assumed — see §1.5.

Configure entirely from env — a model decommission becomes a dashboard change, not a redeploy:

```bash
LLM_PRIMARY_PROVIDER=gemini   # or groq, to invert the chain
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite   # different model = different capacity pool
GEMINI_RETRIES=0              # same-model retries measurably do not help; see §1.5
GEMINI_THINKING_BUDGET=       # leave BLANK - Gemini 3.x rejects a 0 budget with HTTP 400
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODEL=openai/gpt-oss-20b
```

### Three behaviour changes worth knowing

1. **Failover now triggers on any error, not just HTTP 429.** The old router re-raised
   non-429s immediately — which is exactly why the Groq model retirement (below) became a total
   outage instead of a graceful degradation.
2. **Every attempt is recorded in telemetry**, including the ones that failed. Previously a
   429'd primary call left no trace, so the run log understated real latency and hid failures.
3. **A rejected credential skips that provider's remaining attempts.** A 403 will repeat
   identically; retrying it only adds latency. Rate limits are explicitly *excluded* from this
   rule — they are transient, so the retry still happens.

### Verified end-to-end

A full `run_stock_analysis("Tata Consultancy Services")` completes with all five analysts plus
the judge: `BUY | conf 0.85 | target ₹2563.70 | stop ₹2088.96`.

**The entire run is served by Gemini — Groq is never called.** 11 LLM calls, 21,027 tokens. Where
`gemini-3.6-flash` hits a capacity 503, `gemini-3.5-flash-lite` absorbs it inside the same
provider, which is exactly what the two-model Gemini tier is for.

Test suite: **166 passing**.

> **Tuning note.** `primary_success_rate` sits at ~0.17: under 5-way analyst concurrency on a
> free-tier key, `gemini-3.6-flash` 503s on most calls and `gemini-3.5-flash-lite` does the real
> work. The run succeeds and stays on Gemini either way. If you would rather skip the wasted
> round-trip than opportunistically reach for the stronger model, invert them:
> ```bash
> GEMINI_MODEL=gemini-3.5-flash-lite
> GEMINI_FALLBACK_MODEL=gemini-3.6-flash
> ```

---

## 1. Two live incidents found during the audit

### 1.1 🔴 Leaked API keys, still in public git history

`backend/.env` was committed in `62927b7` and deleted in `9f68825` — but **the blob survives in
history and is reachable from `origin/main`** on the public GitHub repo. Google has already
detected and revoked the Gemini key:

```
403 PERMISSION_DENIED — "Your API key was reported as leaked. Please use another API key."
```

Current status, by comparing hashes of `.env` against the leaked blob:

| Key | Status |
|---|---|
| `GOOGLE_API_KEY` | 🔴 **still the leaked value** — already revoked by Google. This is the only thing blocking Gemini. |
| `ALPHA_VANTAGE_KEY` | 🔴 **still the leaked value** — live and exposed. Rotate. |
| `GROQ_API_KEY` | 🟢 already rotated |

`.gitignore` correctly covers `.env` today, so this is historical — but deleting a file does not
remove it from history. **Rotating the keys is the fix; purging history is hygiene.**

### 1.2 🔴 The configured Groq models no longer exist

`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` — the hardcoded primary and fallback — both
return **404 "model does not exist"**. Groq retired them. Verified against the live API:

```
llama-3.3-70b-versatile: 404    llama-3.1-8b-instant: 404    openai/gpt-oss-120b: OK
```

Combined with a revoked Gemini key, **every LLM call in production was failing before this pass**.
The new defaults are models the account actually serves. The deeper lesson is §2 item 2: nothing
in the system noticed.

### 1.3 🟠 `aiohttp>=3.9.0` silently breaks Gemini

`google-genai`'s async transport references `aiohttp.ClientConnectorDNSError`, added in aiohttp
**3.10.6**. The installed 3.9.5 satisfied the old pin, so every Gemini call died with
`module aiohttp has no attribute ClientConnectorDNSError` — an error that *masked the real 403*.
Now pinned to `>=3.10.6`. Without this, "Gemini primary" would have silently never run.

### 1.4 🟠 The virtualenv is committed to git

`backend/venv/` is tracked: **12,669 of 12,763 tracked files — 99.3% of the repo** — totalling
35 MB and including 110 compiled `.so` binaries. `.git` is 94 MB. `.gitignore` lists `venv/`, but
that only affects untracked files; these were committed before the rule existed.

Three consequences:

- It is why the stale **Python 3.9** environment persists even though `runtime.txt` says 3.11 —
  the wrong interpreter's packages are pinned in version control.
- Any dependency change (this pass bumped `aiohttp`) shows up as dozens of modified tracked
  binaries, drowning real diffs.
- For a portfolio project this is the first thing a reader sees: twelve thousand files of
  vendored dependencies before any of your own code.

> **Note on this pass:** upgrading `aiohttp` to satisfy §1.3 modified ~70 tracked venv files.
> Do not revert them — aiohttp 3.9.5 breaks Gemini. Untracking the venv (Phase 1) makes the
> question moot.

### 1.5 🟠 What the new Gemini key revealed

After rotation the key worked, but three assumptions did not survive contact with the API.
All measured, not inferred:

| Assumption | Reality |
|---|---|
| `gemini-2.5-flash` is a safe default | **404 — "no longer available to new users."** The entire `gemini-2.5-*` family is gone for recently-created keys. |
| `thinking_budget=0` saves latency | **400 INVALID_ARGUMENT** on every Gemini 3.x model. Thinking cannot be disabled there, so the "optimisation" made 3.x unusable. The field is now sent only when explicitly configured. |
| An always-current alias is safest | `gemini-flash-latest`, `gemini-3.8-flash`, `gemini-3.7-flash` measured **0/3 — persistent `503 high demand`**. The newest models are the most over-subscribed; an alias trades a 404 for a 503, which fails *every* time instead of loudly once. |

Measured over 3 runs each, via the real provider code path:

| Model | Success | Median latency |
|---|---|---|
| `gemini-3.6-flash` | 3/3 | 3.8s |
| `gemini-3.5-flash` | 3/3 | 3.7s |
| `gemini-3.5-flash-lite` | 3/3 | **1.0s** |
| `gemini-flash-latest` / `3.8` / `3.7` | **0/3** | — (503) |

Two consequences for the chain:

- **The in-provider fallback is a different model, not a retry.** A 503 is a capacity signal for
  one model's pool; asking the same pool again changes nothing.
- **`GEMINI_RETRIES` now defaults to 0.** Across a full 6-agent run, *every* same-model retry
  after a 503/429 failed again. Removing them cut a run from 16 LLM calls to 11 with identical
  output.

A caveat the health probe now prints: **a model can be listed and still 404 on use.** Deprecated
models stay visible to the listing API, so `check_llm_health.py` without `--live` reported
`gemini-2.5-flash` as fine while every real call failed. Use `--live`.

---

## 2. The ten improvements

Ranked by (risk removed) ÷ (effort). Items 1–2 are incident follow-ups.

| # | Improvement | Why it matters | Effort |
|---|---|---|---|
| 1 | **Rotate leaked keys; purge `.env` from git history** | Two live keys are public. Gemini stays dead until rotated. | S |
| 2 | **Model & provider health probe** | A vendor retiring a model took the app down silently. Nothing alerted. | S |
| 3 | **Structured outputs via response schema** | Replaces regex-scraped JSON with a schema the model must satisfy. Removes a whole failure class. | M |
| 4 | **Prompt/token diet** | One run costs ~22.7k tokens; the whole Screener blob is dumped raw into the prompt, unbounded. | M |
| 5 | **Fix the module-level `asyncio.Semaphore`** | Loop-binding footgun; crashes under contention on Python 3.9. Also: local venv is 3.9, `runtime.txt` says 3.11. | S |
| 6 | **Cost + latency observability** | `by_provider()` exists now; nothing surfaces cost, p95, or the Gemini-vs-Groq split. One run took 84s on Groq. | M |
| 7 | **Cache the data layer, not just the verdict** | The slow, flaky part is data fetching. Repeated `LTIM.NS` 404s on every run. Caches are unbounded. | M |
| 8 | **API hardening** | CORS allows *any* `*.vercel.app` with credentials; no auth, no rate limit; `/api/debug/data` is public. | M |
| 9 | **Evaluation & backtest harness** | Verdict quality is entirely unmeasured. `.runlog/` already has the raw material. | L |
| 10 | **Untrack the venv; dependency cleanup** | 99.3% of the repo is a committed Python 3.9 venv. `langchain`, `langchain-community`, `duckduckgo-search` are unused. | S |

---

## 3. Phase-wise implementation

### Phase 0 — Stop the bleeding *(today)*

> Nothing else in this document matters while two live keys are public and the primary model is dead.

**Status: everything automatable is done ✅ — key rotation is the one open item 🔴 (only you can do it).**

#### a. Rotate the two exposed keys — blocking, and only you can do this

- [ ] **`GOOGLE_API_KEY`** — [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
      Create a new key, **delete the old one**, update `backend/.env` *and* the Render dashboard.
      Gemini stays dead until this is done: the current key returns
      `403 — "Your API key was reported as leaked."`
- [ ] **`ALPHA_VANTAGE_KEY`** — [alphavantage.co/support](https://www.alphavantage.co/support/#api-key).
      Still the leaked value, still live, not yet revoked by anyone.
- [ ] `GROQ_API_KEY` — ✅ already rotated, verified serving.

#### b. Verify the rotation — tooling ready

```bash
python scripts/audit_secrets.py          # exits 1 while any leaked value is still in use
python scripts/check_llm_health.py --live
```

[`audit_secrets.py`](scripts/audit_secrets.py) hashes your live `.env` against every `.env` blob in
history, so it proves rotation without ever printing a secret.
[`check_llm_health.py`](scripts/check_llm_health.py) probes each provider, checks the configured
model still exists, and with `--live` reports **which vendor actually served** the call — so
silently running on the fallback tier becomes visible instead of invisible.

Current output, for reference:

```
[!!] gemini   UNREACHABLE - 403 PERMISSION_DENIED ... reported as leaked
[ok] groq     reachable, serves openai/gpt-oss-120b, openai/gpt-oss-20b  (14 models)
```

#### c. Prevent recurrence — done ✅

- [x] **Pre-commit guard** installed ([`scripts/pre-commit`](scripts/pre-commit), via
      [`install-hooks.sh`](scripts/install-hooks.sh)). Zero dependencies. Blocks `.env` files,
      Google/Groq/OpenAI/AWS/JWT key patterns, and vendored dirs (`venv/`, `node_modules/`,
      `.next/`). Uses `gitleaks` as a second layer when installed.
      Verified against 7 cases — blocks `.env`, inline keys, JWTs and venv paths; allows clean
      files, `.env.example`, and the scanner itself.
- [x] **`gitleaks` config** ([`.gitleaks.toml`](.gitleaks.toml)) with a provider-key rule and
      an allowlist for templates. Optional: `brew install gitleaks`.
- [x] **GitHub-side audit.** Secret scanning and **push protection are already enabled** on the
      repo — so a recognised key pattern is now blocked at push time, server-side, independently
      of the local hook.
- [ ] **Two options remain off and must be set in the web UI.** The REST API accepts a PATCH for
      these fields with HTTP 200 but silently ignores it — verified twice; the values stay
      `disabled`. They are not settable via `gh api` for a personal-account repo.

      Repo → **Settings → Code security** → under *Secret protection*:
      - **Validity checks** — tells you whether a leaked secret is *still live*. Precisely the
        signal missing here: the Gemini key was revoked by Google before anything surfaced it.
      - **Non-provider patterns** — catches credentials GitHub has no first-party rule for.

      Validity checks may first need enabling at the account level:
      **github.com/settings/security_analysis**.

      `dependabot_security_updates` is also `disabled`; enabling it would have flagged the
      `aiohttp` issue in §1.3.

#### d. Purge history — done ✅

Ran [`scripts/purge-history.sh --execute`](scripts/purge-history.sh). A full mirror backup was
taken first, and **nothing was pushed** — the force-push is left to you.

| | Before | After |
|---|---|---|
| `.git` size | 93 MB | **548 KB** |
| Tracked files | 12,763 | **104** |
| `.env` blobs in history | 1 | **0** |
| `backend/venv` objects | ~12,850 | **0** |
| Commits | 60 | 59 (one venv-only commit became empty) |

The virtualenv was untracked in the same pass (`git rm -r --cached backend/venv`) — files remain
on disk, so the local environment still runs with the fixed `aiohttp 3.13.5`. Tests: 163 passing
after the rewrite.

Backup: `../Agentic-workflow-for-Indian-stock-financial-analysis-and-advise-backup-<ts>.git` (93 MB).
Keep it until you have pushed and are satisfied.

**One consequence worth understanding.** Purging the blob removed the very thing
`audit_secrets.py` was reading to detect unrotated keys — left alone it would have reported
"clean" the moment history was rewritten, while both keys were still leaked values. The hashes
are now pinned in [`scripts/leaked_hashes.json`](scripts/leaked_hashes.json) (one-way SHA-256
prefixes, safe to commit) and merged with any blobs still in history. Rewriting history cannot
silence the check that proves rotation happened.

**To publish the rewrite** — `filter-repo` drops the remote by design; it has been restored:

```bash
git push --force --all origin
git push --force --tags origin
```

The repo has **0 forks**, so no one else's clone breaks. Rotate the keys first: pushing does not
un-leak an already-scraped value.

**Exit criteria:** `audit_secrets.py` exits 0, and `check_llm_health.py --live` reports
`served by 'gemini'` with `primary_success_rate: 1.0`.

---

### Phase 1 — Reliability ✅ *(done)*

**Model & provider health probe (#2)**

- [x] `backend/llm/health.py` probes every provider concurrently, verifies the configured model
      IDs are served, and reports latency.
- [x] Surfaced at `GET /api/health`, with `?deep=true` (probe providers), `?live=true` (send a
      real completion) and `?models=true` (full model list). Shallow stays free — measured **0ms
      and no network**, because Render polls it.
- [x] `main.py` logs `CRITICAL` at startup when a provider is unhealthy, via a `lifespan` handler
      (not the deprecated `on_event`) running as a background task so a slow vendor cannot delay
      boot. `LLM_STARTUP_CHECK=0` disables it.
- [x] The two `@router.get("/health")` handlers are deduplicated — the second silently shadowed
      the first. A test asserts exactly one is registered.
- [x] `scripts/check_llm_health.py` is now a thin CLI over `llm.health` instead of a second
      implementation. It had already drifted once, reporting on a model the app no longer used.

**Concurrency & runtime (#5, #10)**

- [x] The analyst semaphore is built lazily inside the running loop. A test reproduces the exact
      5-analysts-against-3-slots contention that used to raise
      `got Future attached to a different loop`. A full local run no longer needs a workaround.
- [x] Virtualenv untracked (done in Phase 0).
- [x] `langchain`, `langchain-community` and `duckduckgo-search` dropped. **Verified, not
      assumed:** `langgraph` declares only `langchain-core`, and `langchain_core/globals.py`
      wraps `import langchain` in `try/except ImportError` behind a `_HAS_LANGCHAIN` flag.
- [ ] **Not done — rebuild the venv on Python 3.11.** Only 3.12 is installed on this machine, and
      installing 3.11 to match `runtime.txt` is your call. The lazy-semaphore fix removes the
      practical consequence, so this is now cosmetic rather than blocking.

**Result:** deep health green for both providers (gemini 794ms, groq 675ms); startup probe logs
healthy; full analysis runs end to end on Python 3.9 with no workaround.

---

### Phase 2 — Output quality ✅ *(done)*

**Structured outputs (#3)**

- [x] `backend/models/reports.py` defines a Pydantic model per agent — `FinancialReport`,
      `SentimentReport`, `TechnicalReport`, `RiskReport`, `MacroGovernanceReport`, `JudgeVerdict`.
- [x] Handed to Gemini as `response_schema`, so the model is *constrained* to the shape rather
      than asked for it. All six verified against the live API.
- [x] `parse_llm_json` retained for the Groq tier, whose `json_object` mode guarantees valid JSON
      but not the right shape. Every provider's output is validated.
- [x] Validation is **two-tier**, deliberately. Structural failures (unparseable, or no
      `summary`/`score`) raise and produce a degraded report with `score=None`, so the judge drops
      that pillar instead of weighing a fabricated number. Vocabulary drift is coerced —
      `"Under-Valued"` → `undervalued`, `confidence: 85` → `0.85`, `score: 65` → `10.0`. Rejecting
      a complete report over a cosmetic mismatch would cost a whole pillar for nothing.
- [x] **Deviation from the plan, on purpose.** The plan said to delete the JSON blocks from the
      prompts once the schema was authoritative. I did not: those blocks also carry *content*
      guidance a JSON Schema cannot express ("cite the exact FII number", "max 8 words"), so
      deleting them would trade a shape guarantee for worse content. The stated goal was
      preventing silent drift, so instead a test parses each prompt's JSON block by brace depth
      and asserts every key it requests exists on the schema. All six agents: **16 prompt keys,
      all modelled, zero extras.** Drift now fails the build.

Two vendor bugs found and fixed while wiring this up, both caught only by calling the real API:

- Pydantic emits `additionalProperties` for any model with `extra="allow"`, and Gemini answers
  *"additionalProperties is not supported"*. Fixed with `to_gemini_schema()` in the provider —
  a vendor quirk belongs at the vendor boundary, not in the contracts.
- `Optional[NestedModel]` becomes `anyOf: [$ref, null]`; leaving the `$ref` unresolved made
  Gemini fail with a bare `KeyError`. The sanitiser now inlines refs (with a cycle guard) and
  rewrites nullable unions.

**Prompt diet (#4)**

- [x] The Screener payload is summarised by `backend/data/screener_summary.py` instead of
      `json.dumps(..., indent=2)`: **5,571 → 858 chars, an 85% cut** on TCS, and bounded as
      Screener adds history.
- [x] **A latent data bug surfaced doing this.** Screener's row labels carry a *non-breaking
      space* — the Sales row arrives as `pl_Sales\xa0+`, not `pl_Sales`. Every
      `screener.get("pl_Sales")` returned `None`, so **Revenue CAGR and Profit CAGR rendered as
      "N/A" in every prompt this system has ever sent.** Lookups are now normalised; Revenue CAGR
      computes as 10.2% for TCS.
- [x] Per-agent prompt token budget (`AGENT_PROMPT_TOKEN_BUDGET`, default 6000) logs a warning
      when exceeded.
- [x] Remaining unbounded prompt inputs capped — insider records, announcements, macro history
      and the peer table were all uncapped `str(dict)` joins waiting for a busy register.

**Result, measured:**

| | Before | After |
|---|---|---|
| Tokens per run | 22,756 | **16,659** |
| Screener block | ~1,392 tok | **~214 tok** |
| Revenue CAGR in prompt | `N/A` always | 10.2% |
| JSON parse failures (12-call sweep) | — | **0** |
| Schema validation failures | — | **0** |

**Exit criteria: one met, one missed honestly.** Zero parse failures across the sweep ✅. Tokens
down **27%**, short of the 30% I estimated before measuring ❌ — and that 30% was a guess written
in advance, not a measurement. The remaining prompt weight is instruction text and worked
examples that drive output quality; cutting it to hit a number would trade real quality for a
cosmetic target. Note too that the 22,756 baseline was recorded on the old Groq/llama path, so
part of the delta is the model change, not the diet.

---

### Phase 3 — Cost & latency ✅ *(done)*

- [x] `backend/llm/pricing.py` prices every call; `estimated_cost_usd` is reported per record, per
      provider and per run.
      **The mechanism ships complete but the rates ship unset, deliberately.** The models this app
      defaults to are newer than any table that could be baked in with confidence, and inventing
      plausible rates for a tool that reports money is worse than reporting nothing — a wrong cost
      is believed, a missing one is questioned. An unpriced model yields `cost = None` and the UI
      shows "not set", never `$0.00`. Set `LLM_PRICING_JSON` (no redeploy needed on Render) and
      every run reports real money.
- [x] `by_provider` + cost persist into the run log and cached payload, and a **`RunStats` strip**
      now renders run cost, tokens, p50/p95 and — most usefully — *which provider actually served
      the run*. The backend had emitted `telemetry` since Phase 3 of the old plan; the frontend
      had never consumed it, so a run silently answered by the fallback tier looked identical to a
      healthy one.
- [x] p50/p95/max tracked overall **and per agent**, because the judge runs after all five
      analysts and sits on the critical path.
- [x] `ANALYST_CONCURRENCY` 3 → **5**, re-measured rather than inherited: the old value was set
      for Groq's TPM ceiling, and Gemini's limits are per-model RPM. At 5 the LLM phase ran
      **9.9s → 7.6s with zero failures**.
- [x] `JUDGE_THINKING_BUDGET` lets the judge opt into reasoning tokens — the one call that
      synthesises rather than extracts. Plumbed per-call so it cannot leak to the other five.

**Exit criteria:** cost reporting works, reading "not set" until rates are configured.
"P50 end-to-end under 20s" was **not** met by Phase 3 and could not be: a full run measured ~31s,
of which ~21s was upstream data fetching and ~8s was every LLM call combined. That pointed
straight at Phase 4 — where it is now comfortably met.

---

### Phase 4 — Data layer ✅ *(done)*

- [x] `backend/data/fetch_cache.py` caches at the **fetch** layer, keyed `(source, args,
      trading_day)`, applied to all 17 network fetchers. The trading-day component means an
      end-of-day payload is never served the next morning just because its TTL has not elapsed.
      TTLs track how fast each source actually moves: 30 min for news and market breadth, 1h for
      prices, 6–12h for fundamentals and governance, 24h for macro series.
- [x] **Negative caching.** A miss or an empty payload is cached with a *shorter* TTL, so
      `LTIM.NS` — which 404s from yfinance on every single run — stops costing full latency for a
      guaranteed failure, while a transient outage is not pinned for the day.
- [x] **Stale-while-revalidate.** If an entry has expired and the refetch fails, the last good
      payload is served with its original `as_of` instead of degrading an analyst to nothing.
      `freshness.py` already surfaces staleness in the UI, so old-but-labelled beats absent.
- [x] **Both directories bounded.** The fetch cache evicts expired entries then oldest-first past
      `FETCH_CACHE_MAX_ENTRIES` (500) / `FETCH_CACHE_MAX_BYTES` (32 MB); run logs prune to the
      newest `MAX_RUN_LOGS` (500). Cache size is reported by `GET /api/health?deep=true`.
- [x] `backend/data/providers.py` defines the `IFundamentalsProvider` seam the previous plan
      proposed and never built, with a `FallbackChain` that mirrors how the LLM router handles
      vendors — one source being down should degrade the run, not end it. `YFinanceFundamentals`
      satisfies the protocol structurally, so nothing existing had to be rewritten.

**Result, measured on a full TCS run:**

| | Cold cache | Warm cache |
|---|---|---|
| Total | 43.5s | **6.9s** |
| Data phase | 35.6s | **0.0s** |
| LLM phase | 7.8s | 6.9s |

**Exit criteria both met.** A warm second run does **zero** network I/O for fundamentals, and
neither directory can grow without bound. The payload round-trips cleanly through JSON — 252
history rows in and out, types preserved, `pd.DataFrame` builds identically — which was the real
risk in caching this layer.

This also settles Phase 3's latency target: a warm run is **6.9s end to end**, comfortably inside
the 20s goal. The cold path is still dominated by yfinance, which stays slow and rate-limited from
Render's IPs; the fix for that is a better feed behind the new provider seam, not more caching.

---

### Phase 5 — Hardening & evaluation *(week 4–5)*

**API hardening (#8)**

- [ ] [backend/main.py:25](backend/main.py#L25) — `allow_origin_regex=r"https://.*\.vercel\.app"`
      combined with `allow_credentials=True` lets **anyone's** Vercel deployment make credentialed
      cross-origin calls. Replace with an explicit `ALLOWED_ORIGINS` allowlist.
- [ ] Remove or auth-gate `GET /api/debug/data`
      ([backend/api/routes.py:302](backend/api/routes.py#L302)) — it is a public, unauthenticated
      endpoint that returns internal fetch state and full tracebacks.
- [ ] Rate-limit `/api/analyze/*`. Every call costs real tokens and there is currently no ceiling.
- [ ] Return generic error text to clients; keep `str(e)` in logs only. The SSE error path
      currently forwards raw exception strings to the browser.

**Evaluation (#9)**

- [ ] Golden-set regression: 15–20 tickers across sectors with a recorded expected band. Run
      nightly; alert when a verdict moves more than one band.
- [ ] Forward-return backtest over `.runlog/` — join past verdicts against 1M/3M realised returns.
      Target the previous plan's hit-rate > 55% on BUY/STRONG_BUY at 1M.
- [ ] Provider A/B: same ticker through Gemini and Groq, diff the verdicts. Quantifies what the
      fallback tier actually costs you in quality — right now that is a guess.
- [ ] Add CI (GitHub Actions): `pytest` on push. 163 tests exist and nothing runs them automatically.

**Exit criteria:** a dashboard answering "were we right?"; CI green on every push.

---

## 4. If you only have time for a third of this

1. **Phase 0** — non-negotiable, ~1 hour, and Gemini does not work until it is done.
2. **#2 health probe + #5 semaphore** — half a day, and together they close the exact failure
   mode that caused the outage.
3. **#3 structured outputs** — the single biggest verdict-quality lever, and cheapest now that
   Gemini is primary.

That is roughly a week and it converts the system from "silently broken" to "loudly correct."

---

## 5. Verification

```bash
cd backend

# Unit tests (163)
python -m pytest -q

# Which provider actually served the last run?
python -c "
import json,glob,os
f=max(glob.glob('.runlog/*.json'), key=os.path.getmtime)
t=json.load(open(f)).get('telemetry',{})
print(json.dumps({k:t.get(k) for k in
  ('total_calls','total_tokens','fallback_calls','failed_calls',
   'primary_success_rate','by_provider')}, indent=2))"
```

`primary_success_rate: 1.0` with `by_provider.gemini.successes > 0` and no Groq calls means
Gemini is primary and healthy. Anything less means you are silently running on the fallback tier.
