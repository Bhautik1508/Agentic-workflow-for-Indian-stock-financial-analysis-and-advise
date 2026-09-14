"""Pydantic schemas for agent output.

Why
---
Every prompt describes its JSON shape in prose, and `parse_llm_json` scrapes
whatever comes back with a regex. Nothing connects the two, so the prompt and
the consumer can drift apart silently — and a model that returns a *plausible*
but wrong shape produces a confident, wrong verdict rather than an error.

These models are the single definition of each agent's contract. They are:

  1. handed to Gemini as `response_schema`, so the model is *constrained* to
     the shape instead of merely asked for it, and
  2. used to validate whatever any provider returns, including Groq's, whose
     `json_object` mode guarantees valid JSON but not the right shape.

Strictness policy
-----------------
Deliberately two-tier, because "reject anything imperfect" would throw away a
usable report over a cosmetic difference and cost the judge a whole pillar:

  * **Structural** problems fail loudly — unparseable JSON, or a missing
    `summary`/`score`. Those make the report meaningless, and the degraded-report
    path already handles them (score=None, weight dropped, confidence capped).
  * **Vocabulary** drift is coerced — an enum-ish field that comes back as
    "Bullish" or "very bullish" when we expected one of a fixed set is
    normalised to the nearest legal value, or to a documented default.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _coerce(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """Normalise a free-text enum into the allowed set.

    Tries exact match, then a case/spacing-insensitive match, then a substring
    match ("very bullish trend" -> "bullish"), then gives up and returns the
    documented default rather than failing the whole report.
    """
    if value is None:
        return default
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if text in allowed:
        return text
    # Separator-insensitive: "Under-Valued" -> "undervalued".
    squashed = text.replace("_", "")
    for option in allowed:
        if squashed == option.replace("_", ""):
            return option
    for option in allowed:
        if option in text or text in option:
            return option
    return default


def enum_field(allowed: tuple[str, ...], default: str):
    """Build a (field, validator) pair for a coerced enum field."""
    def validator(cls, v):  # noqa: N805
        return _coerce(v, allowed, default)
    return validator


class DataTableRow(BaseModel):
    """One row of an analyst card's metric table."""
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    value: str = ""
    signal: str = "neutral"

    @field_validator("value", "label", mode="before")
    @classmethod
    def _stringify(cls, v):
        # Models sometimes emit a bare number where a display string is wanted.
        return "" if v is None else str(v)

    @field_validator("signal", mode="before")
    @classmethod
    def _signal(cls, v):
        return _coerce(v, ("positive", "neutral", "negative"), "neutral")


class BaseAgentOutput(BaseModel):
    """Fields every analyst returns. `summary` and `score` are load-bearing:
    without them the judge has nothing to weigh, so they are required."""
    model_config = ConfigDict(extra="allow")   # keep agent-specific extras

    summary: str
    score: float = Field(ge=0.0, le=10.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_line: str = ""
    data_table: List[DataTableRow] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)

    @field_validator("key_findings", "risk_flags", mode="before")
    @classmethod
    def _as_str_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(item) for item in v]

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, v):
        """Clamp into 0-10 rather than reject.

        Whether a score EXISTS is structural — without it the judge has nothing
        to weigh. Whether it is 10.5 instead of 10 is not worth discarding an
        otherwise complete report and dropping a whole pillar of the verdict.
        """
        try:
            return max(0.0, min(10.0, float(v)))
        except (TypeError, ValueError):
            raise ValueError("score must be a number")

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_scale(cls, v):
        """Some models answer 85 when asked for 0.85. Treat >1 as a percentage
        rather than clamping to 1.0 and silently overstating certainty."""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return f / 100.0 if f > 1.0 else f


