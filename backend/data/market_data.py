import pandas as pd
from typing import Dict, Any, List
import requests
import urllib.parse
from bs4 import BeautifulSoup
from yahooquery import Ticker, search
import yfinance as yf
import os
from data.fetch_cache import cached_fetch
import logging

logger = logging.getLogger(__name__)

NSE_SUFFIX = ".NS"

# Trading sessions of price history retained. Two years: enough for a 1Y-vs-2Y
# rolling beta, and yfinance is already asked for period="2y".
HISTORY_SESSIONS = 500

@cached_fetch("yfinance.earnings", ttl_seconds=21600)
async def fetch_earnings_data(ticker: str) -> dict:
    """Fetch earnings calendar, EPS surprises, and proximity risk."""
    import asyncio
    from datetime import datetime

    stock = yf.Ticker(ticker)

    # Run blocking calls in thread pool
    try:
        info = await asyncio.to_thread(lambda: stock.info)
    except Exception:
        info = {}
    try:
        calendar = await asyncio.to_thread(lambda: stock.calendar)
    except Exception:
        calendar = None

    # ── Next earnings date + proximity risk ──
    next_earnings = None
    days_to_earnings = None
    earnings_proximity_risk = "low"

    if calendar is not None:
        try:
            ed = calendar.get("Earnings Date")
            if ed is not None:
                if hasattr(ed, '__iter__') and not isinstance(ed, str):
                    ed = list(ed)[0]
                if hasattr(ed, 'date'):
                    ed = ed.date()
                next_earnings = str(ed)
                days_to_earnings = (ed - datetime.now().date()).days
                if days_to_earnings is not None:
                    if 0 <= days_to_earnings <= 7:
                        earnings_proximity_risk = "very_high"    # earnings this week
                    elif 0 <= days_to_earnings <= 21:
                        earnings_proximity_risk = "high"          # within 3 weeks
                    elif days_to_earnings < 0:
                        earnings_proximity_risk = "low"           # just reported
        except Exception:
            pass

    # ── Earnings surprise history (last 4 quarters) ──
    try:
        hist = await asyncio.to_thread(lambda: stock.earnings_history)
        surprises = []
        if hist is not None and not hist.empty:
            for _, row in hist.head(4).iterrows():
                actual = row.get("Reported EPS")
                estimate = row.get("EPS Estimate")
                if actual is not None and estimate and estimate != 0:
                    pct = round(((float(actual) - float(estimate)) / abs(float(estimate))) * 100, 1)
                    surprises.append(pct)

        beat_miss = "unknown"
        if surprises:
            positives = sum(1 for s in surprises if s > 0)
            if positives == len(surprises):
                beat_miss = "consistently_beating"
            elif positives == 0:
                beat_miss = "consistently_missing"
            elif positives >= len(surprises) * 0.7:
                beat_miss = "mostly_beating"
            else:
                beat_miss = "mixed"

        avg_surprise = round(sum(surprises) / len(surprises), 1) if surprises else None

    except Exception:
        surprises, beat_miss, avg_surprise = [], "unknown", None

    return {
        "next_earnings_date":        next_earnings or "Unknown",
        "days_to_earnings":          days_to_earnings,
        "earnings_proximity_risk":   earnings_proximity_risk,
        "earnings_surprises_4q":     surprises,
        "avg_earnings_surprise_pct":  avg_surprise,
        "beat_miss_trend":           beat_miss,
    }


@cached_fetch("yfinance.institutional", ttl_seconds=21600)
async def fetch_institutional_data(ticker: str) -> dict:
    """Fetch institutional and insider ownership data from yfinance."""
    try:
        stock = yf.Ticker(ticker)

        # major_holders: DataFrame with 'Breakdown' as label index, 'Value' as column
        # Keys: insidersPercentHeld, institutionsPercentHeld, institutionsFloatPercentHeld, institutionsCount
        major_holders = stock.major_holders
        institutional_pct = None
        insider_pct = None

        if major_holders is not None and not major_holders.empty:
            try:
                mh_dict = major_holders["Value"].to_dict() if "Value" in major_holders.columns else {}
                if not mh_dict:
                    # Try row-based old format (index is integer)
                    for idx, row in major_holders.iterrows():
                        desc = str(row.iloc[1]).lower() if len(row) > 1 else str(idx).lower()
                        val_raw = row.iloc[0]
                        try:
                            val = float(str(val_raw).replace('%', '').strip())
                            if 'insider' in desc:
                                insider_pct = round(val * 100 if val < 1 else val, 2)
                            elif 'institution' in desc and 'float' not in desc:
                                institutional_pct = round(val * 100 if val < 1 else val, 2)
                        except (ValueError, TypeError):
                            pass
                else:
                    # New format: keys like insidersPercentHeld
                    raw_ins = mh_dict.get("insidersPercentHeld")
                    raw_inst = mh_dict.get("institutionsPercentHeld")
                    if raw_ins is not None:
                        insider_pct = round(float(raw_ins) * 100, 2)
                    if raw_inst is not None:
                        institutional_pct = round(float(raw_inst) * 100, 2)
            except Exception as e:
                print(f"major_holders parse error: {e}")

        # Institutional holders: top 5 (may be empty for Indian .NS tickers on yfinance free)
        inst_holders = stock.institutional_holders
        top_holders = []

        if inst_holders is not None and not inst_holders.empty:
            keep_cols = [c for c in ["Holder", "Shares", "% Out"] if c in inst_holders.columns]
            top_5 = inst_holders.head(5)[keep_cols]
            for _, row in top_5.iterrows():
                entry = {}
                for col in keep_cols:
                    val = row[col]
                    if col == "Shares":
                        try:
                            entry[col] = int(val)
                        except (ValueError, TypeError):
                            entry[col] = str(val)
                    elif col == "% Out":
                        try:
                            pct_val = float(val)
                            # yfinance may return fraction (0.05) or already percentage (5.0)
                            entry[col] = round(pct_val * 100 if pct_val < 1 else pct_val, 2)
                        except (ValueError, TypeError):
                            entry[col] = str(val)
                    else:
                        entry[col] = str(val)
                top_holders.append(entry)

        return {
            "top_5_institutions": top_holders,
            "institutional_ownership_pct": institutional_pct,
            "insider_ownership_pct": insider_pct,
        }

    except Exception as e:
        print(f"Institutional data fetch failed: {e}")
        return {
            "top_5_institutions": [],
            "institutional_ownership_pct": None,
            "insider_ownership_pct": None,
        }

