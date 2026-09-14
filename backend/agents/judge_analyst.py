from agents.base_agent import get_llm, agent_with_fallback, call_llm_with_retry, parse_and_validate
from models.reports import JudgeVerdict
from graph.state import StockAnalysisState, AgentReport, AgentStatus
from scoring import (
    profile_weights, band_for_score, get_profile,
    evaluate_vetos,
    compute_fundamental_target, compute_technical_target, reconcile_targets,
    compute_counter_factual,
)

# Default ("balanced") weights — used when no profile is specified.
JUDGE_WEIGHTS = {
    "financial":   0.30,
    "technical":   0.23,
    "risk":        0.22,
    "sentiment":   0.12,
    "macro_gov":   0.13,
}

def adjust_for_low_confidence_sentiment(reports: dict, weights: dict) -> tuple[dict, dict]:
    """
    If sentiment report has low confidence (no news data), reduce its effective
    weight to half and redistribute the freed weight to Financial analyst.
    This prevents a data-absent 5.0-6.0 sentiment score from dragging strong
    fundamental stocks toward HOLD.
    """
    sentiment_report = reports.get("Sentiment Analyst", {})

    # In case data isn't a dict due to parsing fallback logic
    sentiment_data = sentiment_report.get("data", {}) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "data", {})
    sentiment_confidence = sentiment_report.get("confidence", 1.0) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "confidence", 1.0)

    # Safely get the news_available flag, default True so we don't accidentally halve it if missing
    news_available = sentiment_data.get("news_available", True) if isinstance(sentiment_data, dict) else True

    if not news_available or sentiment_confidence < 0.5:
        freed_weight = weights["sentiment"] * 0.5
        adjusted_weights = {**weights}
        adjusted_weights["sentiment"]  = weights["sentiment"] * 0.5
        adjusted_weights["financial"]  = weights["financial"] + freed_weight
        return reports, adjusted_weights

    return reports, weights


WEIGHTING_MAP = {
    "Financial Analyst":           "financial",
    "Technical Analyst":           "technical",
    "Risk Analyst":                "risk",
    "Sentiment Analyst":           "sentiment",
    "Macro & Governance Analyst":  "macro_gov",
}


def _is_degraded(report) -> bool:
    """A report is degraded if explicitly flagged or if score is missing/None."""
    if not isinstance(report, dict):
        return True
    if report.get("degraded") is True:
        return True
    if report.get("status") == AgentStatus.ERROR or report.get("status") == "error":
        return True
    if report.get("score") is None:
        return True
    return False


def drop_degraded_and_renormalize(reports: dict, weights: dict) -> tuple[dict, list[str]]:
    """Zero-out weights for degraded analysts and renormalize the remainder so the
    weighted score still sums to 1.0. Returns (effective_weights, degraded_agent_names)."""
    effective = {k: 0.0 for k in weights}
    degraded_agents: list[str] = []

    for agent_name, report in reports.items():
        key = WEIGHTING_MAP.get(agent_name)
        if not key:
            continue
        if _is_degraded(report):
            degraded_agents.append(agent_name)
        else:
            effective[key] = weights[key]

    total = sum(effective.values())
    if total <= 0:
        # All five agents degraded — return original weights so caller can detect
        # and force a NEUTRAL/HOLD with low confidence downstream.
        return weights, degraded_agents

    # Renormalize so live agents' weights sum back to 1.0
    return {k: v / total for k, v in effective.items()}, degraded_agents

JUDGE_SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) at a top Indian hedge fund.
You synthesise 5 specialist reports into a DECISIVE verdict. You are paid
to make calls — not to default to HOLD.

SCORING BANDS:
STRONG_BUY : score >= 7.5 — All pillars aligned, clear catalyst, strong setup
BUY        : score 6.0–7.5 — Good quality, decent setup, acceptable risk
HOLD       : score 4.5–6.0 — Genuinely mixed signals or awaiting confirmation
SELL       : score 3.0–4.5 — Deteriorating fundamentals or broken trend
STRONG_SELL: score < 3.0 — Governance red flags or structural collapse

DECISION RULES (apply these, do not override with intuition):
- If 3+ analysts score >= 6.5: verdict is BUY unless Risk score < 4.0
- If Financial >= 7.0 AND Technical >= 6.0: verdict is BUY unless Risk < 4.0
- If Risk < 4.0 AND Financial < 5.0 simultaneously: verdict is SELL
- A 5.5 no-news sentiment for a Nifty50 stock = NEUTRAL (not negative)
- A profitable company with 10-15% growth is at minimum a 6.5 financial score

WEIGHTS (default 'balanced' profile): Financial 30% | Technical 23% | Risk 22% | Macro/Gov 13% | Sentiment 12%
Conservative profile up-weights Risk and Financial; aggressive up-weights Technical and Sentiment.
Use the EFFECTIVE weights provided in the prompt — they may differ from the defaults above.

