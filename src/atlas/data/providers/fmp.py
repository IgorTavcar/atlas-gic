"""Financial Modeling Prep (FMP) data adapter.

Extracted from artcompany's market_data module.  All functions take
``api_key`` as an explicit parameter — no global config import.
"""

from typing import Optional

_BASE = "https://financialmodelingprep.com/api/v3"


def _get(endpoint: str, params: dict, api_key: str) -> Optional[dict | list]:
    import requests
    params["apikey"] = api_key
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def quote(ticker: str, api_key: str) -> Optional[dict]:
    data = _get(f"quote/{ticker}", {}, api_key)
    if data and isinstance(data, list):
        return data[0]
    return None


def historical_price(
    ticker: str, from_date: str, to_date: str, api_key: str
) -> Optional[list]:
    data = _get(
        f"historical-price-full/{ticker}",
        {"from": from_date, "to": to_date},
        api_key,
    )
    if data and "historical" in data:
        return data["historical"]
    return None


def sector_performance(api_key: str) -> Optional[list]:
    return _get("sector-performance", {}, api_key)


def economic_calendar(
    from_date: str, to_date: str, api_key: str
) -> Optional[list]:
    return _get("economic_calendar", {"from": from_date, "to": to_date}, api_key)