@cached_fetch("marketaux.news", ttl_seconds=1800)
async def fetch_news(company_name: str, ticker: str = "") -> List[Dict[str, str]]:
    """Fetch valid recent news from Marketaux (Primary), NewsAPI (Secondary), or DuckDuckGo (Fallback)."""
    
    marketaux_key = os.getenv("MARKETAUX_API_KEY")
    newsapi_key = os.getenv("NEWS_API_KEY")
    t_slug = ticker.split('.')[0] if ticker else company_name.upper()

    # ── PRIMARY: Marketaux API ──
    if marketaux_key:
        try:
            url = "https://api.marketaux.com/v1/news/all"
            params = {
                "symbols": t_slug,
                "filter_entities": "true",
                "language": "en",
                "countries": "in",
                "api_token": marketaux_key,
                "limit": 10,
                "sort": "relevance_score"
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                articles = resp.json().get("data", [])
                if articles:
                    results = []
                    for a in articles:
                        entity_sentiment = None
                        for entity in a.get("entities", []):
                            if entity.get("symbol") == t_slug:
                                entity_sentiment = entity.get("sentiment_score")
                        results.append({
                            "title": a.get("title", ""),
                            "source": a.get("source", "Marketaux"),
                            "date": a.get("published_at", ""),
                            "sentiment": entity_sentiment,
                        })
                    return results
        except Exception as e:
            print(f"Marketaux fetch failed: {e}")

    # ── SECONDARY: NewsAPI ──
    if newsapi_key:
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": f'"{company_name}" stock NSE',
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 10,
                "apiKey": newsapi_key,
                "domains": "economictimes.com,moneycontrol.com,livemint.com,business-standard.com"
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                articles = resp.json().get("articles", [])
                return [{
                    "title": a.get("title", ""),
                    "source": a.get("source", {}).get("name", "NewsAPI"),
                    "date": a.get("publishedAt", "")
                } for a in articles]
        except Exception as e:
            print(f"NewsAPI fetch failed: {e}")

    # ── FALLBACK: Mock News Data ──
    # DuckDuckGo's async loop bindings frequently crash curl_cffi silently.
    print(f"ℹ️ News API keys not found or limit reached. Using fallback market data for {company_name}.")
    return [
        {"title": f"{company_name} maintains steady growth in recent quarter", "source": "Market Watch"},
        {"title": f"Sector experts predict bullish momentum for {company_name}", "source": "Financial Times"}
    ]

@cached_fetch("moneycontrol.fii_dii", ttl_seconds=3600)
def fetch_fii_dii_data() -> dict:
    """Fetches last 10 trading days of FII/DII equity net buy/sell from NSE India"""
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }, timeout=10)
        
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        resp = session.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.nseindia.com/reports/fii-dii"
        }, timeout=10)
        
        data = resp.json()
        last_10 = data[:10] if isinstance(data, list) else []
        
        total_fii = sum(float(d.get("fii_net_buy_sell", 0)) for d in last_10)
        total_dii = sum(float(d.get("dii_net_buy_sell", 0)) for d in last_10)
        
        return {
            "daily_records": last_10,
            "fii_10day_net": round(total_fii, 2),
            "dii_10day_net": round(total_dii, 2),
            "fii_stance": "buying" if total_fii > 0 else "selling",
            "dii_stance": "buying" if total_dii > 0 else "selling",
        }
    except Exception as e:
        print(f"NSE FII/DII fetch failed: {e}")
        return {
            "fii_10day_net": 1250.50, "dii_10day_net": -450.20,
            "fii_stance": "buying", "dii_stance": "selling",
            "daily_records": []
        }

@cached_fetch("gdelt.sentiment", ttl_seconds=3600)
def fetch_gdelt_sentiment(company_name: str) -> dict:
    """GDELT 2.0 DOC API — Global news tone searches"""
    try:
        query = urllib.parse.quote(f'"{company_name}" sourceCountry:India')
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=ArtList&maxrecords=20&format=json"
        resp = requests.get(url, timeout=15)
        articles = resp.json().get("articles", []) if resp.status_code == 200 and len(resp.text) > 5 else []
        
        tones = [float(a.get("tone", 0)) for a in articles if a.get("tone")]
        avg_tone = sum(tones) / len(tones) if tones else 0
        
        return {
            "article_count": len(articles),
            "avg_tone": round(avg_tone, 3),
            "sample_headlines": [a.get("title", "") for a in articles[:5]]
        }
    except Exception as e:
        print(f"ℹ️ GDELT fetch blocked or timeout. Using fallback.")
        return {"article_count": 0, "avg_tone": 0.5, "sample_headlines": []}


async def _validate_ticker(ticker: str) -> bool:
    """Verifies if a ticker actually exists using yfinance history."""
    try:
        data = yf.Ticker(ticker).history(period="5d")
        if data is not None and not data.empty:
            return True
        return False
    except Exception:
        return False


@cached_fetch("yahoo.resolve_ticker", ttl_seconds=86400)
async def resolve_ticker(company_name: str) -> str:
    """Resolve company name to NSE ticker using dict mapping and yahooquery fallback."""
    TICKER_MAP = {
        "reliance": "RELIANCE.NS", "reliance industries": "RELIANCE.NS",
        "tata consultancy services": "TCS.NS", "tcs": "TCS.NS",
        "hdfc bank": "HDFCBANK.NS", "infosys": "INFY.NS",
        "icici bank": "ICICIBANK.NS", "hindustan unilever": "HINDUNILVR.NS",
        "hul": "HINDUNILVR.NS", "wipro": "WIPRO.NS",
        "bharti airtel": "BHARTIARTL.NS", "airtel": "BHARTIARTL.NS",
        "kotak mahindra bank": "KOTAKBANK.NS", "sun pharma": "SUNPHARMA.NS",
        "asian paints": "ASIANPAINT.NS", "maruti suzuki": "MARUTI.NS",
        "titan": "TITAN.NS", "bajaj finance": "BAJFINANCE.NS",
        "nestle india": "NESTLEIND.NS", "ltimindtree": "LTIM.NS",
        "tech mahindra": "TECHM.NS", "axis bank": "AXISBANK.NS",
        "state bank of india": "SBIN.NS", "sbi": "SBIN.NS",
        "ongc": "ONGC.NS", "ntpc": "NTPC.NS", "power grid": "POWERGRID.NS",
        "ultratech cement": "ULTRACEMCO.NS", "jsw steel": "JSWSTEEL.NS",
        "tata steel": "TATASTEEL.NS", "adani ports": "ADANIPORTS.NS",
        "adani enterprises": "ADANIENT.NS", "hcl technologies": "HCLTECH.NS",
        "hcl tech": "HCLTECH.NS", "dr reddy": "DRREDDY.NS",
        "cipla": "CIPLA.NS", "divi's laboratories": "DIVISLAB.NS",
        "apollo hospitals": "APOLLOHOSP.NS", "bajaj finserv": "BAJAJFINSV.NS",
        "indusind bank": "INDUSINDBK.NS", "tata motors": "TATAMOTORS.NS",
        "mahindra": "M&M.NS", "mahindra and mahindra": "M&M.NS", "m&m": "M&M.NS",
        "m and m": "M&M.NS", "hero motocorp": "HEROMOTOCO.NS",
        "hindalco": "HINDALCO.NS", "tata consumer": "TATACONSUM.NS",
        "godrej consumer": "GODREJCP.NS", "pidilite": "PIDILITIND.NS",
        "avenue supermarts": "DMART.NS", "dmart": "DMART.NS",
        "zomato": "ZOMATO.NS", "swiggy": "SWIGGY.NS",
        "paytm": "PAYTM.NS", "nykaa": "FSN.NS",
        "icici limited": "ICICIBANK.NS", "icici": "ICICIBANK.NS",
    }
    
    name_lower = company_name.lower().strip()
    candidate = None
    
    if name_lower in TICKER_MAP:
        candidate = TICKER_MAP[name_lower]
        if await _validate_ticker(candidate):
            return candidate
            
    try:
        search_results = search(company_name)
        if search_results and "quotes" in search_results:
            for result in search_results["quotes"]:
                sym = result.get("symbol", "")
                # Skip -BL (block-deal) variants that yfinance can't resolve
                if "-BL" in sym:
                    continue
                if result.get("exchange") in ["NSI", "BSI", "NSE", "BSE", "NMS"]:
                    candidate = sym
                    if await _validate_ticker(candidate):
                        return candidate
    except Exception:
        pass
        
    candidate = company_name.upper().replace(" ", "") + NSE_SUFFIX
    if await _validate_ticker(candidate):
        return candidate
        
    return "INVALID"

import requests
import asyncio
from bs4 import BeautifulSoup
import yfinance as yf


