import sys
import os
import unittest
# Make sure we can import from backend dir
sys.path.append('.')

from graph.state import Decision, AgentStatus, AgentReport, StockAnalysisState
from agents.base_agent import get_llm
from models.analysis import BaseAgentOutput

class TestPhase3(unittest.TestCase):
    
    def test_agent_status_enum(self):
        """Test the AgentStatus Enum"""
        self.assertEqual(AgentStatus.PENDING, "pending")
        self.assertEqual(AgentStatus.RUNNING, "running")
        self.assertEqual(AgentStatus.COMPLETE, "complete")
        self.assertEqual(AgentStatus.ERROR, "error")

    def test_decision_enum(self):
        """Test the Decision Enum"""
        self.assertEqual(Decision.BUY, "BUY")
        self.assertEqual(Decision.HOLD, "HOLD")
        self.assertEqual(Decision.SELL, "SELL")
        
    def test_stock_analysis_state_typing(self):
        """Test that we can create a mock state dict matching StockAnalysisState"""
        mock_report: AgentReport = {
            "agent_name": "Financial Analyst",
            "status": AgentStatus.COMPLETE,
            "summary": "Looks good.",
            "score": 8.5,
            "key_findings": ["Growing revenue"],
            "risk_flags": [],
            "data": {"pe_assessment": "undervalued"},
            "confidence": 0.9
        }
        
        mock_state: StockAnalysisState = {
            "company_name": "Reliance",
            "ticker": "RELIANCE.NS",
            "exchange": "NSE",
            "price_data": {},
            "fundamental_data": {},
            "news_data": [],
            "financial_report": mock_report,
            "sentiment_report": None,
            "risk_report": None,
            "technical_report": None,
            "macro_report": None,
            "governance_report": None,
            "final_decision": None,
            "confidence_score": 0.0,
            "target_price_inr": None,
            "stop_loss_inr": None,
            "time_horizon": None,
            "investment_thesis": None,
            "key_risks": [],
            "error": None,
            "run_id": "test_123"
        }
        
        self.assertEqual(mock_state["ticker"], "RELIANCE.NS")
        self.assertEqual(mock_state["financial_report"]["score"], 8.5)

    def test_base_agent_output_schema(self):
        """Test the structural validity of the base pydantic schema for agent output"""
        test_output = BaseAgentOutput(
            summary="Test summary",
            score=7.5,
            key_findings=["Finding 1", "Finding 2"],
            risk_flags=["Risk 1"],
            confidence=0.85
        )
        self.assertEqual(test_output.score, 7.5)
        self.assertEqual(len(test_output.key_findings), 2)

    def test_get_llm_initialization(self):
        """Test if LLM initializes correctly. Mocks API key if missing."""
        # Ensure we have a dummy API key to avoid pydantic validation error
        original_key = os.environ.get("GOOGLE_API_KEY")
        if not original_key:
            os.environ["GOOGLE_API_KEY"] = "dummy_key_for_testing"
            
        try:
            llm = get_llm()
            self.assertEqual(llm.model, "gemini-1.5-flash")
            self.assertEqual(llm.temperature, 0.1)
        finally:
            if not original_key:
                del os.environ["GOOGLE_API_KEY"]
            else:
                os.environ["GOOGLE_API_KEY"] = original_key

if __name__ == '__main__':
    unittest.main()
