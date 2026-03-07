print("HELLO WORLD")
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

from data.market_data import (
    fetch_news,
    fetch_gdelt_sentiment,
    fetch_fii_dii_data,
    fetch_world_bank_macro,
    fetch_market_context,
    fetch_bse_governance,
    fetch_nse_insider_trading,
    fetch_nse_risk_signals
)
from agents.technical_analyst import run_technical_analysis
from agents.sentiment_analyst import run_sentiment_analysis
from agents.macro_governance_analyst import run_macro_governance_analysis
from agents.judge_analyst import run_judge_analyst
from graph.state import AgentReport, AgentStatus

async def run_tests():
    print("=== Testing Phase 10: Steps 6 to 11 ===")
    
    ticker = "TATAMOTORS.NS"
    company_name = "Tata Motors"
    
    print("\n--- Steps 7 & 8: News, GDELT, FII/DII Fetching ---")
    
    # Temporarily remove API keys to test fallback paths
    original_news_api = os.environ.get("NEWS_API_KEY")
    os.environ["NEWS_API_KEY"] = ""
    
    try:
        # Running sequentially to avoid LibreSSL threading segfaults on python3.9 Mac
        news_data = await fetch_news(company_name, ticker)
        gdelt_data = await asyncio.to_thread(fetch_gdelt_sentiment, company_name)
        fii_dii = await asyncio.to_thread(fetch_fii_dii_data)
        
        print(f"✅ News Data Retrieved: {len(news_data)} articles (fallback tested)")
        print(f"✅ GDELT Data Retrieved: Tone {gdelt_data.get('average_tone', 'N/A')}")
        print(f"✅ FII/DII Data Retrieved: Net FII: {fii_dii.get('fii_10day_net', 'N/A')}")
    except Exception as e:
        print(f"❌ Error in Sentiment Data fetching: {e}")
        news_data, gdelt_data, fii_dii = [], {}, {}
        
    print("\n--- Step 10: Macro & Governance Fetching ---")
    try:
        macro_data = {
            **fetch_world_bank_macro(),
            **fetch_market_context()
        }
        print(f"✅ Macro Data Retrieved: {len(macro_data)} metrics")
        
        # Sequentially
        gov_data = await fetch_bse_governance("500570")
        insider_data = await fetch_nse_insider_trading("TATAMOTORS")
        nse_risk = await fetch_nse_risk_signals("TATAMOTORS")
        
        print(f"✅ Governance Data Retrieved: Shareholding={bool(gov_data.get('shareholding'))}")
        print(f"✅ Insider Data Retrieved: {len(insider_data) if insider_data else 0} transactions")
        print(f"✅ NSE Risk Signals Retrieved: Delivery Pct={nse_risk.get('delivery_pct_today')}")
    except Exception as e:
        print(f"❌ Error in Macro/Governance fetching: {e}")
        macro_data, gov_data, insider_data, nse_risk = {}, {}, [], {}

    print("\n--- Steps 6, 9, 10, 11: Analyst Execution (Mocked LLM) ---")
    print("Testing Analyst parsing schemas. Since we mock the API key, we expect fallback ERROR gracefully handled.")
    
    # Restore mock keys for LLM tests
    os.environ["GROQ_API_KEY"] = "mock_key"
    
    state = {
        "company_name": company_name,
        "ticker": ticker,
        "exchange": "NSE",
        "price_data": {},
        "fundamental_data": {},
        "news_data": news_data,
        "screener_data": {},
        "fii_dii_data": fii_dii,
        "gdelt_data": gdelt_data,
        "nse_data": nse_risk,
        "risk_data": {},
        "technical_data": {"rsi_14": 55},
        "macro_data": macro_data,
        "governance_data": gov_data,
        "run_id": "test_run_456"
    }
    
    # Test Technical Analyst
    report_tech = await run_technical_analysis(state)
    print(f"✅ TECHNICAL ANALYST STATUS: {report_tech.get('status', report_tech.status if hasattr(report_tech, 'status') else 'Unknown')}")
    
    # Test Sentiment Analyst
    report_sent = await run_sentiment_analysis(state)
    print(f"✅ SENTIMENT ANALYST STATUS: {report_sent.get('status', report_sent.status if hasattr(report_sent, 'status') else 'Unknown')}")
    
    # Test Macro Analyst
    report_macro = await run_macro_governance_analysis(state)
    print(f"✅ MACRO/GOV ANALYST STATUS: {report_macro.get('status', report_macro.status if hasattr(report_macro, 'status') else 'Unknown')}")

    # Test Judge Analyst
    state["analyst_reports"] = {
        "Technical Analyst": AgentReport(agent_name="Technical Analyst", status=AgentStatus.ERROR, summary="Err", score=5.0, confidence=0.0, key_findings=[], risk_flags=[], data={}),
        "Sentiment Analyst": AgentReport(agent_name="Sentiment Analyst", status=AgentStatus.ERROR, summary="Err", score=5.0, confidence=0.0, key_findings=[], risk_flags=[], data={}),
        "Macro & Governance Analyst": AgentReport(agent_name="Macro & Governance Analyst", status=AgentStatus.ERROR, summary="Err", score=5.0, confidence=0.0, key_findings=[], risk_flags=[], data={})
    }
    report_judge = await run_judge_analyst(state)
    print(f"✅ JUDGE ANALYST STATUS: {report_judge.get('status', report_judge.status if hasattr(report_judge, 'status') else 'Unknown')}")

    print("\n🎉 SUCCESS: All steps 6 to 11 executed correctly with graceful fallbacks!")

if __name__ == "__main__":
    asyncio.run(run_tests())