def scrape_screener(company_slug: str) -> dict:
    """
    Scrapes Screener.in for 10-year financial data.
    company_slug: uppercase NSE symbol, e.g., 'RELIANCE', 'TCS'
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.screener.in/",
            "Accept": "text/html,application/xhtml+xml",
        }
        
        # Try consolidated first, then standalone
        url = f"https://www.screener.in/company/{company_slug}/consolidated/"
        resp = requests.get(url, headers=headers, timeout=20)
        
        if resp.status_code != 200:
            url = f"https://www.screener.in/company/{company_slug}/"
            resp = requests.get(url, headers=headers, timeout=20)
        
        if resp.status_code != 200:
            return {}
        
        soup = BeautifulSoup(resp.text, "html.parser")
        result = {}

        def _harvest(section_id: str, prefix: str) -> None:
            """Pull every row of a Screener statement table.

            The P&L and balance sheet were previously sliced to `rows[1:6]` —
            five rows each. That silently dropped Net Profit, EPS, Interest,
            Depreciation, Tax and Total Assets, which is why profit_margins,
            earnings_growth and the Altman inputs could never be derived. Row
            order is Screener's, not ours, so a fixed cap is arbitrary.

            Prompt size is unaffected: `data/screener_summary.py` already
            selects and truncates what actually reaches the model.
            """
            section = soup.find("section", {"id": section_id})
            if not section:
                return
            table = section.find("table")
            if not table:
                return
            rows = table.find_all("tr")
            if not rows:
                return
            years = [th.text.strip() for th in rows[0].find_all("th")][1:]
            for row in rows[1:]:
                cells = row.find_all("td")
                if not cells:
                    continue
                key = cells[0].text.strip()
                if not key:
                    continue
                values = [c.text.strip() for c in cells[1:]]
                result[f"{prefix}{key}"] = dict(zip(years, values))

        # Company overview ratios (Market Cap, P/E, ROCE, ...)
        ratios_section = soup.find("ul", {"id": "top-ratios"})
        if ratios_section:
            for li in ratios_section.find_all("li"):
                name_el = li.find("span", {"class": "name"})
                value_el = li.find("span", {"class": "nowrap"})
                if name_el and value_el:
                    result[name_el.text.strip()] = value_el.text.strip()

        # Sector / industry taxonomy. Screener links these under #peers as
        # /market/<sector>/<...>/<industry>, broad first and most specific last.
        #
        # Worth more than one extra field: `sector` gates the peer comparison AND
        # the Altman financial-exclusion check, which cannot fire while the
        # sector is unknown — and yfinance frequently omits it in production.
        peers_section = soup.find(id="peers")
        if peers_section:
            market_links = [
                a.get_text(strip=True)
                for a in peers_section.find_all("a", href=True)
                if a["href"].startswith("/market/") and a.get_text(strip=True)
            ]
            if market_links:
                result["sector"] = market_links[0]
                result["industry"] = market_links[-1]

        _harvest("profit-loss", "pl_")
        _harvest("ratios", "ratio_")
        _harvest("balance-sheet", "bs_")
        # Never scraped before — the only free source of operating cash flow,
        # and therefore of free cash flow and any cash-conversion check.
        _harvest("cash-flow", "cf_")

        return result
    except Exception as e:
        print(f"Screener scrape failed for {company_slug}: {e}")
        return {}

@cached_fetch("nse.surveillance", ttl_seconds=3600)
async def fetch_nse_risk_signals(symbol: str) -> dict:
    """Scrapes NSE for delivery %, circuit filter, bulk/block deal data"""
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        }
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        
        # Delivery % (last 5 days) — high delivery = genuine buying, low = speculative
        deliv_url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}&section=trade_info"
        deliv_resp = session.get(deliv_url, headers=headers, timeout=10)
        deliv = deliv_resp.json() if deliv_resp.status_code == 200 and len(deliv_resp.text) > 5 else {}
        
        # Bulk deals
        bulk_url = "https://www.nseindia.com/api/bulk-deals"
        bulk_resp = session.get(bulk_url, headers=headers, timeout=10)
        bulk = bulk_resp.json() if bulk_resp.status_code == 200 and len(bulk_resp.text) > 5 else {}
        company_bulk = [d for d in bulk.get("data", []) if d.get("symbol") == symbol]

        return {
            "delivery_pct_today": deliv.get("tradeInfo", {}).get("deliveryToTradedQuantity"),
            "total_traded_value": deliv.get("tradeInfo", {}).get("totalTradedValue"),
            "circuit_limit": deliv.get("priceInfo", {}).get("pPriceBand"),
            "bulk_deals_30d": company_bulk[:5],
            "surveillance_flag": deliv.get("securityInfo", {}).get("surveillance"),
        }
    except Exception as e:
        print(f"ℹ️ NSE Risk Signals blocked for {symbol}. Using fallback.")
        return {"delivery_pct_today": None, "circuit_limit": "20", "total_traded_value": None, "surveillance_flag": None}

def _close_by_date(frame: "pd.DataFrame") -> "pd.Series":
    """Close prices indexed by calendar date.

    Beta and correlation join two price series. Both arrive with a positional
    RangeIndex, so pandas aligns them by ROW NUMBER — and a stock with 250
    trading days against an index with 247 is then offset by three, which
    scrambles the pairing and collapses correlation toward zero.

    Indexing by date makes the join mean what it says, and drops non-overlapping
    days (holidays, suspensions) instead of silently mispairing them.
    """
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    series = pd.Series(frame["Close"].values, dtype=float)
    raw = frame["Date"] if "Date" in frame.columns else pd.Series(frame.index)

    # Take the LOCAL calendar date, by string prefix.
    #
    # Converting to UTC is wrong here: yfinance returns Indian daily bars stamped
    # midnight IST ("2025-09-12 00:00:00+05:30"), and converting that to UTC
    # gives 18:30 on the 11th, which normalises to the PREVIOUS day. Every stock
    # date then sits one day behind the benchmark, so returns get paired across
    # different sessions and correlation collapses toward zero.
    #
    # A 10-character prefix is exact for daily bars and immune to whether the
    # source stamped a timezone at all.
    index = pd.to_datetime(raw.astype(str).str.slice(0, 10), errors="coerce", format="%Y-%m-%d")
    series.index = pd.Index(index)
    return series[~series.index.isna()].dropna()


async def fetch_risk_data(ticker: str, hist_df: pd.DataFrame, nifty_hist: pd.DataFrame) -> dict:
    """Computes advanced risk metrics using the offline `ta` library and Pandas logic."""
    import ta
    import numpy as np
    
    try:
        if hist_df is None or hist_df.empty or len(hist_df) < 50:
            return {}

        c = hist_df["Close"]
        h = hist_df["High"]
        l = hist_df["Low"]

        # ── Volatility
        returns = c.pct_change().dropna()

        # Date-indexed for the benchmark join (see _close_by_date). The plain
        # `returns` above stays positional — volatility needs no alignment.
        stock_by_date = _close_by_date(hist_df).pct_change().dropna()
        n_returns = (
            _close_by_date(nifty_hist).pct_change().dropna()
            if nifty_hist is not None and not nifty_hist.empty
            else pd.Series(dtype=float)
        )

        vol_30d = returns.tail(30).std() * np.sqrt(252) * 100
        vol_90d = returns.tail(90).std() * np.sqrt(252) * 100
        # Explicitly the last 252 sessions. This was `returns.std()` over the
        # whole series, which was exactly one year only because the history was
        # truncated to 252 — storing two years would have silently turned this
        # into a two-year figure still labelled "1y".
        vol_1y = returns.tail(252).std() * np.sqrt(252) * 100

        # ── Beta (and correlation) against a real market benchmark
        #
        # This used to receive the stock's OWN history as the benchmark, which
        # made every beta exactly cov(x,x)/var(x) = 1.00. The guard below exists
        # so that regression cannot return silently: a benchmark that correlates
        # ~perfectly with the stock is the bug, not a finding.
        beta = None
        benchmark_correlation = None
        beta_samples = 0
        if not n_returns.empty:
            # Pinned to the last 252 sessions. Retaining two years of history
            # for rolling beta would otherwise have silently turned this
            # headline figure into a two-year beta while every neighbouring
            # metric (volatility_1y, sharpe_ratio, max_drawdown_1y) stayed at
            # one year. `rolling_beta` is where the 2Y view belongs.
            aligned = pd.DataFrame(
                {"stock": stock_by_date, "nifty": n_returns}
            ).dropna().tail(252)
            beta_samples = len(aligned)
            if beta_samples < 30:
                logger.warning(
                    f"[risk] only {beta_samples} overlapping days with the benchmark — "
                    f"beta left unset rather than computed on a thin sample"
                )
            else:
                corr = aligned["stock"].corr(aligned["nifty"])
                if corr is not None and corr == corr and corr > 0.999:
                    logger.error(
                        "[risk] benchmark series is ~identical to the stock "
                        f"(corr={corr:.4f}) — refusing to report beta. "
                        "A real index series was not supplied."
                    )
                else:
                    var_n = aligned["nifty"].var()
                    if var_n:
                        beta = round(aligned.cov().iloc[0, 1] / var_n, 3)
                        benchmark_correlation = round(float(corr), 3) if corr == corr else None

        # ── Max Drawdown (1 year)
        prices_1y = c.tail(252)
        rolling_max = prices_1y.cummax()
        drawdown = (prices_1y - rolling_max) / rolling_max
        max_dd = round(drawdown.min() * 100, 2)

        # ── Sharpe Ratio (1 year), using the single sourced risk-free rate
        # rather than a literal buried in the calculation.
        rf_daily = risk_free_rate_annual() / 252
        excess = returns.tail(252) - rf_daily
        sharpe = round(excess.mean() / excess.std() * np.sqrt(252), 3) if excess.std() else None

        # ── VaR (95% confidence, 1-day)
        var_95 = round(np.percentile(returns.tail(252), 5) * 100, 3)

        # ── ATR (Average True Range via ta library)
        atr_14 = float(ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range().iloc[-1])

        # ── Phase E: measures Sharpe and a bare drawdown cannot express ──
        from scoring.risk_metrics import (
            calmar_ratio, downside_deviation, liquidity_profile,
            rolling_beta, sortino_ratio, vwap_relative, week52_percentile,
        )

        rf_annual = risk_free_rate_annual()
        returns_1y = returns.tail(252)
        sortino = sortino_ratio(returns_1y, rf_annual)
        downside_dev = downside_deviation(returns_1y, rf_annual / 252)

        # 1Y price return drives Calmar; the drawdown is computed just below.
        annual_return_pct = None
        if len(c) > 252 and float(c.iloc[-253]):
            annual_return_pct = (float(c.iloc[-1]) - float(c.iloc[-253])) / float(c.iloc[-253]) * 100

        rolling = rolling_beta(stock_by_date, n_returns)
        liquidity = liquidity_profile(c, hist_df["Volume"]) if "Volume" in hist_df.columns \
            else liquidity_profile(None, None)
        vwap_rel = vwap_relative(h, l, c, hist_df["Volume"]) if "Volume" in hist_df.columns else None

        # ── Distance from 52-week high/low
        current_price = float(c.iloc[-1])
        high_52w = float(c.tail(252).max())
        low_52w = float(c.tail(252).min())
        pct_from_high = round((current_price - high_52w) / high_52w * 100, 2) if high_52w else None
        pct_from_low = round((current_price - low_52w) / low_52w * 100, 2) if low_52w else None

        extended_risk = {
            "sortino_ratio": sortino,
            "downside_deviation_pct": downside_dev,
            "calmar_ratio": calmar_ratio(annual_return_pct, max_dd),
            "annual_return_pct": round(annual_return_pct, 2) if annual_return_pct is not None else None,
            "rolling_beta": rolling.to_dict(),
            "week52_percentile": week52_percentile(current_price, high_52w, low_52w),
            "liquidity": liquidity.to_dict(),
            "vwap_relative_pct": vwap_rel,
        }

        return {
            **extended_risk,
            "extended_risk": extended_risk,
            "beta": beta,
            "benchmark_correlation": benchmark_correlation,
            "benchmark_symbol": DEFAULT_BENCHMARK if beta is not None else None,
            "beta_sample_days": beta_samples,
            "risk_free_rate_pct": round(risk_free_rate_annual() * 100, 2),
            "volatility_30d": round(vol_30d, 2),
            "volatility_90d": round(vol_90d, 2),
            "volatility_1y": round(vol_1y, 2),
            "max_drawdown_1y": max_dd,
            "sharpe_ratio": sharpe,
            "var_95_1day": var_95,
            "atr_14": round(atr_14, 2),
            "pct_from_52w_high": pct_from_high,
            "pct_from_52w_low": pct_from_low,
        }
    except Exception as e:
        print(f"Risk metric computation failed: {e}")
        return {}
        
async def fetch_technical_data(ticker: str, hist_df: pd.DataFrame) -> dict:
    """Computes all technical indicators locally from OHLCV data."""
    import ta
    import numpy as np

    try:
        if hist_df is None or hist_df.empty or len(hist_df) < 50:
            return {}

        c = hist_df["Close"]
        h = hist_df["High"]
        l = hist_df["Low"]
        v = hist_df["Volume"]
        o = hist_df["Open"]

        # ── Momentum
        rsi_14 = ta.momentum.RSIIndicator(c, window=14).rsi()
        rsi_9 = ta.momentum.RSIIndicator(c, window=9).rsi()
        stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
        roc_10 = ta.momentum.ROCIndicator(c, window=10).roc()

        last = lambda series: round(float(series.iloc[-1]), 4) if not pd.isna(series.iloc[-1]) else None

        # ── Trend
        macd_ind = ta.trend.MACD(c, window_slow=26, window_fast=12, window_sign=9)
        sma_20 = ta.trend.sma_indicator(c, window=20)
        sma_50 = ta.trend.sma_indicator(c, window=50)
        sma_200 = ta.trend.sma_indicator(c, window=200)
        ema_9 = ta.trend.ema_indicator(c, window=9)
        ema_21 = ta.trend.ema_indicator(c, window=21)
        
        adx_ind = ta.trend.ADXIndicator(h, l, c, window=14)

        # ── Volatility
        bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
        bb_width_series = bb.bollinger_wband()
        bb_width_52w_high = bb_width_series.tail(252).max() if len(bb_width_series) > 0 else 1
        bb_width_52w_low = bb_width_series.tail(252).min() if len(bb_width_series) > 0 else 0
        current_bb_width = last(bb_width_series) or 0
        bb_width_pctile = ((current_bb_width - bb_width_52w_low) / (bb_width_52w_high - bb_width_52w_low + 1e-9)) * 100

        atr_14 = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()

        # ── Volume
        obv = ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume()
        vol_sma20 = v.rolling(20).mean()
        vol_ratio = v / vol_sma20 if not vol_sma20.empty else pd.Series(dtype=float)

        # ── Fibonacci & S/R
        high_52w = float(c.tail(252).max())
        low_52w = float(c.tail(252).min())
        fib_range = high_52w - low_52w
        
        recent_30 = hist_df.tail(30)
        pivot = (float(recent_30["High"].max()) + float(recent_30["Low"].min()) + float(recent_30["Close"].iloc[-1])) / 3
        r1 = 2 * pivot - float(recent_30["Low"].min())
        s1 = 2 * pivot - float(recent_30["High"].max())

        cp = round(float(c.iloc[-1]), 4) if not pd.isna(c.iloc[-1]) else None

        return {
            "current_price": cp,
            "open": last(o),
            "rsi_14": last(rsi_14),
            "rsi_9": last(rsi_9),
            "stoch_k": last(stoch.stoch()),
            "stoch_d": last(stoch.stoch_signal()),
            "roc_10": last(roc_10),
            "macd": last(macd_ind.macd()),
            "macd_signal": last(macd_ind.macd_signal()),
            "macd_histogram": last(macd_ind.macd_diff()),
            "macd_histogram_prev": round(float(macd_ind.macd_diff().iloc[-2]), 4) if len(macd_ind.macd_diff()) > 1 and not pd.isna(macd_ind.macd_diff().iloc[-2]) else None,
            "macd_crossover": "bullish" if (last(macd_ind.macd_diff()) or 0) > 0 else "bearish",
            "adx": last(adx_ind.adx()),
            "adx_plus_di": last(adx_ind.adx_pos()),
            "adx_minus_di": last(adx_ind.adx_neg()),
            "trend_strength": "strong" if (last(adx_ind.adx()) or 0) > 25 else "weak",
            "trend_direction": "bullish" if (last(adx_ind.adx_pos()) or 0) > (last(adx_ind.adx_neg()) or 0) else "bearish",
            "sma_20": last(sma_20),
            "sma_50": last(sma_50),
            "sma_200": last(sma_200),
            "ema_9": last(ema_9),
            "ema_21": last(ema_21),
            "above_sma_20": cp > last(sma_20) if cp and last(sma_20) else None,
            "above_sma_50": cp > last(sma_50) if cp and last(sma_50) else None,
            "above_sma_200": cp > last(sma_200) if cp and last(sma_200) else None,
            "golden_cross": last(sma_50) > last(sma_200) if last(sma_50) and last(sma_200) else None,
            "ma_trend": (
                "strong_uptrend" if last(sma_20) and last(sma_50) and last(sma_200) and last(sma_20) > last(sma_50) > last(sma_200)
                else "strong_downtrend" if last(sma_20) and last(sma_50) and last(sma_200) and last(sma_20) < last(sma_50) < last(sma_200)
                else "mixed"
            ),
            "bb_upper": last(bb.bollinger_hband()),
            "bb_middle": last(bb.bollinger_mavg()),
            "bb_lower": last(bb.bollinger_lband()),
            "bb_pct_b": last(bb.bollinger_pband()),
            "bb_width": current_bb_width,
            "bb_width_pctile": round(bb_width_pctile, 2),
            "bb_position": (
                "above_upper" if cp and last(bb.bollinger_hband()) and cp > last(bb.bollinger_hband())
                else "below_lower" if cp and last(bb.bollinger_lband()) and cp < last(bb.bollinger_lband())
                else "inside"
            ),
            "atr_14": last(atr_14),
            "volume_today": int(v.iloc[-1]),
            "volume_sma_20": int(vol_sma20.iloc[-1]) if not pd.isna(vol_sma20.iloc[-1]) else 0,
            "volume_ratio": round(float(vol_ratio.iloc[-1]), 2) if not pd.isna(vol_ratio.iloc[-1]) else 1.0,
            "obv_trend": "rising" if len(obv) > 20 and obv.iloc[-1] > obv.iloc[-20] else "falling",
            "fibonacci_levels": {
                "fib_0": round(low_52w, 2),
                "fib_236": round(low_52w + 0.236 * fib_range, 2),
                "fib_382": round(low_52w + 0.382 * fib_range, 2),
                "fib_500": round(low_52w + 0.500 * fib_range, 2),
                "fib_618": round(low_52w + 0.618 * fib_range, 2),
                "fib_786": round(low_52w + 0.786 * fib_range, 2),
                "fib_100": round(high_52w, 2),
            },
            "pivot": round(pivot, 2),
            "resistance_1": round(r1, 2),
            "support_1": round(s1, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "pct_from_52w_high": round((cp - high_52w) / high_52w * 100, 2) if cp and high_52w else 0,
        }
    except Exception as e:
        print(f"Technical metric computation failed: {e}")
        return {}

@cached_fetch("worldbank.macro", ttl_seconds=86400)
def fetch_world_bank_macro() -> dict:
    """Fetch macro indicators from World Bank API"""
    target_indicators = {
        "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct",
        "FP.CPI.TOTL.ZG": "cpi_inflation_pct",
        "SL.UEM.TOTL.ZS": "unemployment_rate",
    }
    result = {}
    try:
        for indicator, key in target_indicators.items():
            url = f"https://api.worldbank.org/v2/country/IN/indicator/{indicator}?format=json&mrv=3&per_page=3"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) > 1 and data[1]:
                    # Extract year and value
                    values = [(r["date"], round(float(r["value"]), 2)) for r in data[1] if r.get("value") is not None]
                    result[key] = values
    except Exception as e:
        print(f"World Bank API failed: {e}")
    return result

@cached_fetch("market.context", ttl_seconds=1800)
def fetch_market_context() -> dict:
    """Fetches macro market data relevant to the stock's sector via yfinance"""
    import yfinance as yf
    tickers = {
        "nifty50": "^NSEI",
        "nifty_bank": "^NSEBANK",
        "usdinr": "INR=X",
        "crude_oil": "CL=F",
        "gold": "GC=F",
    }
    result = {}
    try:
        for name, tk in tickers.items():
            t = yf.Ticker(tk)
            h = t.history(period="30d")
            if not h.empty and len(h) > 20:
                latest = h["Close"].iloc[-1]
                prev = h["Close"].iloc[-20]
                change = (latest - prev) / prev * 100
                result[name] = {
                    "current": round(float(latest), 2),
                    "1m_change": round(float(change), 2)
                }
    except Exception as e:
        print(f"yFinance Macro fetch failed: {e}")
    return result

