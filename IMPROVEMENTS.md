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

Default chain: `gemini-2.5-flash` → `gemini-2.5-flash` (one retry) → `openai/gpt-oss-120b` → `openai/gpt-oss-20b`.
A tier with no API key is skipped, so the app still runs on one provider.

Configure entirely from env — a model decommission becomes a dashboard change, not a redeploy:

```bash
LLM_PRIMARY_PROVIDER=gemini   # or groq, to invert the chain
GEMINI_MODEL=gemini-2.5-flash
GEMINI_RETRIES=1              # extra Gemini attempts before dropping to Groq
GEMINI_THINKING_BUDGET=0      # 0 = thinking off (fast). Raise for deeper judge reasoning.
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

A full `run_stock_analysis("Tata Consultancy Services")` completed with all five analysts plus
the judge, producing `BUY | conf 0.80 | target ₹2563.70 | stop ₹2088.96`. With the Gemini key
currently revoked (§1.1), all 14 calls failed over to Groq and the run still succeeded — which
is the failover behaviour working as designed. Test suite: **163 passing**.

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

**Status: tooling built ✅ — key rotation still pending 🔴 (only you can do it).**

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

#### d. Purge history — prepared, awaiting your go-ahead ⏸

[`scripts/purge-history.sh`](scripts/purge-history.sh) removes `backend/.env` **and**
`backend/venv` from all history in one rewrite. Dry-run by default; it **never pushes** — the
irreversible step stays a deliberate act.

```bash
brew install git-filter-repo
bash scripts/purge-history.sh              # dry run
bash scripts/purge-history.sh --execute    # local rewrite + automatic mirror backup
```

Dry run reports: `backend/.env` ~7 objects, `backend/venv` ~12,847 objects, `.git` currently 94 MB.

**The repo has 0 forks**, so the usual objection to rewriting public history — breaking other
people's clones — does not apply here. This is about as safe as a force-push gets.

Order matters: rotate first, then purge. Purging does not un-leak an already-scraped key; it only
stops the dead values being re-harvested and reclaims the 94 MB.

**Exit criteria:** `audit_secrets.py` exits 0, and `check_llm_health.py --live` reports
`served by 'gemini'` with `primary_success_rate: 1.0`.

---

### Phase 1 — Reliability *(week 1)*

**Model & provider health probe (#2)**

- [ ] Add `llm/health.py`: for each configured provider, list models and assert the configured ID
      is present; return `{provider, model, reachable, model_exists, latency_ms}`.
- [ ] Surface it at `GET /api/health?deep=true`. Keep the shallow check cheap for Render's poller.
- [ ] Fail loudly at startup (log `CRITICAL`) when the primary model is unreachable — the outage
      above lasted because the failure was invisible.
- [ ] Deduplicate the two `@router.get("/health")` handlers in
      [backend/api/routes.py:36](backend/api/routes.py#L36) and
      [backend/api/routes.py:298](backend/api/routes.py#L298) — the second silently shadows the first.

**Concurrency & runtime (#5, #10)**

- [ ] Make the analyst semaphore lazy in [backend/graph/workflow.py:17](backend/graph/workflow.py#L17).
      A module-level `asyncio.Semaphore()` binds the import-time loop on Python 3.9 and throws
      `got Future attached to a different loop` once more than `ANALYST_CONCURRENCY` analysts
      contend. Production pins 3.11 where this is benign — but it is a live trap for anyone
      running the repo's own venv, which is Python 3.9.
      ```python
      _analyst_semaphore: asyncio.Semaphore | None = None

      def _get_semaphore() -> asyncio.Semaphore:
          global _analyst_semaphore
          if _analyst_semaphore is None:
              _analyst_semaphore = asyncio.Semaphore(ANALYST_CONCURRENCY)
          return _analyst_semaphore
      ```
- [ ] **Untrack the virtualenv** — the single highest-leverage cleanup in this document:
      ```bash
      git rm -r --cached backend/venv        # .gitignore already covers it
      git commit -m "chore: untrack committed virtualenv"
      ```
      Removes 12,669 files from the tree. To reclaim the 94 MB of history as well, run
      `git filter-repo --path backend/venv --invert-paths` in the same pass as the `.env` purge
      in Phase 0 — one history rewrite, one force-push, one coordination cost.
- [ ] Rebuild the local venv on Python 3.11 to match `runtime.txt`. The committed venv is 3.9.6
      and already emits end-of-life warnings from `google-auth`.
- [ ] Drop `langchain`, `langchain-community`, `duckduckgo-search` from `requirements.txt` —
      none are imported anywhere in `backend/`. Verify with a clean install before merging;
      `langgraph` needs `langchain-core`, which it pulls itself.

**Exit criteria:** deep health check is green; test suite passes on Python 3.11; cold start measurably faster.

---

### Phase 2 — Output quality *(week 2)*

Gemini as primary makes both of these cheaper to do than before.

**Structured outputs (#3)**

- [ ] Define a Pydantic model per agent (`FinancialReport`, `TechnicalReport`, …, `JudgeVerdict`)
      mirroring the JSON schema each prompt currently describes in prose.
- [ ] Pass it to Gemini as `response_schema` + `response_mime_type="application/json"` — the SDK
      already supports this and `GeminiProvider` just needs the field plumbed through.
- [ ] Keep [`parse_llm_json`](backend/agents/base_agent.py#L53) as the Groq-tier fallback; Groq's
      `json_object` mode guarantees valid JSON but not the right *shape*.
- [ ] Validate on the way out. A schema violation should produce a **degraded** report — the
      machinery for that already exists and the judge already handles it.
- [ ] Delete the hand-written JSON schema blocks from the prompts once the schema is authoritative.
      Today the prompt and the parser can drift apart with nothing catching it.

**Prompt diet (#4)**

- [ ] [backend/agents/financial_analyst.py:154](backend/agents/financial_analyst.py#L154) dumps the
      entire Screener payload via `json.dumps(screener, indent=2)` with no cap. Summarise to the
      rows the prompt actually cites (Sales, Net Profit, ROCE, ROE — last 5 years) and drop `indent=2`.
- [ ] Add a token budget per agent; log when a prompt exceeds it.
- [ ] Measure before/after with the existing `total_tokens` telemetry. Baseline: **22,756 tokens/run**.

**Exit criteria:** zero JSON parse failures across a 20-ticker sweep; tokens per run down ≥30%.

---

### Phase 3 — Cost & latency *(week 3)*

- [ ] Add a per-model price table (`llm/pricing.py`, input/output per 1M tokens) and compute
      `estimated_cost_usd` per record and per run. Maintain it by hand — it is a dozen numbers,
      and wrong-but-visible beats absent.
- [ ] Persist `by_provider` + cost into the run log and the cached payload, then surface a small
      "run cost / latency / provider" strip in the UI. The data already flows through the
      `telemetry` SSE event.
- [ ] Track p50/p95 per agent. The observed Groq path spent **84.8s across 8 calls** — the judge
      is serialised behind all five analysts, so it lands on the critical path.
- [ ] Revisit `ANALYST_CONCURRENCY = 3` once Gemini is primary; Gemini's limits differ from Groq's,
      and the value was chosen for Groq's TPM ceiling.
- [ ] Consider `GEMINI_THINKING_BUDGET > 0` for the judge only — it synthesises rather than
      extracts, so it is the one call where deliberation plausibly pays.

**Exit criteria:** every run reports a cost; P50 end-to-end under 20s.

---

### Phase 4 — Data layer *(week 3–4)*

- [ ] Cache at the **fetch** layer, keyed `(source, ticker, trading_day)`. The verdict cache in
      [backend/data/cache.py](backend/data/cache.py) only helps on a repeat of the *same* analysis;
      the expensive, flaky work is upstream.
- [ ] Add negative caching. `LTIM.NS` 404s from yfinance on every single run and is re-fetched each time.
- [ ] Bound both caches. `.cache/` and `.runlog/` grow without eviction — fine at 164K/72K today,
      not fine after a thousand runs on an ephemeral Render disk.
- [ ] Stale-while-revalidate: serve the last good payload with an `as_of` stamp rather than
      degrading an analyst, since [`freshness.py`](backend/data/freshness.py) already surfaces staleness in the UI.
- [ ] Implement the `IFundamentalsProvider` interface the previous plan proposed but never built —
      it is the precondition for ever swapping in a paid feed.

**Exit criteria:** a warm second run does no network I/O for fundamentals; no unbounded directory.

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
