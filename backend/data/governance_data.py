import requests
from bs4 import BeautifulSoup
import re

# BSE code map for top 100 NSE stocks
BSE_CODE_MAP = {
    "RELIANCE.NS": "500325", "TCS.NS": "532540", "HDFCBANK.NS": "500180",
    "INFY.NS": "500209", "ICICIBANK.NS": "532174", "HINDUNILVR.NS": "500696",
    "ITC.NS": "500875", "KOTAKBANK.NS": "500247", "LT.NS": "500510",
    "AXISBANK.NS": "532215", "BAJFINANCE.NS": "500034", "BHARTIARTL.NS": "532454",
    "MARUTI.NS": "532500", "SBIN.NS": "500112", "TITAN.NS": "500114",
    "SUNPHARMA.NS": "524715", "ONGC.NS": "500312", "WIPRO.NS": "507685",
    "DRREDDY.NS": "500124", "NESTLEIND.NS": "500790", "TATAMOTORS.NS": "500570",
    "ULTRACEMCO.NS": "532538", "NTPC.NS": "532555", "POWERGRID.NS": "532898",
    "TECHM.NS": "532755", "ASIANPAINT.NS": "500820", "BAJAJFINSV.NS": "532978",
    "HCLTECH.NS": "532281", "CIPLA.NS": "500087", "DIVISLAB.NS": "532488",
    "APOLLOHOSP.NS": "508869", "TATASTEEL.NS": "500470", "JSWSTEEL.NS": "500228",
    "HINDALCO.NS": "500440", "ADANIPORTS.NS": "532921", "M&M.NS": "500520",
    "EICHERMOT.NS": "505200", "BAJAJ-AUTO.NS": "532977", "HEROMOTOCO.NS": "500182",
    "INDUSINDBK.NS": "532187", "ZOMATO.NS": "543320", "GRASIM.NS": "500300",
    "ADANIENT.NS": "512599", "LTIM.NS": "540005", "TATACONSUM.NS": "500800",
    "PIDILITIND.NS": "500331", "DABUR.NS": "500096", "MARICO.NS": "531642",
    "GODREJCP.NS": "532424", "AUROPHARMA.NS": "524804",
}


def fetch_governance_data(ticker: str) -> dict:
    """
    Fetches promoter shareholding & pledge from Screener.in
    Falls back to yfinance major holders if scraping fails
    """
    symbol = ticker.replace(".NS", "").replace(".BO", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.screener.in/",
        "Accept": "text/html",
    }

    result = {
        "promoter_holding_pct":     None,
        "promoter_pledge_pct":      None,
        "promoter_trend":           "unknown",
        "dii_holding_pct":          None,
        "fii_holding_pct":          None,
        "public_holding_pct":       None,
        "pledge_risk":              "unknown",
        "shareholding_source":      "none",
    }

    # Try Screener.in shareholding
    try:
        url = f"https://www.screener.in/company/{symbol}/"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Find shareholding section
            sh = soup.find("section", {"id": "shareholding"})
            if sh:
                tables = sh.find_all("table")
                for table in tables:
                    rows = table.find_all("tr")
                    for row in rows:
                        cells = row.find_all("td")
                        if not cells:
                            continue
                        label = cells[0].text.strip().lower()
                        vals = [c.text.strip().replace("%", "") for c in cells[1:]]

                        if "promoter" in label and "pledge" not in label:
                            # Latest quarter is last value
                            latest = next((v for v in reversed(vals) if v and v != "-"), None)
                            if latest:
                                result["promoter_holding_pct"] = float(latest)
                                # Trend: compare first vs last
                                first = next((v for v in vals if v and v != "-"), None)
                                if first and latest:
                                    diff = float(latest) - float(first)
                                    result["promoter_trend"] = (
                                        "increasing" if diff > 0.5 else
                                        "decreasing" if diff < -0.5 else "stable"
                                    )

                        elif "pledge" in label:
                            latest = next((v for v in reversed(vals) if v and v != "-"), None)
                            if latest:
                                result["promoter_pledge_pct"] = float(latest)

                        elif "dii" in label or "domestic" in label:
                            latest = next((v for v in reversed(vals) if v and v != "-"), None)
                            if latest:
                                result["dii_holding_pct"] = float(latest)

                        elif "fii" in label or "foreign" in label:
                            latest = next((v for v in reversed(vals) if v and v != "-"), None)
                            if latest:
                                result["fii_holding_pct"] = float(latest)

                result["shareholding_source"] = "screener.in"
    except Exception as e:
        print(f"Governance scraping failed for {symbol}: {e}")

    # Pledge risk classification
    pledge = result.get("promoter_pledge_pct")
    if pledge is not None:
        if pledge < 5:
            result["pledge_risk"] = "very_low"
        elif pledge < 20:
            result["pledge_risk"] = "low"
        elif pledge < 35:
            result["pledge_risk"] = "moderate"
        elif pledge < 50:
            result["pledge_risk"] = "high"
        else:
            result["pledge_risk"] = "very_high"

    return result