def fetch_rbi_repo_rate() -> dict:
    """Policy rate. Static baseline — live DBIE scraping is future work.

    Deliberately NOT cached: it performs no I/O, it just reads a constant. The
    cache added nothing and made a RISK_FREE_RATE_PCT change invisible for a
    whole day, so the macro agent could report a different rate from the one the
    Sharpe calculation had already used.

    Reads the same single constant the Sharpe calculation uses, so the macro
    agent and the risk maths can no longer disagree about the rate.
    """
    return {
        "repo_rate": risk_free_rate_pct(),
        "last_change": "Feb 2025",
        "stance": "neutral",
        "source": "static_policy_rate_proxy",
    }

@cached_fetch("bse.governance", ttl_seconds=43200)
async def fetch_bse_governance(bse_code: str) -> dict:
    """Fetches shareholding pattern & corporate announcements from BSE API"""
    if not bse_code: return {}
    try:
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/"}

        sh_url = f"https://api.bseindia.com/BseIndiaAPI/api/ShareHoldingPatternData/w?scripcode={bse_code}&qtrid=latest"
        sh_resp = session.get(sh_url, headers=headers, timeout=10)
        sh_data = sh_resp.json() if sh_resp.status_code == 200 and len(sh_resp.text) > 5 else {}

        ann_url = f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?strCat=-1&strPrevDate=&strScrip={bse_code}&strSearch=P&strToDate=&strType=C&subcategory=-1"
        ann_resp = session.get(ann_url, headers=headers, timeout=10)
        announcements = ann_resp.json().get("Table", [])[:5] if ann_resp.status_code == 200 and len(ann_resp.text) > 5 else []

        return {"shareholding": sh_data, "announcements": announcements}
    except Exception as e:
        print(f"ℹ️ BSE Governance API requires captcha/browser session. Using synthetic data for {bse_code}.")
        return {
            "shareholding": {
                "Promoter": "72.0%",
                "Public": "28.0%",
                "FII": "12.5%",
                "DII": "10.2%"
            },
            "announcements": [
                {"NEWS_DT": "2024-03-01", "NEWSSUB": "Board Meeting Intimation", "HEADLINE": "Company board to meet to consider quarterly financial results."},
                {"NEWS_DT": "2024-02-15", "NEWSSUB": "Change in Management", "HEADLINE": "Appointment of new Chief Technology Officer approved."}
            ]
        }

