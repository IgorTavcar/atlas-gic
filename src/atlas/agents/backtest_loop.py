"""Main backtest loop: runs ATLAS across historical dates.

Adapted from artcompany — all functions receive ``config`` and ``llm``.
Portfolio management included (buy/sell execution, mark-to-market).
"""

import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..utils.llm import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Portfolio persistence
# ---------------------------------------------------------------------------

def _portfolio_path(config: "Config") -> Path:
    return config.data_dir / "state" / "portfolio.json"


def _trajectory_path(config: "Config") -> Path:
    return config.data_dir / "backtest" / "portfolio_trajectory.csv"


def load_portfolio(config: "Config") -> dict:
    path = _portfolio_path(config)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {
        "cash": config.starting_capital,
        "positions": {},
        "total_value": config.starting_capital,
        "trade_history": [],
    }


def save_portfolio(portfolio: dict, config: "Config") -> None:
    path = _portfolio_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(portfolio, f, indent=2)


# ---------------------------------------------------------------------------
# Portfolio operations
# ---------------------------------------------------------------------------

def mark_to_market(portfolio: dict, date: str, config: "Config") -> dict:
    from .market_data import get_stock_data
    total = portfolio["cash"]
    for ticker, pos in portfolio["positions"].items():
        data = get_stock_data(ticker, date, config)
        price = data.get("price") or pos.get("avg_price", 0)
        total += pos["shares"] * price
    portfolio["total_value"] = total
    return portfolio


def execute_actions(portfolio: dict, actions: list, date: str, config: "Config") -> dict:
    from .market_data import get_stock_data
    for action in actions:
        ticker = action.get("ticker")
        act = (action.get("action") or "").upper()
        shares = int(action.get("shares", 0))
        if not ticker or not act or shares <= 0:
            continue
        data = get_stock_data(ticker, date, config)
        price = data.get("price")
        if not price:
            logger.warning("No price for %s, skipping %s", ticker, act)
            continue

        if act == "BUY":
            cost = shares * price
            if cost > portfolio["cash"]:
                shares = int(portfolio["cash"] * 0.95 / price)
                cost = shares * price
            if shares <= 0:
                continue
            existing = portfolio["positions"].get(
                ticker, {"shares": 0, "avg_price": 0, "entry_date": date}
            )
            total_shares = existing["shares"] + shares
            avg = (
                (existing["shares"] * existing["avg_price"] + shares * price) / total_shares
                if total_shares > 0 else price
            )
            portfolio["positions"][ticker] = {
                "shares": total_shares, "avg_price": avg,
                "entry_date": existing.get("entry_date", date),
            }
            portfolio["cash"] -= cost
            logger.info("BUY %s %s @ $%.2f", shares, ticker, price)

        elif act == "SELL":
            if ticker not in portfolio["positions"]:
                continue
            pos = portfolio["positions"][ticker]
            sell = min(shares, pos["shares"])
            portfolio["cash"] += sell * price
            pos["shares"] -= sell
            if pos["shares"] <= 0:
                del portfolio["positions"][ticker]
            logger.info("SELL %s %s @ $%.2f", sell, ticker, price)

        portfolio["trade_history"].append({
            "date": date, "ticker": ticker, "action": act,
            "shares": shares, "price": price,
        })
    return portfolio


def _append_trajectory(
    day: int, date: str, portfolio: dict, prev_value: float, config: "Config",
) -> None:
    path = _trajectory_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = portfolio["total_value"]
    daily = (value / prev_value - 1) * 100 if prev_value > 0 else 0
    cumulative = (value / config.starting_capital - 1) * 100
    exists = path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["day", "date", "portfolio_value", "daily_return_pct", "cumulative_return_pct"])
        w.writerow([day, date, f"{value:.2f}", f"{daily:.4f}", f"{cumulative:.4f}"])


def _trading_dates(start: str, end: str) -> list[str]:
    dates = []
    cur = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while cur <= end_dt:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run_backtest(
    start_date: str, end_date: str, config: "Config", llm: "LLMClient",
    resume: bool = False,
) -> dict:
    """Run the full backtest from *start_date* to *end_date*."""
    from .eod_cycle import run_full_cycle
    from .scorecard import update_forward_returns, update_darwinian_weights, load_darwinian_weights
    from .autoresearch import maybe_run_autoresearch

    dates = _trading_dates(start_date, end_date)
    logger.info("Starting backtest: %s to %s (%s trading days)", start_date, end_date, len(dates))

    if resume:
        portfolio = load_portfolio(config)
    else:
        portfolio = {
            "cash": config.starting_capital, "positions": {},
            "total_value": config.starting_capital, "trade_history": [],
        }
        save_portfolio(portfolio, config)
        traj = _trajectory_path(config)
        if traj.exists():
            traj.unlink()

    prev_value = portfolio["total_value"]
    day_num = 0

    for day_num, date in enumerate(dates, start=1):
        logger.info("Day %s/%s: %s | $%s", day_num, len(dates), date, f"{portfolio['total_value']:,.0f}")
        try:
            update_forward_returns(date, config)
            from .market_data import get_market_snapshot
            market_data = get_market_snapshot(date, config)
            weights = load_darwinian_weights(config)
            cio = run_full_cycle(market_data, portfolio, config, llm, weights)
            actions = cio.get("actions") or cio.get("portfolio_actions", [])
            portfolio = execute_actions(portfolio, actions, date, config)
            portfolio = mark_to_market(portfolio, date, config)
            update_darwinian_weights(date, config)
            maybe_run_autoresearch(date, day_num, config, llm)
            save_portfolio(portfolio, config)
            _append_trajectory(day_num, date, portfolio, prev_value, config)
            prev_value = portfolio["total_value"]
        except KeyboardInterrupt:
            logger.info("Backtest interrupted")
            break
        except Exception as exc:
            logger.error("Error on day %s (%s): %s", day_num, date, exc, exc_info=True)
            _append_trajectory(day_num, date, portfolio, prev_value, config)
            continue

    final_return = (portfolio["total_value"] / config.starting_capital - 1) * 100
    logger.info("Backtest complete! %s days, $%s, %.1f%%", day_num, f"{portfolio['total_value']:,.0f}", final_return)
    return {
        "start_date": start_date,
        "end_date": dates[day_num - 1] if dates else end_date,
        "trading_days": day_num,
        "starting_value": config.starting_capital,
        "ending_value": portfolio["total_value"],
        "total_return_pct": final_return,
    }


def run_simple_backtest(
    days: int, config: "Config", llm: "LLMClient",
) -> None:
    """Lightweight mode: N days of simple agent scoring (josjo80 style)."""
    from .market_data import get_simple_market_data
    from .scorecard import load_darwinian_weights

    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
    from ..config import ALL_AGENTS
    agents = ALL_AGENTS

    logger.info("Data: %s | LLM: %s", "real" if config.has_market_data else "mock", "real" if llm.is_real else "mock")

    for day in range(1, days + 1):
        logger.info("Day %s", day)
        snap = get_simple_market_data(tickers, config)
        # Simple scoring: each agent gets a score per ticker
        signals = []
        ticker_list = list(snap.get("prices", {}).keys()) or tickers
        for i, agent in enumerate(agents):
            ticker = ticker_list[i % len(ticker_list)]
            score = llm.score_agent(agent, ticker, snap)
            signals.append({"agent": agent, "ticker": ticker, "score": score})

        top = sorted(signals, key=lambda s: s["score"], reverse=True)[:3]
        logger.info("Top: %s | source=%s", [(s["agent"], s["score"]) for s in top], snap.get("source"))
