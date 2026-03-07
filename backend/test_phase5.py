import asyncio
import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.append('.')

from graph.runner import run_stock_analysis

async def test_workflow():
    print("=========================================")
    print("🧠 StockSage AI: LangGraph Workflow Tester")
    print("=========================================\n")
    
    company_name = input("Enter a company name (e.g., 'tata motors', 'reliance', 'hdfc'): ").strip()
    if not company_name:
        return
        
    print(f"\n🚀 Starting full workflow test for: {company_name}")
    
    try:
        async for event in run_stock_analysis(company_name):
            if event["event"] == "status":
                print(f"ℹ️ {event['data']}")
            elif event["event"] == "node_update":
                node_name = event["node"]
                print(f"✅ Node Finished: {node_name}")
                if node_name == "judge_node":
                    state = event["state"]
                    
                    reports = state.get("analyst_reports", {})
                    if reports:
                        print("\n=========================================")
                        print("📊 AGENT REPORTS")
                        print("=========================================\n")
                        for agent, rep in reports.items():
                            status_icon = "✅" if rep.get("status") in ["SUCCESS", "success", "COMPLETE", "complete"] else "❌"
                            print(f"[{agent.replace('_analyst', '').replace('_node', '').title()} Analyst] {status_icon} SCORE: {rep.get('score', 'N/A')}/10 ")
                            print(f"   Summary: {rep.get('summary', 'No summary generated.')}")
                            print(f"   Findings: {rep.get('key_findings', [])}")
                            if rep.get('risk_flags'):
                                print(f"   Risks: {rep.get('risk_flags')}")
                            print("\n--------------------------------------------------")
                            
                    print("\n=================")
                    print("🎉 FINAL JUDGMENT")
                    print("=================")
                    print(f"Decision: {state.get('final_decision')}")
                    print(f"Confidence: {state.get('confidence_score')}")
                    print(f"Thesis: {state.get('investment_thesis')}")
                    print(f"Risks: {state.get('key_risks')}")
            elif event["event"] == "complete":
                 print(f"🎉 {event['data']}")
                 
    except Exception as e:
        print(f"❌ Error during execution: {e}")

if __name__ == "__main__":
    asyncio.run(test_workflow())