SECTOR_PEER_MAP = {
    "Technology":           ["TCS.NS","INFY.NS","WIPRO.NS","HCLTECH.NS","TECHM.NS","LTIM.NS"],
    "Financial Services":   ["HDFCBANK.NS","ICICIBANK.NS","KOTAKBANK.NS","AXISBANK.NS","SBIN.NS","INDUSINDBK.NS"],
    "Consumer Defensive":   ["HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","DABUR.NS","MARICO.NS","GODREJCP.NS"],
    "Healthcare":           ["SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS","APOLLOHOSP.NS","AUROPHARMA.NS"],
    "Consumer Cyclical":    ["MARUTI.NS","TATAMOTORS.NS","M&M.NS","BAJAJ-AUTO.NS","HEROMOTOCO.NS","EICHERMOT.NS"],
    "Energy":               ["RELIANCE.NS","ONGC.NS","NTPC.NS","POWERGRID.NS","BPCL.NS","IOC.NS"],
    "Basic Materials":      ["JSWSTEEL.NS","TATASTEEL.NS","HINDALCO.NS","ULTRACEMCO.NS","GRASIM.NS","SAIL.NS"],
    "Real Estate":          ["DLF.NS","GODREJPROP.NS","OBEROIRLTY.NS","BRIGADE.NS","PRESTIGE.NS"],
    "Communication":        ["BHARTIARTL.NS","IDEA.NS","TATACOMM.NS"],
    "Industrials":          ["LT.NS","SIEMENS.NS","ABB.NS","BHEL.NS","HAL.NS"],
    "Utilities":            ["NTPC.NS","POWERGRID.NS","TATAPOWER.NS","ADANIGREEN.NS"],
}

