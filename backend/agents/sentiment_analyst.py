import re
from agents.base_agent import get_llm, parse_llm_json, agent_with_fallback, call_llm_with_retry
from graph.state import StockAnalysisState, AgentReport, AgentStatus

def compute_news_stats(news_items: list, fii_dii: dict) -> dict:
    """
    Computes structured news stats to pass into the LLM prompt.
    Prevents the LLM from defaulting to 5.0 when data is absent.
    """
    if not news_items:
        return {
            "news_available":         False,
            "news_volume":            "none",
            "article_count":          0,
            "marketaux_avg_sentiment": None,
            "positive_count":         0,
            "negative_count":         0,
            "neutral_count":          0,
            "fii_10day_net":          fii_dii.get("fii_10day_net", 0),
            "dii_10day_net":          fii_dii.get("dii_10day_net", 0),
            "fii_stance":             fii_dii.get("fii_stance", "unknown"),
            "dii_stance":             fii_dii.get("dii_stance", "unknown"),
        }

    sentiments = [
        float(a["sentiment"]) for a in news_items
        if a.get("sentiment") is not None
    ]
    avg = round(sum(sentiments) / len(sentiments), 3) if sentiments else None

    return {
        "news_available":          True,
        "news_volume":             "high" if len(news_items) > 10 else "normal" if len(news_items) > 3 else "low",
        "article_count":           len(news_items),
        "marketaux_avg_sentiment": avg,
        "positive_count":          sum(1 for s in sentiments if s > 0.1),
        "negative_count":          sum(1 for s in sentiments if s < -0.1),
        "neutral_count":           sum(1 for s in sentiments if -0.1 <= s <= 0.1),
        "fii_10day_net":           fii_dii.get("fii_10day_net", 0),
        "dii_10day_net":           fii_dii.get("dii_10day_net", 0),
        "fii_stance":              fii_dii.get("fii_stance", "unknown"),
        "dii_stance":              fii_dii.get("dii_stance", "unknown"),
    }

SENTIMENT_SYSTEM_PROMPT = """
You are a Market Sentiment Analyst specializing in Indian equities at a leading Mumbai-based
hedge fund. You have deep expertise in interpreting news flow, FII/DII behavior, and social
sentiment signals for NSE/BSE-listed companies.

You understand India-specific sentiment drivers:
- Promoter buying/selling signals
- RBI policy impact on banking/NBFC sentiment
- FII behavior during global risk-on/risk-off cycles
- How Budget announcements affect sector sentiment
- The significance of management guidance in quarterly results
- Impact of SEBI/CCI/government regulatory actions

━━━ SCORING RULES — FOLLOW EXACTLY ━━━

STEP 1 — ESTABLISH BASE SCORE FROM NEWS AVAILABILITY:

  Case A: News available (article_count > 0)
    → Base score = derived entirely from actual news sentiment
    → Use the marketaux_avg_sentiment and article tone as primary signal
    → Ignore this step and go directly to Step 2

  Case B: No news available (article_count = 0) + stock is Nifty50 / large-cap blue chip
    → Base score = 6.0
    → Rationale: absence of negative news IS a positive signal for a well-covered large-cap.
      Analysts and media watch these stocks closely — no news means no scandal, no miss, no crisis.

  Case C: No news available (article_count = 0) + stock is mid-cap or small-cap
    → Base score = 5.0
    → Rationale: low coverage means genuine uncertainty, not safety.

STEP 2 — ADJUST FOR FII/DII 10-DAY NET FLOW:

  Apply these adjustments ON TOP of the base score from Step 1:

  Both FII and DII net buying   → +1.0
  FII buying, DII selling       → +0.5  (FII is the stronger signal)
  FII selling, DII buying       → -0.3  (DII cushions but FII is leading indicator)
  Both FII and DII net selling  → -1.5
  FII/DII data unavailable      → +0.0  (no adjustment)

STEP 3 — APPLY NEWS EVENT OVERRIDE (if a single dominant event exists in last 7 days):

  Major positive event (earnings beat >10%, buyback, major contract, upgrade):
    → Score = max(current_score, 7.5)

  Major negative event (earnings miss >10%, RBI penalty, management exit, fraud):
    → Score = min(current_score, 3.5)

  Routine event (dividend, AGM, index rebalance, minor analyst note):
    → No override, keep Step 2 score

STEP 4 — FINAL SCORE RULES:

  → Round final score to nearest 0.5 increment:
    Use only: 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0

  → You MUST NOT give exactly 5.0 unless BOTH of these are true:
      (a) There are BOTH positive AND negative news signals actively present
      (b) FII and DII flows are near-zero or conflicting

  → Clamp final score: minimum 1.0, maximum 9.5

━━━ SCORE MEANING REFERENCE ━━━
  1.0–2.5  = Active crisis (fraud / SEBI ban / accounting scandal)
  3.0–4.0  = Clearly negative (earnings miss, regulatory penalty, management exit)
  4.5–5.0  = Mildly negative OR genuine conflict of signals
  5.5–6.0  = Mildly positive / no-news large-cap default
  6.5–7.0  = Positive (in-line results, sector tailwind, FII buying)
  7.5–8.5  = Strong positive (earnings beat, buyback, major win)
  9.0–9.5  = Exceptional (re-rating event, transformational deal)

━━━ SUMMARY FIELD REQUIREMENTS ━━━
Your "summary" field MUST explicitly mention:
  1. How many news articles were found (e.g. "0 articles found" or "12 articles found")
  2. The exact FII/DII net flow number in ₹ Crore (e.g. "FII net sold ₹1,240 Cr in 10 days")
  3. The base score you started with and why (Case A/B/C from Step 1)
  4. What adjustment was applied in Step 2 and the final score

Example of a GOOD summary (no news, large-cap, FII buying):
  "No news articles found for ICICIBANK in the last 7 days, indicating absence of any
  negative catalysts — starting at base score 6.0 (large-cap Case B). FII net bought
  ₹3,420 Cr over the last 10 days (+1.0 adjustment), DII net sold ₹890 Cr (-0.0 since
  FII dominates). Final score: 7.0."

Example of a BAD summary (DO NOT DO THIS):
  "The overall sentiment is neutral due to a lack of recent news and mixed signals."
  [This is wrong — it doesn't cite numbers, doesn't follow the scoring rules, defaults to 5.0]

Output ONLY valid JSON. No preamble, no explanation outside the JSON.
"""

