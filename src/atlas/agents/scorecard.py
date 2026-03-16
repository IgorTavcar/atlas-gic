"""Agent scorecard: tracks recommendations, rolling Sharpe, Darwinian weights.

Adapted from artcompany — replaces numpy with stdlib ``statistics``.
All functions receive ``config`` as a parameter.
"""

import json
import logging
from pathlib import Path
from statistics import mean, stdev
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

def _scorecard_path(config: "Config") -> Path:
    return config.data_dir / "track_record" / "scorecard.json"


def _weights_path(config: "Config") -> Path:
    return config.data_dir / "state" / "darwinian_weights.json"


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_scorecard(config: "Config") -> dict:
    path = _scorecard_path(config)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    from ..config import ALL_AGENTS
    return {
        "recommendations": [],
        "agent_stats": {a: {"total": 0, "scored": 0} for a in ALL_AGENTS},
    }


def save_scorecard(sc: dict, config: "Config") -> None:
    path = _scorecard_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(sc, f, indent=2)


def load_darwinian_weights(config: "Config") -> dict:
    path = _weights_path(config)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    from ..config import DEFAULT_DARWINIAN_WEIGHTS
    weights = dict(DEFAULT_DARWINIAN_WEIGHTS)
    save_darwinian_weights(weights, config)
    return weights


def save_darwinian_weights(weights: dict, config: "Config") -> None:
    path = _weights_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(weights, f, indent=2)


# ---------------------------------------------------------------------------
# Recommendation logging
# ---------------------------------------------------------------------------

def log_recommendation(
    agent_name: str, date: str, ticker: str, direction: str,
    conviction: int, config: "Config",
    entry_price: Optional[float] = None,
) -> None:
    sc = load_scorecard(config)
    sc["recommendations"].append({
        "agent": agent_name, "date": date, "ticker": ticker,
        "direction": direction, "conviction": conviction,
        "entry_price": entry_price,
        "return_1d": None, "return_5d": None, "return_20d": None,
        "scored": False,
    })
    sc["agent_stats"].setdefault(agent_name, {"total": 0, "scored": 0})
    sc["agent_stats"][agent_name]["total"] += 1
    save_scorecard(sc, config)


# ---------------------------------------------------------------------------
# Forward returns
# ---------------------------------------------------------------------------

def update_forward_returns(date: str, config: "Config") -> None:
    from datetime import datetime
    from ..agents.market_data import get_forward_return

    sc = load_scorecard(config)
    today = datetime.strptime(date, "%Y-%m-%d")
    updated = 0

    for rec in sc["recommendations"]:
        if rec["scored"]:
            continue
        rec_date = datetime.strptime(rec["date"], "%Y-%m-%d")
        elapsed = (today - rec_date).days

        if elapsed >= 1 and rec["return_1d"] is None:
            rec["return_1d"] = get_forward_return(rec["ticker"], rec["date"], 1, config)
        if elapsed >= 7 and rec["return_5d"] is None:
            rec["return_5d"] = get_forward_return(rec["ticker"], rec["date"], 5, config)
        if elapsed >= 30 and rec["return_20d"] is None:
            rec["return_20d"] = get_forward_return(rec["ticker"], rec["date"], 20, config)
            if rec["return_20d"] is not None:
                rec["scored"] = True
                sc["agent_stats"].setdefault(rec["agent"], {"total": 0, "scored": 0})
                sc["agent_stats"][rec["agent"]]["scored"] += 1
                updated += 1

    if updated:
        save_scorecard(sc, config)
        logger.info("Updated forward returns for %s recommendations", updated)


# ---------------------------------------------------------------------------
# Sharpe calculation (stdlib, no numpy)
# ---------------------------------------------------------------------------

def calculate_agent_sharpe(
    agent_name: str, config: "Config",
    lookback_days: int = 60, horizon: str = "5d",
) -> Optional[float]:
    sc = load_scorecard(config)
    field = f"return_{horizon}"
    relevant = [
        r for r in sc["recommendations"]
        if r["agent"] == agent_name and r.get(field) is not None
    ]
    if len(relevant) < 5:
        return None

    returns = []
    for rec in relevant[-lookback_days:]:
        raw = rec[field]
        weighted = raw * (rec["conviction"] / 100)
        if rec["direction"] == "SHORT":
            weighted *= -1
        returns.append(weighted)

    if len(returns) < 3:
        return None
    s = stdev(returns)
    if s == 0:
        return 0.0
    return mean(returns) / s


def get_all_agent_sharpes(config: "Config", lookback_days: int = 60) -> Dict[str, Optional[float]]:
    from ..config import ALL_AGENTS
    return {a: calculate_agent_sharpe(a, config, lookback_days) for a in ALL_AGENTS}


def get_worst_agent(
    config: "Config", lookback_days: int = 60, exclude: set | None = None,
) -> Optional[str]:
    sharpes = get_all_agent_sharpes(config, lookback_days)
    ex = exclude or set()
    candidates = {a: s for a, s in sharpes.items() if s is not None and a not in ex}
    if not candidates:
        return None
    return min(candidates, key=lambda a: candidates[a])


# ---------------------------------------------------------------------------
# Darwinian weight updates
# ---------------------------------------------------------------------------

def update_darwinian_weights(date: str, config: "Config") -> dict:
    sharpes = get_all_agent_sharpes(config, lookback_days=20)
    scored = {a: s for a, s in sharpes.items() if s is not None}
    if len(scored) < 4:
        logger.info("Not enough scored agents for Darwinian weight update")
        return load_darwinian_weights(config)

    weights = load_darwinian_weights(config)
    sorted_agents = sorted(scored.items(), key=lambda x: x[1])
    n = len(sorted_agents)
    q = max(1, n // 4)
    bottom = {a for a, _ in sorted_agents[:q]}
    top = {a for a, _ in sorted_agents[-q:]}

    for agent in scored:
        if agent in top:
            weights[agent] = min(
                config.darwinian_weight_ceiling,
                weights.get(agent, 1.0) * config.darwinian_reward_multiplier,
            )
        elif agent in bottom:
            weights[agent] = max(
                config.darwinian_weight_floor,
                weights.get(agent, 1.0) * config.darwinian_penalty_multiplier,
            )

    save_darwinian_weights(weights, config)
    logger.info("Updated Darwinian weights on %s", date)
    return weights