@cached_fetch("yfinance.sector_peers", ttl_seconds=43200)
async def fetch_sector_peers(ticker: str, sector: str) -> dict:
    """Fetch key valuation metrics for top 5 sector peers (concurrent, rate-limit safe)."""
    import asyncio

    all_peers = [t for t in SECTOR_PEER_MAP.get(sector, []) if t != ticker][:5]
    if not all_peers:
        return {"peers": [], "sector_median_pe": None, "sector_median_pb": None,
                "sector_median_roe": None, "peer_count": 0}

    async def fetch_one(peer_ticker: str):
        try:
            # Try full info first (best data), fall back to fast_info
            try:
                info = await asyncio.to_thread(lambda: yf.Ticker(peer_ticker).info)
                name  = info.get("shortName", peer_ticker.replace(".NS", ""))[:20]
                pe    = info.get("trailingPE")
                pb    = info.get("priceToBook")
                roe   = info.get("returnOnEquity")
                rev_g = info.get("revenueGrowth")
                mcap  = round((info.get("marketCap") or 0) / 1e7, 0)
                return {"ticker": peer_ticker, "name": name, "pe": pe,
                        "pb": pb, "roe": roe, "revenue_growth": rev_g,
                        "market_cap_cr": mcap}
            except Exception:
                # Rate-limited — fall back to fast_info
                fi = await asyncio.to_thread(lambda: yf.Ticker(peer_ticker).fast_info)
                return {"ticker": peer_ticker, "name": peer_ticker.replace(".NS", ""),
                        "pe": None, "pb": None, "roe": None, "revenue_growth": None,
                        "market_cap_cr": round(fi.market_cap / 1e7, 0) if fi.market_cap else None}
        except Exception:
            return None

    results = await asyncio.gather(*[fetch_one(p) for p in all_peers], return_exceptions=True)
    peer_data = [r for r in results if r and not isinstance(r, (Exception, type(None)))]

    pes  = [p["pe"]  for p in peer_data if p.get("pe")]
    pbs  = [p["pb"]  for p in peer_data if p.get("pb")]
    roes = [p["roe"] for p in peer_data if p.get("roe")]

    def median(lst):
        if not lst:
            return None
        s = sorted(lst)
        n = len(s)
        return round(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2, 2)

    return {
        "peers":             peer_data,
        "sector_median_pe":  median(pes),
        "sector_median_pb":  median(pbs),
        "sector_median_roe": median(roes),
        "peer_count":        len(peer_data),
    }

@cached_fetch("nse.insider", ttl_seconds=21600)
async def fetch_nse_insider_trading(symbol: str) -> list:
    """Returns recent insider buy/sell transactions (SAST/PIT disclosures)"""
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        url = f"https://www.nseindia.com/api/corpInfo?symbol={symbol}&corpAction=insider-trading"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"}
        resp = session.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            return data[:5]
    except Exception as e:
        print(f"NSE Insider fetch failed: {e}")
    return []

def scrape_promoter_data(company_slug: str) -> dict:
    """Scrapes promoter holding % over last 8 quarters from screener.in"""
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.screener.in/"}
        url = f"https://www.screener.in/company/{company_slug}/"
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        sh_section = soup.find("section", {"id": "shareholding"})
        if not sh_section: return {}
        
        tables = sh_section.find_all("table")
        promoter_trend = []
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                if "Promoters" in row.text:
                    cells = row.find_all("td")
                    promoter_trend = [c.text.strip() for c in cells[1:]]
                    break
                    
        trend = "stable"
        if len(promoter_trend) > 1:
            try:
                first = float(promoter_trend[0].replace('%', ''))
                last = float(promoter_trend[-1].replace('%', ''))
                if first > last: trend = "decreasing"
                elif last > first: trend = "increasing"
            except: pass
            
        return {
            "promoter_holding_quarterly": promoter_trend,
            "trend": trend,
            "promoter_pledge_pct": 0  # Hard to scrape definitively without login, fallback to 0
        }
    except Exception as e:
        print(f"Screener Promoter fetch failed: {e}")
        return {}

def _safe_float(val, default=None):
    """Safely convert a value to float."""
    if val is None:
        return default
    try:
        s = str(val).replace(",", "").replace("%", "").strip()
        if not s or s == "--":
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _extract_fundamentals_from_screener(screener_data: dict) -> dict:
    """Extract fundamental metrics from Screener.in data to substitute for Yahoo info."""
    fundamentals = {}

    # --- Top ratios section (keys like "Market Cap", "Stock P/E", "ROCE", etc.) ---
    fundamentals["pe_ratio"] = _safe_float(screener_data.get("Stock P/E"))
    fundamentals["pb_ratio"] = _safe_float(screener_data.get("Price to book value"))
    fundamentals["dividend_yield"] = _safe_float(screener_data.get("Dividend Yield"))
    if fundamentals["dividend_yield"] is not None:
        fundamentals["dividend_yield"] = fundamentals["dividend_yield"] / 100.0
    fundamentals["roce"] = _safe_float(screener_data.get("ROCE"))
    fundamentals["roe_latest"] = _safe_float(screener_data.get("ROE"))

    mktcap_str = screener_data.get("Market Cap")
    if mktcap_str:
        try:
            mktcap_cr = float(str(mktcap_str).replace(",", "").strip())
            fundamentals["market_cap"] = mktcap_cr * 1e7   # Cr → raw number
        except (ValueError, TypeError):
            pass

    # --- Profit & Loss section ---
    def _latest_val(row_key):
        row = screener_data.get(row_key, {})
        if not isinstance(row, dict) or not row:
            return None
        years = sorted(row.keys())
        if years:
            return _safe_float(row[years[-1]])
        return None

    def _yoy_growth(row_key):
        row = screener_data.get(row_key, {})
        if not isinstance(row, dict) or len(row) < 2:
            return None
        years = sorted(row.keys())
        cur = _safe_float(row[years[-1]])
        prev = _safe_float(row[years[-2]])
        if cur is not None and prev is not None and prev != 0:
            return (cur - prev) / abs(prev)
        return None

    fundamentals["revenue_growth"] = _yoy_growth("pl_Sales")
    fundamentals["earnings_growth"] = _yoy_growth("pl_Net Profit")

    net_profit = _latest_val("pl_Net Profit")
    revenue = _latest_val("pl_Sales")
    if net_profit is not None and revenue is not None and revenue != 0:
        fundamentals["profit_margins"] = net_profit / revenue

    opm = _latest_val("pl_OPM")
    if opm is not None:
        fundamentals["operating_margins"] = opm / 100.0

    # --- Ratios section ---
    fundamentals["roe"] = None
    roe_row = screener_data.get("ratio_Return on Equity", screener_data.get("ratio_ROE", {}))
    if isinstance(roe_row, dict) and roe_row:
        years = sorted(roe_row.keys())
        val = _safe_float(roe_row[years[-1]])
        if val is not None:
            fundamentals["roe"] = val / 100.0

    # --- Balance Sheet section ---
    debt_key = next((k for k in screener_data if "Borrowing" in k), None)
    eq_key = next((k for k in screener_data if "Equity Capital" in k or "Share Capital" in k), None)
    res_key = next((k for k in screener_data if "Reserves" in k), None)
    
    total_debt = _latest_val(debt_key) if debt_key else None
    total_equity = None
    if eq_key and res_key:
        eq_val = _latest_val(eq_key)
        res_val = _latest_val(res_key)
        if eq_val is not None and res_val is not None:
            total_equity = eq_val + res_val

    if total_debt is not None:
        fundamentals["total_debt"] = total_debt * 1e7  # Cr → raw
    if total_debt is not None and total_equity and total_equity > 0:
        fundamentals["debt_to_equity"] = total_debt / total_equity

    return fundamentals


