"""Configuration loaded from environment / .env file.

Combines josjo80's dataclass pattern with artcompany's 25 agent definitions
and Darwinian weights.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


_load_dotenv()


@dataclass
class Config:
    # API keys
    anthropic_api_key: str = ""
    fmp_api_key: str = ""
    finnhub_api_key: str = ""
    fred_api_key: str = ""

    # Portfolio settings
    starting_capital: float = 1_000_000.0
    max_position_size_pct: float = 0.15
    max_gross_exposure: float = 1.5
    max_net_exposure: float = 0.8

    # Autoresearch settings
    autoresearch_window_days: int = 5
    autoresearch_min_recommendations: int = 10
    darwinian_weight_ceiling: float = 2.5
    darwinian_weight_floor: float = 0.3
    darwinian_reward_multiplier: float = 1.05
    darwinian_penalty_multiplier: float = 0.95

    # LLM settings
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3

    # Paths (derived, not from env)
    data_dir: Path = field(default_factory=lambda: Path("data"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            fmp_api_key=os.getenv("FMP_API_KEY", ""),
            finnhub_api_key=os.getenv("FINNHUB_API_KEY", ""),
            fred_api_key=os.getenv("FRED_API_KEY", ""),
            starting_capital=float(os.getenv("STARTING_CAPITAL", "1000000")),
            max_position_size_pct=float(os.getenv("MAX_POSITION_SIZE_PCT", "0.15")),
            max_gross_exposure=float(os.getenv("MAX_GROSS_EXPOSURE", "1.5")),
            max_net_exposure=float(os.getenv("MAX_NET_EXPOSURE", "0.8")),
            autoresearch_window_days=int(os.getenv("AUTORESEARCH_WINDOW_DAYS", "5")),
            autoresearch_min_recommendations=int(os.getenv("AUTORESEARCH_MIN_RECOMMENDATIONS", "10")),
            darwinian_weight_ceiling=float(os.getenv("DARWINIAN_WEIGHT_CEILING", "2.5")),
            darwinian_weight_floor=float(os.getenv("DARWINIAN_WEIGHT_FLOOR", "0.3")),
            darwinian_reward_multiplier=float(os.getenv("DARWINIAN_REWARD_MULTIPLIER", "1.05")),
            darwinian_penalty_multiplier=float(os.getenv("DARWINIAN_PENALTY_MULTIPLIER", "0.95")),
            llm_model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            log_dir=Path(os.getenv("LOG_DIR", "logs")),
        )

    @property
    def has_market_data(self) -> bool:
        return bool(self.fmp_api_key or self.finnhub_api_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def prompts_dir(self) -> Path:
        """Prompt .md files shipped inside the package."""
        return Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Agent definitions: 25 agents across 4 layers
# ---------------------------------------------------------------------------

AGENT_DEFINITIONS: Dict[str, dict] = {
    # Layer 1 — Macro
    "central_bank":        {"layer": 1, "type": "macro"},
    "geopolitical":        {"layer": 1, "type": "macro"},
    "china":               {"layer": 1, "type": "macro"},
    "dollar":              {"layer": 1, "type": "macro"},
    "yield_curve":         {"layer": 1, "type": "macro"},
    "commodities":         {"layer": 1, "type": "macro"},
    "volatility":          {"layer": 1, "type": "macro"},
    "emerging_markets":    {"layer": 1, "type": "macro"},
    "news_sentiment":      {"layer": 1, "type": "macro"},
    "institutional_flow":  {"layer": 1, "type": "macro"},
    # Layer 2 — Sector
    "semiconductor":       {"layer": 2, "type": "sector"},
    "energy":              {"layer": 2, "type": "sector"},
    "biotech":             {"layer": 2, "type": "sector"},
    "consumer":            {"layer": 2, "type": "sector"},
    "industrials":         {"layer": 2, "type": "sector"},
    "financials":          {"layer": 2, "type": "sector"},
    "relationship_mapper": {"layer": 2, "type": "sector"},
    # Layer 3 — Superinvestors
    "druckenmiller":       {"layer": 3, "type": "superinvestor"},
    "aschenbrenner":       {"layer": 3, "type": "superinvestor"},
    "baker":               {"layer": 3, "type": "superinvestor"},
    "ackman":              {"layer": 3, "type": "superinvestor"},
    # Layer 4 — Decision
    "cro":                 {"layer": 4, "type": "decision"},
    "alpha_discovery":     {"layer": 4, "type": "decision"},
    "autonomous_execution": {"layer": 4, "type": "decision"},
    "cio":                 {"layer": 4, "type": "decision"},
}

LAYER1_AGENTS = [k for k, v in AGENT_DEFINITIONS.items() if v["layer"] == 1]
LAYER2_AGENTS = [k for k, v in AGENT_DEFINITIONS.items() if v["layer"] == 2]
LAYER3_AGENTS = [k for k, v in AGENT_DEFINITIONS.items() if v["layer"] == 3]
LAYER4_AGENTS = [k for k, v in AGENT_DEFINITIONS.items() if v["layer"] == 4]
ALL_AGENTS = list(AGENT_DEFINITIONS.keys())

# Default Darwinian weights (from 378-day backtest final state)
DEFAULT_DARWINIAN_WEIGHTS: Dict[str, float] = {
    "central_bank": 0.3,
    "geopolitical": 2.5,
    "china": 1.36,
    "dollar": 0.44,
    "yield_curve": 1.13,
    "commodities": 2.5,
    "volatility": 2.5,
    "emerging_markets": 0.35,
    "news_sentiment": 1.55,
    "institutional_flow": 0.3,
    "semiconductor": 0.3,
    "energy": 2.5,
    "biotech": 0.36,
    "consumer": 1.92,
    "industrials": 2.5,
    "financials": 0.47,
    "relationship_mapper": 1.0,
    "druckenmiller": 0.55,
    "aschenbrenner": 2.5,
    "baker": 0.46,
    "ackman": 2.5,
    "cro": 1.0,
    "alpha_discovery": 1.82,
    "autonomous_execution": 1.0,
    "cio": 0.3,
}
