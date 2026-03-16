"""Autoresearch: self-improving agent prompts via Sharpe-guided evolution.

Merges artcompany's full state-machine with josjo80's mock fallback on git
errors.  All branch operations target **main** (not master).
"""

import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..config import Config
    from ..utils.llm import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _ar_log_path(config: "Config") -> Path:
    return config.data_dir / "track_record" / "autoresearch_log.json"


def _ar_state_path(config: "Config") -> Path:
    return config.data_dir / "state" / "autoresearch_state.json"


def _load_ar_log(config: "Config") -> list:
    p = _ar_log_path(config)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return []


def _save_ar_log(log: list, config: "Config") -> None:
    p = _ar_log_path(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(log, f, indent=2)


def _load_ar_state(config: "Config") -> dict:
    p = _ar_state_path(config)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {"active_trial": None, "recently_modified": {}}


def _save_ar_state(state: dict, config: "Config") -> None:
    p = _ar_state_path(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt_path(agent_name: str, config: "Config") -> Optional[Path]:
    for layer in ("layer1", "layer2", "layer3", "layer4"):
        p = config.prompts_dir / layer / f"{agent_name}.md"
        if p.exists():
            return p
    return None


def _generate_modification(
    agent_name: str, current_prompt: str, sharpe: float, llm: "LLMClient",
) -> Optional[dict]:
    """Ask the LLM to propose one targeted prompt modification."""
    system = (
        "You are an AI prompt engineer specialising in financial trading systems.\n"
        "Propose exactly ONE focused change. Return a JSON object with:\n"
        '- "modification": one specific change (1-2 sentences)\n'
        '- "new_prompt": the full updated prompt text'
    )
    user_msg = (
        f"Agent: {agent_name}\nCurrent rolling Sharpe: {sharpe:.3f}\n\n"
        f"Current prompt:\n---\n{current_prompt}\n---\n\n"
        "Return ONLY valid JSON."
    )
    result = llm.call_agent(system, user_msg, agent_name="autoresearch_generator")
    if isinstance(result, dict) and "new_prompt" in result:
        return result
    return None


# ---------------------------------------------------------------------------
# Trial lifecycle
# ---------------------------------------------------------------------------

def start_trial(
    agent_name: str, date: str, day_number: int,
    config: "Config", llm: "LLMClient",
) -> bool:
    from .scorecard import calculate_agent_sharpe, load_scorecard

    state = _load_ar_state(config)
    if state.get("active_trial"):
        return False

    recently = state.get("recently_modified", {})
    if agent_name in recently:
        if day_number - recently[agent_name] < config.autoresearch_window_days:
            return False

    sharpe = calculate_agent_sharpe(agent_name, config, lookback_days=60)
    if sharpe is None:
        return False

    prompt_path = _prompt_path(agent_name, config)
    if not prompt_path:
        logger.error("No prompt file for %s", agent_name)
        return False
    current_prompt = prompt_path.read_text()

    sc = load_scorecard(config)
    recs = [r for r in sc["recommendations"] if r["agent"] == agent_name]
    if len(recs) < config.autoresearch_min_recommendations:
        logger.info("Not enough recs for %s (%s)", agent_name, len(recs))
        return False

    logger.info("Starting autoresearch trial for %s (Sharpe: %.3f)", agent_name, sharpe)

    # Generate modification
    mod = _generate_modification(agent_name, current_prompt, sharpe, llm)
    if not mod or not mod.get("new_prompt"):
        # Mock fallback
        mod = {
            "modification": "mock tweak",
            "new_prompt": current_prompt + f"\n\n<!-- autoresearch: sharpe={sharpe:.3f} -->",
        }

    desc = mod.get("modification", "prompt modification")
    slug = re.sub(r"[^a-z0-9]+", "-", desc.lower())[:40].strip("-")

    try:
        from ..utils.git_ops import create_autoresearch_branch, commit_prompt_modification, get_repo_root
        repo = get_repo_root()
        branch = create_autoresearch_branch(agent_name, slug, repo)
        prompt_path.write_text(mod["new_prompt"])
        commit_prompt_modification(agent_name, desc, repo)

        state["active_trial"] = {
            "agent": agent_name, "branch": branch,
            "start_day": day_number, "start_date": date,
            "pre_sharpe": sharpe, "modification": desc,
        }
        state["recently_modified"][agent_name] = day_number
        _save_ar_state(state, config)
        logger.info("Trial started: %s", branch)
        return True

    except Exception as exc:
        logger.warning("Git autoresearch failed (%s); recording without branch", exc)
        state["active_trial"] = {
            "agent": agent_name, "branch": None,
            "start_day": day_number, "start_date": date,
            "pre_sharpe": sharpe, "modification": desc,
        }
        state["recently_modified"][agent_name] = day_number
        _save_ar_state(state, config)
        return True


def evaluate_trial(date: str, day_number: int, config: "Config") -> Optional[dict]:
    from .scorecard import calculate_agent_sharpe

    state = _load_ar_state(config)
    trial = state.get("active_trial")
    if not trial:
        return None

    elapsed = day_number - trial["start_day"]
    if elapsed < config.autoresearch_window_days:
        return None

    agent = trial["agent"]
    post_sharpe = calculate_agent_sharpe(agent, config, lookback_days=30)
    if post_sharpe is None:
        return None

    pre_sharpe = trial["pre_sharpe"]
    improved = post_sharpe > pre_sharpe
    branch = trial.get("branch")

    logger.info("Autoresearch eval: %s pre=%.3f post=%.3f improved=%s", agent, pre_sharpe, post_sharpe, improved)

    if branch:
        try:
            from ..utils.git_ops import merge_autoresearch_branch, revert_autoresearch_branch
            if improved:
                merge_autoresearch_branch(branch, "main")
            else:
                revert_autoresearch_branch(branch, "main")
        except Exception as exc:
            logger.warning("Git cleanup failed: %s", exc)

    result = {
        "day": day_number, "date": date, "agent": agent,
        "modification": trial.get("modification", ""),
        "pre_sharpe": pre_sharpe, "post_sharpe": post_sharpe,
        "kept": improved,
    }
    log = _load_ar_log(config)
    log.append(result)
    _save_ar_log(log, config)

    state["active_trial"] = None
    _save_ar_state(state, config)
    return result


def maybe_run_autoresearch(
    date: str, day_number: int, config: "Config", llm: "LLMClient",
) -> None:
    """Called each trading day. Evaluate active trial; maybe start new one."""
    result = evaluate_trial(date, day_number, config)
    if result:
        logger.info("Trial complete: %s — %s", result["agent"], "KEPT" if result["kept"] else "REVERTED")

    if day_number % 7 != 0:
        return

    state = _load_ar_state(config)
    if state.get("active_trial"):
        return

    from .scorecard import get_worst_agent
    recently = set(
        a for a, d in state.get("recently_modified", {}).items()
        if day_number - d < config.autoresearch_window_days * 2
    )
    worst = get_worst_agent(config, lookback_days=60, exclude=recently)
    if worst:
        logger.info("Autoresearch candidate: %s", worst)
        start_trial(worst, date, day_number, config, llm)