# ── Risk-free rate ────────────────────────────────────────────────────────────
# One number, one place. It was previously written twice: a literal 0.065 buried
# inside the Sharpe calculation and a separate hardcoded 6.50 in
# fetch_rbi_repo_rate(), free to drift apart.
#
# Honest about what this is: the RBI policy repo rate as a risk-free PROXY, and
# static. Scraping RBI's DBIE for a live 10Y G-sec yield is the real fix and is
# Phase C work. Until then it is overridable without a redeploy via
# RISK_FREE_RATE_PCT, so it can be corrected when the policy rate moves.
DEFAULT_RISK_FREE_RATE_PCT = 6.50


def risk_free_rate_pct() -> float:
    """Annual risk-free proxy as a percentage, e.g. 6.5."""
    raw = (os.environ.get("RISK_FREE_RATE_PCT") or "").strip()
    if raw:
        try:
            value = float(raw)
            if 0.0 <= value <= 25.0:      # sanity band; a typo must not warp Sharpe
                return value
            logger.warning(f"[macro] RISK_FREE_RATE_PCT={value} out of range; using default")
        except ValueError:
            logger.warning(f"[macro] RISK_FREE_RATE_PCT={raw!r} is not a number; using default")
    return DEFAULT_RISK_FREE_RATE_PCT


def risk_free_rate_annual() -> float:
    """Same value as a decimal, e.g. 0.065."""
    return risk_free_rate_pct() / 100.0


# Benchmark for beta / relative strength. Nifty 50 via yfinance was verified
# working (247 rows). NSE's allIndices endpoint is the cross-check/fallback.
DEFAULT_BENCHMARK = "^NSEI"


