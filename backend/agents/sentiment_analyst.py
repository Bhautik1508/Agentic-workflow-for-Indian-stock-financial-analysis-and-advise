import json
from agents.base_agent import get_llm
from graph.state import StockAnalysisState, AgentReport, AgentStatus

SENTIMENT_SYSTEM_PROMPT = """You are a Market Sentiment Analyst specializing in Indian equities at a leading Mumbai-based
hedge fund. You have deep expertise in interpreting news flow, FII/DII behavior, and social
sentiment signals for NSE/BSE-listed companies.

You understand India-specific sentiment drivers:
- Promoter buying/selling signals
- RBI policy impact on banking/NBFC sentiment
- FII behavior during global risk-on/risk-off cycles
- How Budget announcements affect sector sentiment
- The significance of management guidance in quarterly results
- Impact of SEBI/CCI/government regulatory actions

Sentiment scoring guide (0–10):
    0–2  = Extremely negative — panic selling, regulatory action, fraud allegations
    3–4  = Negative — disappointing results, negative news flow, FII selling
    5    = Neutral — mixed signals, no clear directional bias
    6–7  = Positive — good news flow, FII buying, positive guidance
    8–10 = Extremely positive — re-rating event, major contract win, buyback/bonus

Output ONLY valid JSON. No preamble, no explanation outside the JSON."""

SENTIMENT_USER_PROMPT = """
Analyze market sentiment for {company_name} ({ticker}) based on the following data:

━━━ RECENT NEWS (Last 7 Days) ━━━
{news_items}

━━━ FII / DII ACTIVITY (Last 10 Trading Days) ━━━
FII Net Flow:    ₹{fii_10day_net} Crore ({fii_stance})
DII Net Flow:    ₹{dii_10day_net} Crore ({dii_stance})
Daily breakdown:
{fii_dii_daily_table}

━━━ GDELT GLOBAL SENTIMENT ━━━
Article Count (30 days):  {gdelt_article_count}
Average Tone Score:       {gdelt_avg_tone} (positive = bullish, negative = bearish)
Sample Global Headlines:
{gdelt_headlines}

━━━ MARKETAUX ENTITY SENTIMENT ━━━
Average Sentiment Score:  {marketaux_avg_sentiment} (range -1.0 to +1.0)
Positive Articles:        {positive_count}
Negative Articles:        {negative_count}
Neutral Articles:         {neutral_count}

━━━ COMPANY CONTEXT ━━━
Sector:          {sector}
Recent Events:   {recent_corporate_events}

Provide sentiment analysis as JSON with this exact schema:
{{
    "summary": "<2-3 sentence overall sentiment assessment>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "key_findings": [
        "<finding 1: overall news tone with specific examples>",
        "<finding 2: FII/DII behavior interpretation>",
        "<finding 3: notable positive catalyst if any>",
        "<finding 4: notable negative signal if any>",
        "<finding 5: social/global sentiment reading>"
    ],
    "risk_flags": [
        "<any negative news that could affect price>",
        "<any regulatory/legal concern in news>"
    ],
    "news_sentiment": "very_positive" | "positive" | "neutral" | "negative" | "very_negative",
    "fii_dii_stance": "both_buying" | "fii_buying_dii_selling" | "fii_selling_dii_buying" | "both_selling" | "mixed",
    "sentiment_trend": "improving" | "stable" | "deteriorating",
    "key_news_event": "<single most important news item in last 7 days>",
    "event_impact": "positive" | "neutral" | "negative"
}}
"""

async def run_sentiment_analysis(state: StockAnalysisState) -> AgentReport:
    """Run sentiment and news analysis."""
    try:
        client = get_llm()
        news = state.get("news_data", [])
        fundamental = state.get("fundamental_data", {})
        
        # Parse FII DII payload
        fii_dii_payload = state.get("fii_dii_data", {})
        daily_records = fii_dii_payload.get("daily_records", [])
        daily_table = ""
        for r in daily_records:
            date = r.get('date', 'Unknown')
            f_net = r.get('fii_net_buy_sell', 0)
            d_net = r.get('dii_net_buy_sell', 0)
            daily_table += f"{date} | FII: {f_net} | DII: {d_net}\n"
        if not daily_table: daily_table = "No daily FII/DII data available."

        # Parse GDELT
        gdelt_payload = state.get("gdelt_data", {})
        headlines = "\n".join(gdelt_payload.get("sample_headlines", [])) or "No global headlines found."

        # Parse News
        news_items_text = ""
        pos_count = 0
        neg_count = 0
        neu_count = 0
        sent_sum = 0
        sent_items = 0
        
        for idx, n in enumerate(news):
            title = n.get("title", "")
            src = n.get("source", "Unknown")
            date = n.get("date", "")
            s_score = n.get("sentiment")
            
            s_text = f"Sentiment Score: {s_score}" if s_score is not None else "Sentiment Score: N/A"
            news_items_text += f"{idx+1}. {title} | Source: {src} | {s_text} | Date: {date}\n"
            
            if s_score is not None:
                sent_sum += float(s_score)
                sent_items += 1
                if float(s_score) > 0.2: pos_count += 1
                elif float(s_score) < -0.2: neg_count += 1
                else: neu_count += 1
                
        if not news_items_text: news_items_text = f"No recent news found for {state['company_name']}."
        avg_sent = round(sent_sum / sent_items, 3) if sent_items > 0 else "N/A"

        prompt = SENTIMENT_USER_PROMPT.format(
            company_name=state["company_name"],
            ticker=state["ticker"],
            news_items=news_items_text,
            fii_10day_net=fii_dii_payload.get("fii_10day_net", 0.0),
            fii_stance=fii_dii_payload.get("fii_stance", "Unknown"),
            dii_10day_net=fii_dii_payload.get("dii_10day_net", 0.0),
            dii_stance=fii_dii_payload.get("dii_stance", "Unknown"),
            fii_dii_daily_table=daily_table,
            gdelt_article_count=gdelt_payload.get("article_count", 0),
            gdelt_avg_tone=gdelt_payload.get("avg_tone", 0.0),
            gdelt_headlines=headlines,
            marketaux_avg_sentiment=avg_sent,
            positive_count=pos_count,
            negative_count=neg_count,
            neutral_count=neu_count,
            sector=fundamental.get("sector", "Unknown"),
            recent_corporate_events=fundamental.get("business_summary", "No events given.")[:500] + "..."
        )
        
        response = await client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        data = json.loads(text)
        
        return AgentReport(
            agent_name="Sentiment Analyst",
            status=AgentStatus.COMPLETE,
            summary=data.get("summary", ""),
            score=data.get("score", 5.0),
            key_findings=data.get("key_findings", []),
            risk_flags=data.get("risk_flags", []),
            confidence=data.get("confidence", 0.0),
            data=data
        )
    except Exception as e:
        print(f"Sentiment Analyst Error: {e}")
        return AgentReport(
            agent_name="Sentiment Analyst",
            status=AgentStatus.ERROR,
            summary=f"Analysis failed: {str(e)}",
            score=5.0,
            key_findings=[],
            risk_flags=["Analysis failed"],
            confidence=0.0,
            data={}
        )
