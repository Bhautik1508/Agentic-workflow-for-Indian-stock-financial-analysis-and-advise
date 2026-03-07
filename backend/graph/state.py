from typing import TypedDict, Optional, List, Dict, Any
from enum import Enum

class Decision(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"

class AgentReport(TypedDict):
    agent_name: str
    status: AgentStatus
    summary: str
    score: float          # 0-10 (10 = most bullish)
    key_findings: List[str]
    risk_flags: List[str]
    data: Dict[str, Any]
    confidence: float     # 0-1

class StockAnalysisState(TypedDict):
    # Input
    company_name: str
    ticker: str           # Resolved NSE ticker (e.g., "RELIANCE.NS")
    exchange: str         # "NSE" or "BSE"
    
    # Market data (populated by data fetcher node)
    price_data: Optional[Dict]
    fundamental_data: Optional[Dict]
    news_data: Optional[List[Dict]]
    
    # Advanced Data Sources added in Phase 10
    screener_data: Optional[Dict]
    fii_dii_data: Optional[Dict]
    gdelt_data: Optional[Dict]
    nse_data: Optional[Dict]
    risk_data: Optional[Dict]
    technical_data: Optional[Dict]
    macro_data: Optional[Dict]
    governance_data: Optional[Dict]
    
    # Agent reports (populated as agents complete)
    financial_report: Optional[AgentReport]
    sentiment_report: Optional[AgentReport]
    risk_report: Optional[AgentReport]
    technical_report: Optional[AgentReport]
    macro_governance_report: Optional[AgentReport]
    
    # Final judgment
    final_decision: Optional[Decision]
    confidence_score: float       # 0-100
    target_price_inr: Optional[float]
    stop_loss_inr: Optional[float]
    time_horizon: Optional[str]   # "short" | "medium" | "long"
    investment_thesis: Optional[str]
    key_risks: List[str]
    
    # Metadata
    error: Optional[str]
    run_id: str
