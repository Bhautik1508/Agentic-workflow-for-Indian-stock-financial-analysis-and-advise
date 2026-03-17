import requests


def fetch_options_signals(symbol: str) -> dict:
    """
    Fetches PCR (Put-Call Ratio) and max pain from NSE options chain.
    symbol: NSE symbol WITHOUT .NS suffix, e.g. 'RELIANCE', 'TCS'
    """
    session = requests.Session()
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    default = {
        "pcr": None, "pcr_signal": "unavailable",
        "max_call_oi_strike": None, "max_put_oi_strike": None,
        "total_call_oi": None, "total_put_oi": None,
        "atm_iv": None, "iv_signal": "unavailable",
    }

    try:
        # Warm up session with NSE homepage (get cookies)
        session.get(
            "https://www.nseindia.com",
            headers={**base_headers, "Accept": "text/html"},
            timeout=10,
        )

        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"
        resp = session.get(
            url,
            headers={**base_headers, "Referer": "https://www.nseindia.com/option-chain"},
            timeout=15,
        )

        if resp.status_code != 200:
            return default

        records = resp.json().get("records", {}).get("data", [])
        if not records:
            return default

        # Aggregate OI
        call_oi_map = {}
        put_oi_map = {}
        total_call_oi = 0
        total_put_oi = 0

        for r in records:
            strike = r.get("strikePrice", 0)
            if r.get("CE"):
                oi = r["CE"].get("openInterest", 0)
                call_oi_map[strike] = call_oi_map.get(strike, 0) + oi
                total_call_oi += oi
            if r.get("PE"):
                oi = r["PE"].get("openInterest", 0)
                put_oi_map[strike] = put_oi_map.get(strike, 0) + oi
                total_put_oi += oi

        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

        # PCR signal (Indian market calibration)
        if pcr is None:
            pcr_signal = "unavailable"
        elif pcr >= 1.3:
            pcr_signal = "bullish"          # excess puts = contrarian bullish
        elif pcr >= 0.8:
            pcr_signal = "neutral"
        elif pcr >= 0.5:
            pcr_signal = "mildly_bearish"
        else:
            pcr_signal = "bearish"

        # Max OI strikes (natural support/resistance)
        max_call_strike = max(call_oi_map, key=call_oi_map.get) if call_oi_map else None
        max_put_strike = max(put_oi_map, key=put_oi_map.get) if put_oi_map else None

        # ATM IV (find strike closest to current price)
        underlying_price = resp.json().get("records", {}).get("underlyingValue", 0)
        atm_iv = None
        if underlying_price and records:
            atm_record = min(records, key=lambda r: abs(r.get("strikePrice", 0) - underlying_price))
            if atm_record.get("CE"):
                atm_iv = atm_record["CE"].get("impliedVolatility")

        iv_signal = "unavailable"
        if atm_iv:
            if atm_iv > 40:
                iv_signal = "very_high_iv"      # elevated risk / event expected
            elif atm_iv > 25:
                iv_signal = "high_iv"
            elif atm_iv > 15:
                iv_signal = "normal_iv"
            else:
                iv_signal = "low_iv"            # complacency

        return {
            "pcr": pcr, "pcr_signal": pcr_signal,
            "max_call_oi_strike": max_call_strike,
            "max_put_oi_strike": max_put_strike,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "atm_iv": atm_iv, "iv_signal": iv_signal,
            "underlying_price": underlying_price,
        }

    except Exception as e:
        return {**default, "error": str(e)}
