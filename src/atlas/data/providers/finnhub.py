"""Finnhub market data adapter.

Combines josjo80's clean quote adapter with artcompany's news/sentiment
functions.  Free tier: 60 req/min.
"""

import time
from typing import Dict, List, Optional, Tuple

_BASE = "https://finnhub.io/api/v1"
_DELAY = 0.1  # well within free-tier limits


def _get(endpoint: str, params: dict, api_key: str) -> Optional[dict | list]:
    import requests
    params["token"] = api_key
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


# -- Quotes (josjo80) ------------------------------------------------------

def fetch_quotes(tickers: List[str], api_key: str) -> Dict[str, Tuple[float, float]]:
    """Return ``{ticker: (price, daily_return)}``."""
    import requests
    results: Dict[str, Tuple[float, float]] = {}
    for ticker in tickers:
        resp = requests.get(
            f"{_BASE}/quote",
            params={"symbol": ticker, "token": api_key},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data["c"])
        pct = float(data.get("dp", 0))
        results[ticker] = (price, round(pct / 100, 6))
        time.sleep(_DELAY)
    return results


# -- News / sentiment (artcompany) -----------------------------------------

def fetch_market_news(api_key: str, category: str = "general") -> Optional[list]:
    return _get("news", {"category": category}, api_key)


def fetch_company_news(
    ticker: str, from_date: str, to_date: str, api_key: str
) -> Optional[list]:
    return _get(
        "company-news",
        {"symbol": ticker, "from": from_date, "to": to_date},
        api_key,
    )


def fetch_quote(ticker: str, api_key: str) -> Optional[dict]:
    return _get("quote", {"symbol": ticker}, api_key)


def fetch_sentiment(ticker: str, api_key: str) -> Optional[dict]:
    return _get("news-sentiment", {"symbol": ticker}, api_key)