SENTIMENT_USER_PROMPT = """
Analyze market sentiment for {company_name} ({ticker}).

━━━ COMPANY CLASSIFICATION ━━━
Sector:       {sector}
Market Cap:   ₹{market_cap_cr} Crore
Index Member: {index_membership}
  → Use this for Case B vs Case C base score decision (Nifty50 = large-cap Case B)

━━━ NEWS DATA ━━━
Articles Found (last 7 days): {article_count}
News Volume: {news_volume}
Marketaux Average Sentiment Score: {marketaux_avg_sentiment}
  (scale: -1.0 = very negative, 0.0 = neutral, +1.0 = very positive)
Positive Articles: {positive_count}
Negative Articles: {negative_count}
Neutral Articles:  {neutral_count}

News Headlines:
{news_items_formatted}
[If empty: "NO NEWS ARTICLES FOUND IN LAST 7 DAYS"]

━━━ FII / DII ACTIVITY (Last 10 Trading Days) ━━━
FII Net Flow: ₹{fii_10day_net} Crore → Stance: {fii_stance}
DII Net Flow: ₹{dii_10day_net} Crore → Stance: {dii_stance}
Daily breakdown:
{fii_dii_daily_table}

━━━ GDELT GLOBAL SENTIMENT ━━━
Article Count: {gdelt_article_count}
Average Tone:  {gdelt_avg_tone}
  (GDELT scale: +5 = positive, -5 = negative, 0 = neutral)
Sample Headlines: {gdelt_headlines}

━━━ RECENT CORPORATE EVENTS ━━━
{recent_corporate_events}
(e.g., quarterly results, AGM, board meeting, dividend, fundraise, management change)

━━━ SCORING CHECKLIST — COMPLETE BEFORE GENERATING JSON ━━━

Before writing your JSON, answer these sequentially:

Q1: How many news articles were found?
    Answer: {article_count} articles
    → If 0: Is {company_name} a Nifty50/large-cap? {is_large_cap}
      YES → Base score = 6.0 (Case B)
      NO  → Base score = 5.0 (Case C)
    → If >0: Derive base score from actual news sentiment

Q2: What is the FII 10-day net flow?
    Answer: ₹{fii_10day_net} Crore
    → Apply FII/DII adjustment from scoring rules

Q3: Is there one dominant event in last 7 days that overrides?
    Answer: {dominant_event_exists} — {dominant_event_description}
    → Apply override if yes

Q4: What is the final score after Steps 1+2+3?
    → Round to nearest 0.5

Q5: Can you justify giving exactly 5.0?
    → Only if BOTH positive AND negative signals exist simultaneously

Provide output as JSON with this exact schema:
{{
    "summary": "<MUST include: article count + FII/DII exact numbers + base score reasoning + final score — see system prompt example>",
    "score": <float — must be a 0.5 increment, e.g. 5.5 or 6.0 or 7.5>,
    "confidence": <float 0.0–1.0 — use 0.4–0.6 when no news, 0.7–0.9 when news available>,
    "key_findings": [
        "<finding 1: news availability and volume — cite exact count>",
        "<finding 2: FII net flow with exact ₹ Crore number and interpretation>",
        "<finding 3: DII net flow with exact ₹ Crore number and interpretation>",
        "<finding 4: most significant news event if any, or 'no significant events'>",
        "<finding 5: GDELT global sentiment reading>"
    ],
    "risk_flags": [
        "<specific negative signal with data — or 'none identified' if truly absent>"
    ],
    "news_sentiment": "very_positive" | "positive" | "neutral" | "negative" | "very_negative" | "no_data",
    "fii_dii_stance": "both_buying" | "fii_buying_dii_selling" | "fii_selling_dii_buying" | "both_selling" | "mixed" | "unknown",
    "sentiment_trend": "improving" | "stable" | "deteriorating" | "unknown",
    "news_available":  true | false,
    "base_score_used": <float — the Step 1 base before FII/DII adjustment>,
    "fii_dii_adjustment": <float — the exact +/- applied in Step 2, e.g. +1.0 or -0.3>,
    "dominant_event": "<description of override event, or 'none'>",
    "key_news_event": "<single most important news item, or 'No significant news in last 7 days'>",
    "event_impact": "positive" | "neutral" | "negative" | "none"
}}
"""

