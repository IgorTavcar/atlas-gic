"""End-of-day cycle: orchestrates all 25 agents through 4 layers.

Adapted from artcompany — each layer feeds structured JSON to the next.
All functions receive ``config`` and ``llm`` as explicit parameters.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..utils.llm import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt(agent_name: str, config: "Config") -> str:
    for layer_dir in ("layer1", "layer2", "layer3", "layer4"):
        path = config.prompts_dir / layer_dir / f"{agent_name}.md"
        if path.exists():
            return path.read_text()
    raise FileNotFoundError(f"Prompt not found for agent: {agent_name}")


def _state_dir(config: "Config") -> Path:
    d = config.data_dir / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_state(filename: str, data: dict, config: "Config") -> None:
    path = _state_dir(config) / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Layer 1 — Macro
# ---------------------------------------------------------------------------

def _run_macro_agent(
    agent_name: str, market_data: dict, weights: dict,
    config: "Config", llm: "LLMClient",
) -> dict:
    prompt = _load_prompt(agent_name, config)
    weight = weights.get(agent_name, 1.0)
    user_msg = (
        f"Date: {market_data.get('date', 'unknown')}\n"
        f"Darwinian weight: {weight:.2f}\n\n"
        f"Market Data:\n{json.dumps(market_data, indent=2)}\n\n"
        "Analyse the data and provide your regime signal. Return ONLY valid JSON."
    )
    from ..utils.logging import log_agent_output
    result = llm.call_agent(prompt, user_msg, agent_name=agent_name)
    log_agent_output(agent_name, market_data.get("date", ""), result, config.log_dir)
    return result


def run_layer1(
    market_data: dict, weights: dict, config: "Config", llm: "LLMClient",
) -> dict:
    from ..config import LAYER1_AGENTS
    logger.info("=== Layer 1: Macro agents ===")
    signals = {}
    for agent in LAYER1_AGENTS:
        logger.info("Running %s", agent)
        signals[agent] = _run_macro_agent(agent, market_data, weights, config, llm)

    regime_votes = {"RISK_ON": 0.0, "RISK_OFF": 0.0, "NEUTRAL": 0.0}
    total_weight = 0.0
    for agent, sig in signals.items():
        regime = sig.get("regime") or sig.get("signal", "NEUTRAL")
        if regime not in regime_votes:
            regime = "NEUTRAL"
        conviction = sig.get("conviction", 50)
        w = weights.get(agent, 1.0)
        regime_votes[regime] += w * conviction
        total_weight += w

    if total_weight > 0:
        winning = max(regime_votes, key=lambda r: regime_votes[r])
        weighted_conv = int(regime_votes[winning] / total_weight)
    else:
        winning, weighted_conv = "NEUTRAL", 50

    macro_out = {
        "regime": winning, "signals": signals, "regime_votes": regime_votes,
        "weighted_conviction": weighted_conv, "date": market_data.get("date"),
    }
    _save_state("macro_regime.json", macro_out, config)
    logger.info("Macro regime: %s (conviction: %s)", winning, weighted_conv)
    return macro_out


# ---------------------------------------------------------------------------
# Layer 2 — Sector desks
# ---------------------------------------------------------------------------

def _run_sector_agent(
    agent_name: str, macro_regime: dict, market_data: dict, weights: dict,
    config: "Config", llm: "LLMClient",
) -> dict:
    prompt = _load_prompt(agent_name, config)
    weight = weights.get(agent_name, 1.0)
    user_msg = (
        f"Date: {market_data.get('date', 'unknown')}\n"
        f"Darwinian weight: {weight:.2f}\n\n"
        f"Macro Regime from Layer 1:\n{json.dumps(macro_regime, indent=2)}\n\n"
        f"Market Data:\n{json.dumps(market_data, indent=2)}\n\n"
        "Analyse your sector and provide recommendations. Return ONLY valid JSON."
    )
    from ..utils.logging import log_agent_output
    result = llm.call_agent(prompt, user_msg, agent_name=agent_name)
    log_agent_output(agent_name, market_data.get("date", ""), result, config.log_dir)
    return result


def run_layer2(
    macro_regime: dict, market_data: dict, weights: dict,
    config: "Config", llm: "LLMClient",
) -> dict:
    from ..config import LAYER2_AGENTS
    logger.info("=== Layer 2: Sector desks ===")
    picks = {}
    for agent in LAYER2_AGENTS:
        logger.info("Running %s", agent)
        picks[agent] = _run_sector_agent(agent, macro_regime, market_data, weights, config, llm)
    sector_out = {"picks": picks, "date": market_data.get("date"), "macro_regime": macro_regime.get("regime")}
    _save_state("sector_picks.json", sector_out, config)
    return sector_out


# ---------------------------------------------------------------------------
# Layer 3 — Superinvestors
# ---------------------------------------------------------------------------

def _run_superinvestor(
    agent_name: str, sector_picks: dict, macro_regime: dict, portfolio: dict,
    weights: dict, date: str, config: "Config", llm: "LLMClient",
) -> dict:
    prompt = _load_prompt(agent_name, config)
    weight = weights.get(agent_name, 1.0)
    user_msg = (
        f"Date: {date}\nDarwinian weight: {weight:.2f}\n\n"
        f"Macro Regime:\n{json.dumps(macro_regime, indent=2)}\n\n"
        f"Sector Desk Recommendations:\n{json.dumps(sector_picks, indent=2)}\n\n"
        f"Current Portfolio:\n{json.dumps(portfolio, indent=2)}\n\n"
        "Review through your investment philosophy. Return ONLY valid JSON."
    )
    from ..utils.logging import log_agent_output
    result = llm.call_agent(prompt, user_msg, agent_name=agent_name)
    log_agent_output(agent_name, date, result, config.log_dir)
    return result


def run_layer3(
    sector_picks: dict, macro_regime: dict, portfolio: dict,
    weights: dict, date: str, config: "Config", llm: "LLMClient",
) -> dict:
    from ..config import LAYER3_AGENTS
    logger.info("=== Layer 3: Superinvestors ===")
    views = {}
    for agent in LAYER3_AGENTS:
        logger.info("Running %s", agent)
        views[agent] = _run_superinvestor(
            agent, sector_picks, macro_regime, portfolio, weights, date, config, llm,
        )
    si_out = {"views": views, "date": date}
    _save_state("superinvestor_views.json", si_out, config)
    return si_out


# ---------------------------------------------------------------------------
# Layer 4 — Decision
# ---------------------------------------------------------------------------

def _run_l4_agent(
    agent_name: str, user_msg: str, date: str, config: "Config", llm: "LLMClient",
) -> dict:
    prompt = _load_prompt(agent_name, config)
    from ..utils.logging import log_agent_output
    result = llm.call_agent(prompt, user_msg, agent_name=agent_name)
    log_agent_output(agent_name, date, result, config.log_dir)
    return result


def run_layer4(
    macro_regime: dict, sector_picks: dict, superinvestor_views: dict,
    portfolio: dict, weights: dict, date: str,
    config: "Config", llm: "LLMClient",
) -> dict:
    logger.info("=== Layer 4: Decision ===")
    all_prior = {"macro": macro_regime, "sectors": sector_picks, "superinvestors": superinvestor_views}

    # CRO
    cro_msg = (
        f"Date: {date}\nDarwinian weight: {weights.get('cro', 1.0):.2f}\n\n"
        f"All Agent Outputs:\n{json.dumps(all_prior, indent=2)}\n\n"
        f"Current Portfolio:\n{json.dumps(portfolio, indent=2)}\n\n"
        "Identify all risks. Return ONLY valid JSON."
    )
    cro_review = _run_l4_agent("cro", cro_msg, date, config, llm)
    _save_state("cro_review.json", cro_review, config)

    # Alpha discovery
    all_with_cro = {**all_prior, "cro": cro_review}
    alpha_msg = (
        f"Date: {date}\nDarwinian weight: {weights.get('alpha_discovery', 1.0):.2f}\n\n"
        f"All Prior Agent Outputs:\n{json.dumps(all_with_cro, indent=2)}\n\n"
        f"Current Portfolio:\n{json.dumps(portfolio, indent=2)}\n\n"
        "Find high-conviction ideas not yet mentioned. Return ONLY valid JSON."
    )
    alpha = _run_l4_agent("alpha_discovery", alpha_msg, date, config, llm)

    # CIO
    all_final = {**all_with_cro, "alpha_discovery": alpha}
    cio_msg = (
        f"Date: {date}\nYour Darwinian weight: {weights.get('cio', 1.0):.2f}\n\n"
        f"All inputs (agents weighted by Darwinian scores):\n"
        f"{json.dumps({'darwinian_weights': weights, 'all_agent_outputs': all_final, 'cro_review': cro_review, 'current_portfolio': portfolio}, indent=2)}\n\n"
        "Make final BUY/SELL/HOLD decisions. Return ONLY valid JSON."
    )
    cio_decisions = _run_l4_agent("cio", cio_msg, date, config, llm)
    _save_state("portfolio_actions.json", cio_decisions, config)
    actions = cio_decisions.get("actions") or cio_decisions.get("portfolio_actions", [])
    logger.info("CIO decisions: %s actions", len(actions))
    return cio_decisions


# ---------------------------------------------------------------------------
# Full cycle
# ---------------------------------------------------------------------------

def run_full_cycle(
    market_data: dict, portfolio: dict, config: "Config", llm: "LLMClient",
    weights: dict | None = None,
) -> dict:
    """Run the complete 4-layer EOD cycle."""
    from ..config import DEFAULT_DARWINIAN_WEIGHTS
    date = market_data.get("date", "")
    logger.info("=== Starting EOD cycle for %s ===", date)
    if weights is None:
        weights = dict(DEFAULT_DARWINIAN_WEIGHTS)

    macro = run_layer1(market_data, weights, config, llm)
    sectors = run_layer2(macro, market_data, weights, config, llm)
    supers = run_layer3(sectors, macro, portfolio, weights, date, config, llm)
    cio = run_layer4(macro, sectors, supers, portfolio, weights, date, config, llm)

    logger.info("=== EOD cycle complete for %s ===", date)
    return cio