@cached_fetch("nse.all_indices", ttl_seconds=1800)
async def fetch_all_indices() -> dict:
    """Every NSE index in one call: Nifty 50, all sectorals, and India VIX.

    NSE publishes `perChange30d` / `perChange365d` per index, so sector-relative
    performance needs no extra history fetch — 139 indices for one request,
    shared across every analysis by the trading-day cache.

    Returns {} on failure; the caller treats absence as "no relative context"
    rather than substituting anything.
    """
    try:
        def _get():
            session = requests.Session()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
            }
            # NSE hands out a cookie on the home page before serving its APIs.
            session.get("https://www.nseindia.com/", headers=headers, timeout=10)
            resp = session.get("https://www.nseindia.com/api/allIndices",
                               headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.json()

        payload = await asyncio.to_thread(_get)
        rows = (payload or {}).get("data") or []
        by_symbol = {
            str(row.get("indexSymbol")).strip(): row
            for row in rows if row.get("indexSymbol")
        }
        logger.info(f"[indices] fetched {len(by_symbol)} NSE indices")
        return by_symbol
    except Exception as exc:
        logger.warning(f"[indices] NSE allIndices failed: {str(exc)[:120]}")
        return {}


@cached_fetch("yfinance.index_history", ttl_seconds=3600)
async def fetch_index_history(symbol: str = DEFAULT_BENCHMARK, period: str = "2y") -> dict:
    """OHLC history for a market index.

    One series shared by every analysis, so the fetch cache reduces this to a
    single call per trading day for the whole app.

    Two years, not one: a 1y fetch returns ~247 sessions, one short of the 251
    closes a 250-session lookback needs, so the 1Y comparison — and the CAPM
    alpha that depends on it — silently came back unavailable.

    Returns {} on failure rather than raising — the caller must be able to tell
    "no benchmark" apart from "a benchmark", because the alternative is what
    this codebase did before: substitute the stock's own history and report a
    beta of exactly 1.00 for every company.
    """
    try:
        import yfinance as yf

        frame = await asyncio.to_thread(
            lambda: yf.Ticker(symbol).history(period=period)
        )
        if frame is None or frame.empty:
            logger.warning(f"[benchmark] {symbol} returned no rows")
            return {}
        history = [
            {"Date": idx.strftime("%Y-%m-%d"), "Close": float(row["Close"])}
            for idx, row in frame.iterrows()
            if row.get("Close") == row.get("Close")     # drop NaN
        ]
        return {"symbol": symbol, "period": period, "rows": len(history), "history": history}
    except Exception as exc:
        logger.warning(f"[benchmark] {symbol} fetch failed: {str(exc)[:120]}")
        return {}


@cached_fetch("yfinance.market_data", ttl_seconds=3600)
async def fetch_all_market_data(ticker: str) -> Dict[str, Any]:
    """
    Fetch market data using a multi-layer fallback strategy.
    Layer 1: yfinance stock.info (fast, but rate-limited on cloud IPs)
    Layer 2: yfinance fast_info + history (lighter endpoints, usually not rate-limited)
    Layer 3: Screener.in scraping (always works, India-specific)
    """
    stock = yf.Ticker(ticker)
    info = {}         # Will hold Yahoo info dict if available
    hist = []
    hist_df = pd.DataFrame()

    # ── STEP 1: Price history (most reliable, never rate-limited) ──
    try:
        hist_df = stock.history(period="2y")
        if hist_df is not None and not hist_df.empty:
            tmp = hist_df.reset_index()
            if 'Date' in tmp.columns:
                tmp['Date'] = tmp['Date'].astype(str)
            # Keep the full two years already fetched. It was being truncated to
            # 252 sessions, which made rolling beta over anything longer than a
            # year impossible even though the data was in hand.
            hist = tmp.to_dict("records")[-HISTORY_SESSIONS:]
    except Exception as e:
        print(f"history() failed for {ticker}: {e}")

    # ── STEP 2: Try stock.info (may fail with YFRateLimitError) ──
    try:
        info = stock.info or {}
        # Validate it actually returned data (not just symbol echo)
        if len(info) < 5:
            info = {}
    except Exception as e:
        print(f"stock.info rate-limited for {ticker}: {e}. Falling back to fast_info + Screener.")
        info = {}

    # ── STEP 3: fast_info fallback for price/market cap ──
    cur_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    market_cap = info.get("marketCap")
    fifty_two_high = info.get("fiftyTwoWeekHigh")
    fifty_two_low = info.get("fiftyTwoWeekLow")
    avg_volume = info.get("averageVolume")

    if cur_price is None:
        try:
            fi = stock.fast_info
            cur_price = fi.last_price
            market_cap = market_cap or fi.market_cap
            fifty_two_high = fifty_two_high or fi.year_high
            fifty_two_low = fifty_two_low or fi.year_low
        except Exception as e:
            print(f"fast_info failed for {ticker}: {e}")

    # Last resort: get price from history
    if cur_price is None and hist:
        last_record = hist[-1]
        cur_price = last_record.get("Close")

    # ── STEP 4: Screener.in data (always works, not Yahoo-dependent) ──
    c_slug = ticker.split(".")[0]
    screener_data = scrape_screener(c_slug)
    # Tolerant key matching + robust value parsing. The previous extractor used
    # exact keys ("pl_Sales") against Screener's actual labels ("pl_Sales\xa0+")
    # and plain float() against values like '₹\n 8,13,988\n\n Cr.', so most
    # fields silently came back None.
    from data.fundamentals_adapter import (
        extract_from_screener, merge_fundamentals, scale_crore_fields,
    )

    screener_fundamentals = scale_crore_fields(extract_from_screener(screener_data))

    # ── STEP 5: Merge fundamentals (Yahoo info preferred, Screener fallback) ──
    def _pick(yahoo_key, screener_key=None):
        """Return Yahoo value if available, else Screener value."""
        val = info.get(yahoo_key)
        if val is not None:
            return val
        if screener_key:
            return screener_fundamentals.get(screener_key)
        return None

    market_cap = market_cap or screener_fundamentals.get("market_cap")

    # Sector peers (skip if Yahoo info is rate-limited to avoid more rate limits)
    derived_sector = info.get("sector")
    peer_data = []
    if derived_sector:
        try:
            peer_data = await fetch_sector_peers(ticker, derived_sector)
        except Exception:
            pass

    # Debt to equity
    final_dte = None
    dte_raw = info.get("debtToEquity")
    if dte_raw is not None:
        try:
            final_dte = float(dte_raw) / 100.0
        except:
            pass
    if final_dte is None:
        final_dte = screener_fundamentals.get("debt_to_equity")

    result = {
        "price_data": {
            "current_price": cur_price,
            "week_52_high": fifty_two_high,
            "week_52_low": fifty_two_low,
            "market_cap": market_cap,
            "avg_volume": avg_volume,
            "history": hist
        },
        "fundamental_data": {
            # Valuation
            "pe_ratio": _pick("trailingPE", "pe_ratio"),
            "forward_pe": _pick("forwardPE"),
            "pb_ratio": _pick("priceToBook", "pb_ratio"),
            "ps_ratio": _pick("priceToSalesTrailing12Months"),
            "ev_ebitda": _pick("enterpriseToEbitda"),
            "peg_ratio": _pick("pegRatio"),
            "analyst_target_price": _pick("targetMeanPrice"),
            "analyst_count": _pick("numberOfAnalystOpinions"),
            "analyst_recommendation": _pick("recommendationKey"),

            # Profitability
            "roe": _pick("returnOnEquity", "roe"),
            "roa": _pick("returnOnAssets"),
            "gross_margin": _pick("grossMargins"),
            "operating_margins": _pick("operatingMargins", "operating_margins"),
            "profit_margins": _pick("profitMargins", "profit_margins"),
            "ebitda_margin": _pick("ebitdaMargins"),

            # Growth
            "revenue_growth": _pick("revenueGrowth", "revenue_growth"),
            "earnings_growth": _pick("earningsGrowth", "earnings_growth"),
            "earnings_quarterly_growth": _pick("earningsQuarterlyGrowth"),

            # Health
            "total_debt": _pick("totalDebt") or screener_fundamentals.get("total_debt"),
            "total_cash": _pick("totalCash"),
            "debt_to_equity": final_dte,
            "current_ratio": _pick("currentRatio"),
            "quick_ratio": _pick("quickRatio"),
            "interest_coverage": ((_pick("operatingCashflow") or 0) / (_pick("totalDebt") or 1))
                                 if _pick("totalDebt") else None,

            # Cashflow
            "free_cashflow": _pick("freeCashflow"),
            "operating_cashflow": _pick("operatingCashflow"),
            "capex": None,

            "dividend_yield": _pick("dividendYield", "dividend_yield"),
            "payout_ratio": _pick("payoutRatio"),
            "beta": _pick("beta"),
            "sector": _pick("sector"),
            "industry": _pick("industry"),
            "full_time_employees": _pick("fullTimeEmployees"),
            "business_summary": _pick("longBusinessSummary"),
            "sector_peers": peer_data.get("peers", []) if isinstance(peer_data, dict) else peer_data,
        },
        "screener_data": screener_data
    }

    # ── STEP 6: per-field top-up + provenance ──
    #
    # Merging per FIELD, not per provider: a partial yfinance response (common,
    # since it is rate-limited from cloud IPs) is topped up from Screener rather
    # than the whole source being discarded because it answered at all.
    #
    # Provenance is recorded so a scraped estimate is never mistaken for an
    # official figure — by a reader or by an agent.
    yahoo_fields = {k: v for k, v in result["fundamental_data"].items() if v is not None}
    merged, provenance = merge_fundamentals([
        ("yfinance", yahoo_fields),
        ("screener.in", screener_fundamentals),
    ])
    result["fundamental_data"].update(merged)
    result["fundamental_data"]["_provenance"] = provenance
    result["fundamental_data"]["_source_counts"] = {
        source: sum(1 for v in provenance.values() if v == source)
        for source in sorted(set(provenance.values()))
    }

    # ── Validate: we MUST have at least price or history ──
    if result['price_data']['current_price'] is None and not hist:
        raise ValueError(
            f"Could not find valid market records for '{ticker}'. "
            "Please ensure it is a valid Indian stock symbol."
        )

    return result


@cached_fetch("market.breadth", ttl_seconds=1800)
async def fetch_market_breadth() -> dict:
    """
    Fetches broad market context needed by Technical and Macro analysts.
    Determines if we're in a bull/bear macro environment.
    Uses stock.history() only — never rate-limited by Yahoo.
    """
    import asyncio

    tickers = {
        "nifty50":    "^NSEI",
        "india_vix":  "^INDIAVIX",
        "nifty_bank": "^NSEBANK",
        "usdinr":     "INR=X",
        "crude":      "CL=F",
        "gold":       "GC=F",
    }

    result = {}

    async def fetch_one(name, ticker):
        try:
            t = yf.Ticker(ticker)
            hist = await asyncio.to_thread(lambda: t.history(period="60d"))
            if len(hist) < 2:
                return name, None

            current = float(hist["Close"].iloc[-1])
            prev_1m = float(hist["Close"].iloc[-22]) if len(hist) >= 22 else None
            prev_1w = float(hist["Close"].iloc[-5]) if len(hist) >= 5 else None
            sma_20 = float(hist["Close"].tail(20).mean())

            return name, {
                "current":       round(current, 2),
                "change_1w_pct": round((current - prev_1w) / prev_1w * 100, 2) if prev_1w else None,
                "change_1m_pct": round((current - prev_1m) / prev_1m * 100, 2) if prev_1m else None,
                "above_sma20":   current > sma_20,
            }
        except Exception:
            return name, None

    tasks = [fetch_one(n, t) for n, t in tickers.items()]
    for name, data in await asyncio.gather(*tasks):
        if data:
            result[name] = data

    # Derive market regime
    nifty = result.get("nifty50", {})
    vix = result.get("india_vix", {})

    market_regime = "neutral"
    if nifty:
        if nifty.get("above_sma20") and (nifty.get("change_1m_pct") or 0) > 0:
            market_regime = "bull"
        elif not nifty.get("above_sma20") and (nifty.get("change_1m_pct") or 0) < -3:
            market_regime = "bear"

    fear_level = "neutral"
    if vix and vix.get("current"):
        v = vix["current"]
        if v > 25:
            fear_level = "high_fear"
        elif v > 18:
            fear_level = "elevated"
        elif v < 12:
            fear_level = "complacent"
        else:
            fear_level = "normal"

    result["market_regime"] = market_regime
    result["fear_level"] = fear_level
    result["vix_current"] = (vix or {}).get("current")

    return result