ALWAYS produce a dissent_summary explaining which analysts disagree with the verdict and why
they were over-ridden. If all analysts align, say so.

Output ONLY valid JSON. No preamble."""

JUDGE_USER_PROMPT = """
Synthesise the following 5 specialist reports for {company_name} ({ticker}).

━━━ ANALYST SCORES & SIGNALS ━━━
{analyst_reports}

━━━ SENTIMENT WEIGHT NOTE ━━━
Sentiment news_available: {sentiment_news_available}
Effective sentiment weight: {effective_sentiment_weight}
{sentiment_weight_note}

━━━ PRE-COMPUTED WEIGHTED SCORE ━━━
Mathematical weighted score: {weighted_score}/10
(Use as baseline. Adjust based on your CIO judgement and the rules above.)

━━━ KEY CONTEXT ━━━
Financial valuation: {val_verdict} | Health: {fin_health}
Technical trend: {tech_trend} | Signal: {tech_signal}
Risk level: {risk_level} | Macro: {macro_env} | Governance: {gov_quality}

Return JSON with this EXACT schema:
{{
  "summary": "<1-paragraph conviction synthesis>",
  "action": "STRONG_BUY"|"BUY"|"HOLD"|"SELL"|"STRONG_SELL",
  "score": <float 0-10>,
  "confidence": <float 0.0-1.0>,
  "investment_thesis": "<3-4 sentence compelling narrative>",
  "key_catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "target_price": <float INR>,
  "max_entry_price": <float INR>,
  "stop_loss": <float INR>,
  "time_horizon": "short_term"|"medium_term"|"long_term",
  "conviction_level": "high"|"medium"|"low",
  "strongest_pillar": "financial"|"technical"|"risk"|"sentiment"|"macro_governance",
  "weakest_pillar": "financial"|"technical"|"risk"|"sentiment"|"macro_governance",
  "score_attribution": {{
    "financial": "<score and 1-sentence reason>",
    "technical": "<score and 1-sentence reason>",
    "risk": "<score and 1-sentence reason>",
    "sentiment": "<score and 1-sentence reason>",
    "macro_governance": "<score and 1-sentence reason>"
  }},
  "dissent_summary": "<2-3 sentences naming the analyst(s) most at odds with the verdict and why you over-rode them>"
}}
"""



@agent_with_fallback("Judge Analyst", default_score=5.0)
async def run_judge_analyst(state: StockAnalysisState) -> AgentReport:
    """Run the final judge analysis to synthesize reports into a verdict."""
    client = get_llm()
    raw_reports = state.get("analyst_reports", {})

    # 0. Profile selection (Phase 2). Profile drives weights AND verdict bands.
    profile_name, _ = get_profile(state.get("risk_profile") or "")
    base_weights = profile_weights(profile_name)

    # 1. Apply low-confidence sentiment adjustment (existing behaviour)
    reports, weights_after_sentiment = adjust_for_low_confidence_sentiment(raw_reports, base_weights)

    # 2. Drop degraded analysts entirely; renormalize remaining weights
    effective_weights, degraded_agents = drop_degraded_and_renormalize(reports, weights_after_sentiment)

    # Calculate mathematical baseline weighted score using only live agents.
    calculated_score = 0.0
    for agent_name, report in reports.items():
        key = WEIGHTING_MAP.get(agent_name)
        if not key or _is_degraded(report):
            continue
        score = report.get("score")
        if score is None:
            continue
        calculated_score += float(score) * effective_weights[key]

    weighted_score = round(calculated_score, 2)
    all_degraded = len(degraded_agents) >= len(WEIGHTING_MAP)
    
    # Get sentiments flags for the prompt inclusion
    sentiment_report = reports.get("Sentiment Analyst", {})
    sentiment_confidence = sentiment_report.get("confidence", 1.0) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "confidence", 1.0)
    sentiment_data = sentiment_report.get("data", {}) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "data", {})
    sentiment_news_available = sentiment_data.get("news_available", True) if isinstance(sentiment_data, dict) else True
    effective_sentiment_weight = effective_weights["sentiment"]
    
    if not sentiment_news_available or sentiment_confidence < 0.5:
        sentiment_weight_note = "NOTE: Sentiment score is based on FII/DII data only (no news).\\n Its weight has been halved. Do not let the sentiment score override strong fundamental\\n or technical signals. A 6.0 no-news sentiment for a Nifty50 stock is a NEUTRAL signal,\\n not a negative one — treat it accordingly."
    else:
        sentiment_weight_note = "Sentiment data is robust. Weight remains standard."

    # Format all reports into a readable string
    reports_text = ""
    for agent_name, report in reports.items():
        if _is_degraded(report):
            err = report.get("error") if isinstance(report, dict) else None
            reports_text += f"[{agent_name.upper()}] DEGRADED — excluded from weighted score. Reason: {err or 'unknown'}\\n\\n"
            continue
        if report and isinstance(report, dict) and report.get("status") == AgentStatus.COMPLETE:
            reports_text += f"[{agent_name.upper()}]\\n"
            reports_text += f"Score: {report.get('score', 0)}/10 | Confidence: {report.get('confidence', 0.0)}\\n"

            # Check based on dict access
            if "Macro" in agent_name:
                env = report.get("data", {}).get("macro_environment", "Unknown") if isinstance(report.get("data"), dict) else "Unknown"
                gov = report.get("data", {}).get("governance_quality", "Unknown") if isinstance(report.get("data"), dict) else "Unknown"
                reports_text += f"Macro: {env} | Governance: {gov}\\n"
            elif "Technical" in agent_name:
                trend = report.get("data", {}).get("trend", "Unknown") if isinstance(report.get("data"), dict) else "Unknown"
                reports_text += f"Trend: {trend}\\n"

            reports_text += f"Summary: {report.get('summary', '')}\\n"
            reports_text += f"Findings: {'; '.join(report.get('key_findings', []))}\\n"
            if report.get("risk_flags"):
                reports_text += f"Risks: {'; '.join(report.get('risk_flags', []))}\\n"
            reports_text += "\\n"

    if not reports_text: reports_text = "No reports generated."

    if degraded_agents:
        reports_text += (
            f"\\n━━━ DEGRADED AGENTS ━━━\\n"
            f"The following analysts failed and were excluded from the weighted score: "
            f"{', '.join(degraded_agents)}.\\n"
            f"Cap your confidence accordingly — fewer pillars means less conviction.\\n"
        )

    fin_rep = raw_reports.get("Financial Analyst", {}) or {}
    tech_rep = raw_reports.get("Technical Analyst", {}) or {}
    risk_rep = raw_reports.get("Risk Analyst", {}) or {}
    sent_rep = raw_reports.get("Sentiment Analyst", {}) or {}
    macro_rep = raw_reports.get("Macro & Governance Analyst", {}) or {}
    
    fin_data = fin_rep.get("data", {}) if isinstance(fin_rep, dict) else {}
    tech_data = tech_rep.get("data", {}) if isinstance(tech_rep, dict) else {}
    risk_data = risk_rep.get("data", {}) if isinstance(risk_rep, dict) else {}
    macro_data = macro_rep.get("data", {}) if isinstance(macro_rep, dict) else {}

    val_verdict = fin_data.get('valuation_verdict', 'N/A')
    fin_health  = fin_data.get('financial_health', 'N/A')
    tech_trend  = tech_data.get('trend', 'N/A')
    tech_signal = tech_rep.get('signal_line', 'N/A') if isinstance(tech_rep, dict) else 'N/A'
    risk_level  = risk_data.get('risk_level', 'N/A')
    macro_env   = macro_data.get('macro_environment', 'N/A')
    gov_quality = macro_data.get('governance_quality', 'N/A')

    prompt = JUDGE_USER_PROMPT.format(
        company_name=state.get("company_name", "Unknown"),
        ticker=state.get("ticker", "UNKNOWN"),
        analyst_reports=reports_text,
        sentiment_news_available="True" if sentiment_news_available else "False",
        effective_sentiment_weight=effective_sentiment_weight,
        sentiment_weight_note=sentiment_weight_note,
        weighted_score=weighted_score,
        
        val_verdict=val_verdict,
        fin_health=fin_health,
        tech_trend=tech_trend,
        tech_signal=tech_signal,
        risk_level=risk_level,
        macro_env=macro_env,
        gov_quality=gov_quality
    )

    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        agent="Judge Analyst",
        response_schema=JudgeVerdict,
    )

    result = parse_and_validate(text, JudgeVerdict, "Judge Analyst")

    # If all five pillars are degraded, the verdict is structurally meaningless.
    # Force a HOLD with floor confidence so we don't surface a false-confident BUY/SELL.
    if all_degraded:
        result["action"] = "HOLD"
        result["confidence"] = 0.1
        result["summary"] = (
            "All specialist analyses degraded — verdict cannot be relied upon. "
            "Showing HOLD as a safe default."
        )

    # Cap confidence: each degraded analyst removes 15% of nominal confidence.
    elif degraded_agents:
        penalty = 0.15 * len(degraded_agents)
        cap = max(0.1, 1.0 - penalty)
        try:
            current = float(result.get("confidence", 0.0) or 0.0)
            result["confidence"] = min(current, cap)
        except (TypeError, ValueError):
            result["confidence"] = cap

    # ── Phase 2 — band-floor check based on profile ──
    # If LLM returned an action that doesn't match the math under this profile,
    # snap the action to the band the weighted score deserves. The LLM still
    # owns the narrative; the math owns the band.
    try:
        score_for_band = float(result.get("score", weighted_score) or weighted_score)
    except (TypeError, ValueError):
        score_for_band = weighted_score
    profile_band = band_for_score(score_for_band, profile_name)
    if not all_degraded and result.get("action") != profile_band:
        result["band_disagreement"] = {
            "llm_action": result.get("action"),
            "profile_band": profile_band,
            "score_used": score_for_band,
            "profile": profile_name,
        }
        result["action"] = profile_band

    # ── Phase 2 — apply hard veto rules ──
    veto = evaluate_vetos(
        fundamental_data=state.get("fundamental_data"),
        governance_data=state.get("governance_data"),
        nse_data=state.get("nse_data"),
        risk_report=raw_reports.get("Risk Analyst"),
    )
    if veto.triggered and veto.forced_verdict:
        result["action"] = veto.forced_verdict
        result["confidence"] = max(result.get("confidence", 0.0) or 0.0, veto.forced_confidence or 0.0)
        # Keep the LLM's narrative summary but prepend the veto reason for honesty
        prefix = "VETO: " + "; ".join(veto.reasons[:2]) + ". "
        existing = result.get("summary", "")
        if not existing.startswith("VETO:"):
            result["summary"] = prefix + existing

    # ── Phase 2 — grounded targets (override LLM target/stop with math) ──
    grounded = _build_grounded_targets(state, profile_name, llm_target=result.get("target_price"))
    if grounded.target_price is not None:
        result["target_price"] = grounded.target_price
    if grounded.stop_loss is not None:
        result["stop_loss"] = grounded.stop_loss
    result["grounded_targets"] = grounded.to_dict()
    result["risk_profile"] = profile_name
    result["effective_weights"] = effective_weights
    result["veto"] = veto.to_dict()

    # ── Phase 5 — counter-factual: 'what would change this verdict?' ──
    pillar_scores: dict = {}
    for agent_name, key in WEIGHTING_MAP.items():
        rep = raw_reports.get(agent_name)
        if isinstance(rep, dict) and rep.get("score") is not None and not _is_degraded(rep):
            try:
                pillar_scores[key] = float(rep["score"])
            except (TypeError, ValueError):
                pass
    risk_pillar_score = pillar_scores.get("risk")
    cf = compute_counter_factual(
        weighted_score=weighted_score,
        current_band=result.get("action") or "HOLD",
        pillar_scores=pillar_scores,
        weights=effective_weights,
        profile=profile_name,
        risk_pillar_score=risk_pillar_score,
    )
    result["counter_factual"] = cf.to_dict()

    return AgentReport(
        agent_name="Judge Analyst",
        status=AgentStatus.COMPLETE,
        summary=result.get("summary", ""),
        score=result.get("score"),
        confidence=result.get("confidence", 0.0),
        key_findings=result.get("key_findings", []),
        risk_flags=result.get("risk_flags", []),
        data=result
    )


def _build_grounded_targets(state: StockAnalysisState, profile_name: str, *, llm_target=None):
    """Pure helper — extracts the inputs grounded_pricing needs and returns the result.

    Lives outside the LLM call so it can be unit-tested without mocking Groq."""
    fundamental = state.get("fundamental_data") or {}
    price = state.get("price_data") or {}
    risk = state.get("risk_data") or {}
    technical = state.get("technical_data") or {}
    peer = state.get("peer_data") or {}

    current_price = price.get("current_price") or fundamental.get("current_price")
    forward_eps = fundamental.get("forward_eps") or fundamental.get("eps_forward")
    sector_median_pe = peer.get("sector_median_pe") if isinstance(peer, dict) else None

    # Forward EPS may be missing — derive from price/PE as a fallback.
    fundamental_target = compute_fundamental_target(
        forward_eps,
        sector_median_pe,
        fallback_eps_from_pe=(current_price, fundamental.get("pe_ratio")),
    )
    technical_target = compute_technical_target(
        current_price,
        week_52_high=price.get("week_52_high"),
        fib_1618=technical.get("fib_1618") or technical.get("fib_extension_1618"),
        nearest_resistance=technical.get("nearest_resistance"),
        analyst_target=fundamental.get("analyst_target_price"),
    )

    _, profile_spec = get_profile(profile_name)
    return reconcile_targets(
        current_price=current_price,
        fundamental_target=fundamental_target,
        technical_target=technical_target,
        llm_target=llm_target,
        analyst_target=fundamental.get("analyst_target_price"),
        atr_14=risk.get("atr_14") or technical.get("atr_14"),
        volatility_1y_pct=risk.get("volatility_1y"),
        profile_max_size=profile_spec.get("max_position_size", 1.0),
    )
