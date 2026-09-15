from typing import TypedDict, Optional, List, Dict, Any
from enum import Enum

class Decision(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"

class AgentReport(TypedDict, total=False):
    agent_name: str
    status: AgentStatus
    summary: str
    score: Optional[float]   # 0-10 (10 = most bullish). None when degraded.
    key_findings: List[str]
    risk_flags: List[str]
    signal_line: str         # ≤8 word signal for collapsed card
    data_table: List[Dict[str, str]]  # [{label, value, signal}] max 5 rows
    data: Dict[str, Any]
    confidence: float        # 0-1
    degraded: bool           # True when the agent could not produce a real score
    error: Optional[str]     # Short error message when degraded

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
    earnings_data: Optional[Dict]
    institutional_data: Optional[Dict]
    options_data: Optional[Dict]
    market_breadth: Optional[Dict]
    peer_data: Optional[Dict]
    relative_context: Optional[Dict]
    quality_metrics: Optional[Dict]
    indices: Optional[Dict]
    
    # Agent reports (populated as agents complete)
    financial_report: Optional[AgentReport]
    sentiment_report: Optional[AgentReport]
    risk_report: Optional[AgentReport]
    technical_report: Optional[AgentReport]
    macro_governance_report: Optional[AgentReport]
    
    # Final judgment
    final_decision: Optional[Decision]
    action: Optional[str]
    confidence_score: float       # 0-1 canonical wire format
    target_price_inr: Optional[float]
    max_entry_price: Optional[float]
    stop_loss_inr: Optional[float]
    time_horizon: Optional[str]   # "short" | "medium" | "long"
    investment_thesis: Optional[str]
    key_risks: List[str]
    key_catalysts: List[str]
    conviction_level: Optional[str]

    # Phase 2 — grounded targets + investor profile + governance vetos
    risk_profile: Optional[str]              # "conservative" | "balanced" | "aggressive"
    grounded_targets: Optional[Dict[str, Any]]
    veto: Optional[Dict[str, Any]]
    dissent_summary: Optional[str]

    # Scoring detail the judge already computes.
    #
    # These must be declared here or LangGraph drops them: a node's return is
    # merged into the state by key, and keys absent from this schema are
    # discarded silently. `judge_node` has been returning all five since Phase
    # 5, and all five were thrown away between the judge and the stream —
    # which is why "What would change this verdict?" never rendered anywhere,
    # and why no run log or cache entry carries a counter_factual.
    judge_score: Optional[float]
    score_attribution: Optional[Dict[str, Any]]
    strongest_pillar: Optional[str]
    weakest_pillar: Optional[str]

    # Phase 5 — "what would change this verdict?"
    counter_factual: Optional[Dict[str, Any]]

    # Phase 3 — data trust
    data_quality: Optional[Dict[str, Any]]
    llm_telemetry: Optional[Dict[str, Any]]
    stale_sources: Optional[List[str]]

    # Metadata
    error: Optional[str]
    run_id: str