class FinancialReport(BaseAgentOutput):
    valuation_verdict: str = "fairly_valued"
    pe_premium_discount_pct: float = 0.0
    financial_health: str = "average"
    growth_quality: str = "moderate"
    pe_vs_history: str = ""
    moat_assessment: str = ""
    earnings_risk: str = "moderate"
    earnings_quality: str = "unknown"
    target_price_fundamental: Optional[float] = None

    _v1 = field_validator("valuation_verdict", mode="before")(
        enum_field(("undervalued", "fairly_valued", "overvalued"), "fairly_valued"))
    _v2 = field_validator("financial_health", mode="before")(
        enum_field(("excellent", "good", "average", "poor"), "average"))
    _v3 = field_validator("growth_quality", mode="before")(
        enum_field(("high_quality", "moderate", "low_quality", "declining"), "moderate"))
    _v4 = field_validator("earnings_risk", mode="before")(
        enum_field(("very_high", "high", "moderate", "low"), "moderate"))
    _v5 = field_validator("earnings_quality", mode="before")(
        enum_field(("consistently_beating", "mostly_beating", "mixed",
                    "consistently_missing", "unknown"), "unknown"))


class SentimentReport(BaseAgentOutput):
    news_sentiment: str = "no_data"
    fii_dii_stance: str = "unknown"
    sentiment_trend: str = "unknown"
    news_available: bool = False
    base_score_used: float = 5.0
    fii_dii_adjustment: float = 0.0
    dominant_event: str = "none"
    key_news_event: str = ""
    event_impact: str = "none"

    _v1 = field_validator("news_sentiment", mode="before")(
        enum_field(("very_positive", "positive", "neutral", "negative",
                    "very_negative", "no_data"), "no_data"))
    _v2 = field_validator("fii_dii_stance", mode="before")(
        enum_field(("both_buying", "fii_buying_dii_selling", "fii_selling_dii_buying",
                    "both_selling", "mixed", "unknown"), "unknown"))
    _v3 = field_validator("sentiment_trend", mode="before")(
        enum_field(("improving", "stable", "deteriorating", "unknown"), "unknown"))
    _v4 = field_validator("event_impact", mode="before")(
        enum_field(("positive", "neutral", "negative", "none"), "none"))


class TechnicalReport(BaseAgentOutput):
    trend: str = "sideways"
    momentum: str = "neutral"
    volume_confirmation: bool = False
    immediate_support: Optional[float] = None
    immediate_resistance: Optional[float] = None
    technical_target: Optional[float] = None
    stop_loss_technical: Optional[float] = None
    chart_pattern: str = "none"
    entry_zone: str = ""
    options_signal: str = "unavailable"
    key_resistance_options: Optional[float] = None
    key_support_options: Optional[float] = None
    market_tailwind: bool = False

    _v1 = field_validator("trend", mode="before")(
        enum_field(("strong_uptrend", "uptrend", "sideways", "downtrend",
                    "strong_downtrend"), "sideways"))
    _v2 = field_validator("momentum", mode="before")(
        enum_field(("overbought", "bullish", "neutral", "bearish", "oversold"), "neutral"))
    _v3 = field_validator("options_signal", mode="before")(
        enum_field(("bullish", "neutral", "bearish", "unavailable"), "unavailable"))


class RiskReport(BaseAgentOutput):
    company_specific_risks: List[str] = Field(default_factory=list)
    macro_sector_risks: List[str] = Field(default_factory=list)
    risk_level: str = "moderate"
    beta_category: str = "market_like"
    financial_risk: str = "moderate"
    liquidity_risk: str = "moderate"
    event_risk: str = "moderate"
    max_loss_estimate: str = ""
    recommended_stop_loss_buffer: float = 8.0
    position_size_modifier: float = Field(default=1.0, ge=0.0, le=1.0)
    suitable_for: List[str] = Field(default_factory=list)
    risk_score: Optional[float] = None

    _lists = field_validator("company_specific_risks", "macro_sector_risks",
                             "suitable_for", mode="before")(
        BaseAgentOutput._as_str_list.__func__)  # type: ignore[attr-defined]
    _v1 = field_validator("risk_level", mode="before")(
        enum_field(("very_low", "low", "moderate", "high", "very_high"), "moderate"))
    _v2 = field_validator("beta_category", mode="before")(
        enum_field(("defensive", "market_like", "aggressive"), "market_like"))
    _v3 = field_validator("financial_risk", "liquidity_risk", "event_risk", mode="before")(
        enum_field(("very_low", "low", "moderate", "high"), "moderate"))


class GovernanceScoreDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")
    promoter_holding: float = 5.0
    pledge_risk: float = 5.0
    insider_activity: float = 5.0
    board_quality: float = 5.0
    disclosure_quality: float = 5.0


class MacroGovernanceReport(BaseAgentOutput):
    macro_environment: str = "neutral"
    governance_quality: str = "average"
    promoter_confidence: str = "moderate"
    insider_signal: str = "neutral"
    rate_cycle_impact: str = "neutral"
    sector_macro_tailwind: bool = False
    promoter_signal: str = "unknown"
    governance_veto_risk: bool = False
    macro_tailwind: bool = False
    currency_impact: str = "neutral"
    governance_score_detail: Optional[GovernanceScoreDetail] = None

    _v1 = field_validator("macro_environment", mode="before")(
        enum_field(("very_supportive", "supportive", "neutral", "headwind",
                    "severe_headwind"), "neutral"))
    _v2 = field_validator("governance_quality", mode="before")(
        enum_field(("excellent", "good", "average", "poor", "concerning"), "average"))
    _v3 = field_validator("promoter_confidence", mode="before")(
        enum_field(("high", "moderate", "low"), "moderate"))
    _v4 = field_validator("insider_signal", mode="before")(
        enum_field(("strong_buy", "buy", "neutral", "sell", "strong_sell"), "neutral"))
    _v5 = field_validator("rate_cycle_impact", "currency_impact", mode="before")(
        enum_field(("positive", "neutral", "negative"), "neutral"))
    _v6 = field_validator("promoter_signal", mode="before")(
        enum_field(("accumulating", "stable", "reducing", "unknown"), "unknown"))


class JudgeVerdict(BaseModel):
    """The judge's own contract. `action` and `score` drive the whole verdict,
    so they are required; the narrative fields are not."""
    model_config = ConfigDict(extra="allow")

    summary: str
    action: str
    score: float = Field(ge=0.0, le=10.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    investment_thesis: str = ""
    key_catalysts: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    target_price: Optional[float] = None
    max_entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    time_horizon: str = "medium_term"
    conviction_level: str = "medium"
    strongest_pillar: str = ""
    weakest_pillar: str = ""
    score_attribution: Dict[str, str] = Field(default_factory=dict)
    dissent_summary: str = ""

    _lists = field_validator("key_catalysts", "key_risks", mode="before")(
        BaseAgentOutput._as_str_list.__func__)  # type: ignore[attr-defined]
    _conf = field_validator("confidence", mode="before")(
        BaseAgentOutput._confidence_scale.__func__)  # type: ignore[attr-defined]
    _score = field_validator("score", mode="before")(
        BaseAgentOutput._clamp_score.__func__)  # type: ignore[attr-defined]
    _v1 = field_validator("action", mode="before")(
        enum_field(("strong_buy", "buy", "hold", "sell", "strong_sell"), "hold"))
    _v2 = field_validator("time_horizon", mode="before")(
        enum_field(("short_term", "medium_term", "long_term"), "medium_term"))
    _v3 = field_validator("conviction_level", mode="before")(
        enum_field(("high", "medium", "low"), "medium"))

    @field_validator("action", mode="after")
    @classmethod
    def _upper(cls, v: str) -> str:
        # The rest of the pipeline compares against STRONG_BUY / BUY / ...
        return v.upper()

    @field_validator("score_attribution", mode="before")
    @classmethod
    def _attribution_to_str(cls, v):
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items()}


SCHEMA_BY_AGENT = {
    "Financial Analyst": FinancialReport,
    "Sentiment Analyst": SentimentReport,
    "Technical Analyst": TechnicalReport,
    "Risk Analyst": RiskReport,
    "Macro & Governance Analyst": MacroGovernanceReport,
    "Judge Analyst": JudgeVerdict,
}
