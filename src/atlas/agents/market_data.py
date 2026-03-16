"""Market data: comprehensive snapshot builder with mock fallback.

Merges josjo80's simple MarketSnapshot with artcompany's full macro/sector
data collection.  Falls back to mock data when API keys are absent.
"""

import logging
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock fallback
# ---------------------------------------------------------------------------

def _mock_snapshot(date: str) -> dict:
    """Generate a plausible mock market snapshot."""
    return {
        "date": date,
        "source": "mock",
        "macro": {
            "fed_funds_rate": 4.5,
            "yield_2y": 4.2,
            "yield_10y": 4.0,
            "yield_30y": 4.3,
            "real_rate_10y": 1.8,
            "cpi_yoy": 3.2,
            "unemployment": 3.9,
            "credit_spread_hy": 3.5,
        },
        "prices": {
            "SPY": {"name": "S&P 500 ETF", "price": round(random.uniform(420, 530), 2),
                     "change_pct": round(random.uniform(-2, 2), 2)},
            "QQQ": {"name": "Nasdaq ETF", "price": round(random.uniform(360, 480), 2),
                     "change_pct": round(random.uniform(-3, 3), 2)},
            "GLD": {"name": "Gold", "price": round(random.uniform(170, 220), 2),
                     "change_pct": round(random.uniform(-1, 1), 2)},
            "VIX": {"name": "Volatility", "price": round(random.uniform(12, 30), 2),
                     "change_pct": round(random.uniform(-10, 10), 2)},
        },
        "sector_performance": [],
        "headlines": ["[mock] Markets mixed on economic data"],
        "yield_curve_spread": round(random.uniform(-0.5, 1.5), 2),
    }


def _mock_simple(tickers: List[str]) -> dict:
    """Lightweight mock for simple backtest mode."""
    prices = {t: round(random.uniform(20, 500), 2) for t in tickers}
    returns = {t: round(random.uniform(-0.05, 0.05), 4) for t in tickers}
    return {"prices": prices, "returns": returns, "source": "mock"}


# ---------------------------------------------------------------------------
# Real data collection
# ---------------------------------------------------------------------------

_KEY_TICKERS = {
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF", "IWM": "Russell 2000",
    "GLD": "Gold", "USO": "Oil", "UUP": "Dollar", "TLT": "Long Bonds",
    "VIX": "Volatility Index", "EEM": "Emerging Markets", "HYG": "High Yield",
}

_FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "yield_2y": "DGS2",
    "yield_10y": "DGS10",
    "yield_30y": "DGS30",
    "real_rate_10y": "DFII10",
    "cpi_yoy": "CPIAUCSL",
    "unemployment": "UNRATE",
    "credit_spread_hy": "BAMLH0A0HYM2",
    "credit_spread_ig": "BAMLC0A0CM",
}


def get_market_snapshot(date: str, config: "Config") -> dict:
    """Build a comprehensive market snapshot for the given date.

    Uses FMP for prices/sectors, Finnhub for news, FRED for macro.
    Falls back to mock when any provider key is missing.
    """
    if not config.has_market_data:
        return _mock_snapshot(date)

    snapshot: dict = {"date": date, "source": "live"}

    # -- FRED macro --
    macro: Dict[str, Optional[float]] = {}
    if config.fred_api_key:
        from ..data.providers.fred import series_latest
        for label, sid in _FRED_SERIES.items():
            macro[label] = series_latest(sid, config.fred_api_key)
    snapshot["macro"] = macro

    # -- FMP prices --
    prices: dict = {}
    if config.fmp_api_key:
        from ..data.providers.fmp import quote as fmp_quote, sector_performance
        for ticker, name in _KEY_TICKERS.items():
            q = fmp_quote(ticker, config.fmp_api_key)
            if q:
                prices[ticker] = {
                    "name": name,
                    "price": q.get("price"),
                    "change_pct": q.get("changesPercentage"),
                    "volume": q.get("volume"),
                }
        snapshot["sector_performance"] = (sector_performance(config.fmp_api_key) or [])[:10]
    snapshot["prices"] = prices

    # -- Finnhub news --
    headlines: List[str] = []
    if config.finnhub_api_key:
        from ..data.providers.finnhub import fetch_market_news
        news = fetch_market_news(config.finnhub_api_key) or []
        headlines = [n.get("headline", "") for n in news[:15] if n.get("headline")]
    snapshot["headlines"] = headlines

    # Derived
    y10 = macro.get("yield_10y")
    y2 = macro.get("yield_2y")
    snapshot["yield_curve_spread"] = (y10 - y2) if y10 and y2 else None

    return snapshot


def get_simple_market_data(tickers: List[str], config: "Config") -> dict:
    """Lightweight price/return snapshot for simple backtest mode.

    Priority: Finnhub -> mock.
    """
    if config.finnhub_api_key:
        try:
            from ..data.providers.finnhub import fetch_quotes
            quotes = fetch_quotes(tickers, config.finnhub_api_key)
            prices = {t: v[0] for t, v in quotes.items()}
            returns = {t: v[1] for t, v in quotes.items()}
            return {"prices": prices, "returns": returns, "source": "finnhub"}
        except Exception as exc:
            logger.warning("Finnhub fetch failed (%s); falling back to mock", exc)

    return _mock_simple(tickers)


def get_stock_data(ticker: str, date: str, config: "Config") -> dict:
    """Fetch data for a single stock (for portfolio mark-to-market)."""
    if config.fmp_api_key:
        from ..data.providers.fmp import quote as fmp_quote
        q = fmp_quote(ticker, config.fmp_api_key)
        if q:
            return {
                "ticker": ticker, "date": date,
                "price": q.get("price"),
                "change_pct": q.get("changesPercentage"),
                "market_cap": q.get("marketCap"),
            }
    return {"ticker": ticker, "date": date, "price": round(random.uniform(20, 500), 2)}


def get_forward_return(
    ticker: str, entry_date: str, horizon_days: int, config: "Config"
) -> Optional[float]:
    """Calculate forward return from *entry_date* over *horizon_days*."""
    if not config.fmp_api_key:
        return round(random.uniform(-0.10, 0.10), 4)
    try:
        from ..data.providers.fmp import historical_price
        entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
        end_str = (entry_dt + timedelta(days=horizon_days + 10)).strftime("%Y-%m-%d")
        prices = historical_price(ticker, entry_date, end_str, config.fmp_api_key)
        if not prices or len(prices) < 2:
            return None
        prices_sorted = sorted(prices, key=lambda x: x["date"])
        entry_price = prices_sorted[0]["close"]
        target_dt = entry_dt + timedelta(days=horizon_days)
        closest = min(
            prices_sorted,
            key=lambda x: abs((datetime.strptime(x["date"], "%Y-%m-%d") - target_dt).days),
        )
        exit_price = closest["close"]
        return (exit_price - entry_price) / entry_price if entry_price > 0 else None
    except Exception as exc:
        logger.warning("Forward return calc failed for %s: %s", ticker, exc)
        return None
