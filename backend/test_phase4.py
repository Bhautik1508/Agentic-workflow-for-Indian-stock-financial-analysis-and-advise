import sys
import asyncio
import unittest
sys.path.append('.')

from graph.state import StockAnalysisState
from agents.financial_analyst import run_financial_analysis
from agents.sentiment_analyst import run_sentiment_analysis
from agents.technical_analyst import run_technical_analysis
from agents.risk_analyst import run_risk_analysis
from agents.macro_analyst import run_macro_analysis
from agents.governance_analyst import run_governance_analysis

class TestPhase4(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.mock_state: StockAnalysisState = {
            "company_name": "TCS",
            "ticker": "TCS.NS",
            "exchange": "NSE",
            "price_data": {"current_price": 4000.0, "market_cap": 1400000000000},
            "fundamental_data": {"sector": "IT", "pe_ratio": 30.5},
            "news_data": [{"title": "TCS reports stellar earnings", "source": "Mint"}],
            "financial_report": None,
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
            "run_id": "test_phase_4_swarm"
        }

    async def test_financial_analyst(self):
        report = await run_financial_analysis(self.mock_state)
        self.assertEqual(report["agent_name"], "Financial Analyst")
        self.assertIn(report["status"], ["complete", "error"])

    async def test_sentiment_analyst(self):
        report = await run_sentiment_analysis(self.mock_state)
        self.assertEqual(report["agent_name"], "Sentiment Analyst")
        self.assertIn(report["status"], ["complete", "error"])
        
    async def test_technical_analyst(self):
        report = await run_technical_analysis(self.mock_state)
        self.assertEqual(report["agent_name"], "Technical Analyst")
        self.assertIn(report["status"], ["complete", "error"])

    async def test_risk_analyst(self):
        report = await run_risk_analysis(self.mock_state)
        self.assertEqual(report["agent_name"], "Risk Analyst")
        self.assertIn(report["status"], ["complete", "error"])
        
    async def test_macro_analyst(self):
        report = await run_macro_analysis(self.mock_state)
        self.assertEqual(report["agent_name"], "Macro Analyst")
        self.assertIn(report["status"], ["complete", "error"])

    async def test_governance_analyst(self):
        report = await run_governance_analysis(self.mock_state)
        self.assertEqual(report["agent_name"], "Governance Analyst")
        self.assertIn(report["status"], ["complete", "error"])

if __name__ == '__main__':
    unittest.main()