@agent_with_fallback("Sentiment Analyst", default_score=5.0)
async def run_sentiment_analysis(state: StockAnalysisState) -> AgentReport:
    """Run sentiment and news analysis."""
    client = get_llm()
    news  = state.get("news_data", [])
    fii   = state.get("fii_dii_data", {})
    info  = state.get("fundamental_data", {})
    price = state.get("price_data", {})

    # Compute stats before sending to LLM
    stats = compute_news_stats(news, fii)

    # Determine large-cap status (Nifty50 market cap threshold ~₹50,000 Cr)
    market_cap_cr = (info.get("market_cap") or 0) / 1e7
    is_large_cap  = market_cap_cr > 50000

    # Determine index membership
    index_membership = "Nifty50" if market_cap_cr > 100000 else \
                       "Nifty100" if market_cap_cr > 50000 else \
                       "Nifty500" if market_cap_cr > 10000 else "Small/Mid Cap"

    # Format news items for prompt
    news_items_formatted = "\\n".join([
        f"- {a.get('title', '?')} | Source: {a.get('source','?')} | Sentiment: {a.get('sentiment','?')} | {a.get('date','')[:10]}"
        for a in news[:15]
    ]) if news else "NO NEWS ARTICLES FOUND IN LAST 7 DAYS"

    # Format FII/DII daily table
    daily = fii.get("daily_records", [])
    fii_dii_daily_table = "\\n".join([
        f"  {d.get('date','')}: FII ₹{d.get('fii_net_buy_sell','?')} Cr | DII ₹{d.get('dii_net_buy_sell','?')} Cr"
        for d in daily[:7]
    ]) if daily else "FII/DII daily data unavailable"

    # Dominant event detection (simple heuristic)
    dominant_keywords_positive = ["buyback", "bonus", "beat", "record profit", "acquisition", "order win"]
    dominant_keywords_negative = ["fraud", "penalty", "ban", "miss", "resignation", "default", "sebi notice"]
    dominant_event_exists = False
    dominant_event_description = "none"
    for a in news[:5]:
        title_lower = (a.get("title") or "").lower()
        if any(kw in title_lower for kw in dominant_keywords_positive):
            dominant_event_exists = True
            dominant_event_description = f"POSITIVE: {a.get('title')}"
            break
        if any(kw in title_lower for kw in dominant_keywords_negative):
            dominant_event_exists = True
            dominant_event_description = f"NEGATIVE: {a.get('title')}"
            break

    prompt = SENTIMENT_USER_PROMPT.format(
        company_name              = state["company_name"],
        ticker                    = state["ticker"],
        sector                    = info.get("sector", "Unknown"),
        market_cap_cr             = round(market_cap_cr, 0),
        index_membership          = index_membership,
        is_large_cap              = "YES" if is_large_cap else "NO",
        article_count             = stats["article_count"],
        news_volume               = stats["news_volume"],
        marketaux_avg_sentiment   = stats["marketaux_avg_sentiment"] or "N/A (no articles)",
        positive_count            = stats["positive_count"],
        negative_count            = stats["negative_count"],
        neutral_count             = stats["neutral_count"],
        news_items_formatted      = news_items_formatted,
        fii_10day_net             = stats["fii_10day_net"],
        dii_10day_net             = stats["dii_10day_net"],
        fii_stance                = stats["fii_stance"],
        dii_stance                = stats["dii_stance"],
        fii_dii_daily_table       = fii_dii_daily_table,
        gdelt_article_count       = state.get("gdelt_data", {}).get("article_count", 0),
        gdelt_avg_tone            = state.get("gdelt_data", {}).get("avg_tone", "N/A"),
        gdelt_headlines           = "\\n".join(state.get("gdelt_data", {}).get("sample_headlines", ["N/A"])),
        recent_corporate_events   = state.get("corporate_events", "None identified"),
        dominant_event_exists     = "YES" if dominant_event_exists else "NO",
        dominant_event_description = dominant_event_description,
    )

    messages = [
        {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    # Use the robust LLM caller with fallback
    text = await call_llm_with_retry(
        client=client,
        messages=messages
    )

    data = parse_llm_json(text)

    return AgentReport(
        agent_name   = "Sentiment Analyst",
        status       = AgentStatus.COMPLETE,
        summary      = data["summary"],
        score        = float(data["score"]),
        key_findings = data["key_findings"],
        risk_flags   = data.get("risk_flags", []),
        confidence   = float(data["confidence"]),
        data         = data,
    )
