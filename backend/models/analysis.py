from pydantic import BaseModel, Field
from typing import List, Optional

class BaseAgentOutput(BaseModel):
    summary: str = Field(..., description="2-3 sentence overall assessment")
    score: float = Field(..., description="0-10 score, where 10 is extremely bullish")
    key_findings: List[str]
    risk_flags: List[str]
    confidence: float = Field(..., description="0-1 confidence score of the assessment")

class FinancialAgentOutput(BaseAgentOutput):
    pe_assessment: str = Field(..., description="undervalued|fairly_valued|overvalued")
    financial_health: str = Field(..., description="excellent|good|average|poor")
    growth_trend: str = Field(..., description="accelerating|stable|declining")

class SentimentAgentOutput(BaseAgentOutput):
    news_sentiment: str = Field(..., description="very_positive|positive|neutral|negative|very_negative")
    fii_dii_stance: str = Field(..., description="buying|neutral|selling")
    news_volume: str = Field(..., description="high|normal|low")

class JudgeOutput(BaseModel):
    decision: str = Field(..., description="BUY | SELL | HOLD")
    confidence_score: int = Field(..., description="0-100 score representing certainty")
    investment_thesis: str = Field(..., description="3-4 sentence compelling thesis")
    target_price_inr: float = Field(..., description="12-month target price in INR")
    stop_loss_inr: float = Field(..., description="Recommended stop loss in INR")
    time_horizon: str = Field(..., description="short_term | medium_term | long_term")
    weighted_score: float = Field(..., description="0-10 weighted average of all analysts")
    key_catalysts: List[str]
    key_risks: List[str]
    position_sizing: str = Field(..., description="aggressive | moderate | conservative")
    suitable_for: str = Field(..., description="growth_investor | value_investor | trader | income_investor")
