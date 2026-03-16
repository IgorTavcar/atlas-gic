"""LLM client with Anthropic backend and mock fallback.

Merges josjo80's LLMClient class with artcompany's call_agent() retry/backoff
and JSON extraction logic.  When no ANTHROPIC_API_KEY is set (or the package
is missing) every call returns a plausible mock response.
"""

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)

_SCORE_MODEL = "claude-haiku-4-5-20251001"
_REASON_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS_SCORE = 16
_MAX_TOKENS_REASON = 1024


# ---------------------------------------------------------------------------
# JSON extraction (artcompany)
# ---------------------------------------------------------------------------

def _parse_json_response(content: str, label: str = "") -> dict:
    """Best-effort JSON extraction from an LLM response."""
    # Direct parse
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass
    # ```json … ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # First { … }
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    logger.error("[%s] Could not parse JSON: %s…", label, content[:200])
    return {}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_MOCK_MACRO = {
    "regime": "NEUTRAL", "conviction": 50,
    "primary_driver": "mock mode — no API key",
    "top_long_theme": "N/A", "top_short_theme": "N/A",
    "key_risk": "N/A",
}

_MOCK_SECTOR = {
    "sector_regime": "NEUTRAL",
    "top_long": {"ticker": "SPY", "conviction": 50, "thesis": "mock", "target": "N/A"},
    "top_short": {"ticker": "SPY", "conviction": 50, "thesis": "mock", "target": "N/A"},
    "sector_risk": "mock mode",
}

_MOCK_SUPERINVESTOR = {
    "portfolio_verdicts": [],
    "missing_name": {"ticker": "SPY", "thesis": "mock", "conviction": 50, "direction": "LONG"},
    "overall_view": "mock mode",
}

_MOCK_DECISION = {
    "market_view": "mock mode",
    "macro_regime": "NEUTRAL",
    "actions": [],
    "risk_commentary": "mock mode",
    "conviction": 50,
}


def _mock_for_layer(layer_type: str) -> dict:
    return {
        "macro": _MOCK_MACRO,
        "sector": _MOCK_SECTOR,
        "superinvestor": _MOCK_SUPERINVESTOR,
        "decision": _MOCK_DECISION,
    }.get(layer_type, _MOCK_MACRO).copy()


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient:
    """Thin wrapper around Anthropic messages API with mock fallback."""

    def __init__(self, api_key: str = "", config: "Config | None" = None) -> None:
        self._api_key = api_key
        self._client = None
        self._config = config
        if api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=api_key)
                logger.debug("LLMClient: using Anthropic backend")
            except ImportError:
                logger.warning("anthropic package not installed; falling back to mock LLM")

    @property
    def is_real(self) -> bool:
        return self._client is not None

    # -- low-level ----------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        model = model or (self._config.llm_model if self._config else _REASON_MODEL)
        max_tokens = max_tokens or (self._config.llm_max_tokens if self._config else _MAX_TOKENS_REASON)

        if not self._client:
            return f'{{"mock": true, "prompt_snippet": "{prompt[:60]}"}}'

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        if self._config:
            kwargs["temperature"] = self._config.llm_temperature

        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text.strip()

    # -- agent call with retry (artcompany) ---------------------------------

    def call_agent(
        self,
        system_prompt: str,
        user_message: str,
        agent_name: str = "unknown",
        max_retries: int = 3,
        expect_json: bool = True,
    ) -> dict | str:
        """Call an ATLAS agent.  Retries on rate-limit / transient errors."""
        if not self._client:
            from ..config import AGENT_DEFINITIONS
            layer_type = AGENT_DEFINITIONS.get(agent_name, {}).get("type", "macro")
            return _mock_for_layer(layer_type)

        import anthropic as _anthropic
        model = self._config.llm_model if self._config else _REASON_MODEL
        max_tokens = self._config.llm_max_tokens if self._config else _MAX_TOKENS_REASON
        temperature = self._config.llm_temperature if self._config else 0.3
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                content = resp.content[0].text
                if not expect_json:
                    return content
                return _parse_json_response(content, agent_name)

            except _anthropic.RateLimitError as exc:
                wait = 2 ** attempt * 5
                logger.warning("[%s] Rate limit, waiting %ss (attempt %s)", agent_name, wait, attempt + 1)
                time.sleep(wait)
                last_error = exc
            except _anthropic.APIError as exc:
                wait = 2 ** attempt * 2
                logger.warning("[%s] API error: %s, retrying in %ss", agent_name, exc, wait)
                time.sleep(wait)
                last_error = exc
            except json.JSONDecodeError as exc:
                logger.error("[%s] JSON parse error: %s", agent_name, exc)
                last_error = exc
                break

        logger.error("[%s] All %s attempts failed: %s", agent_name, max_retries, last_error)
        return {}

    # -- scoring (josjo80) --------------------------------------------------

    def score_agent(self, agent: str, ticker: str, snapshot: dict) -> float:
        daily_return = snapshot.get("returns", {}).get(ticker, 0.0)
        if not self._client:
            return round(daily_return * 100, 3)

        price = snapshot.get("prices", {}).get(ticker, float("nan"))
        prompt = (
            f"You are scoring the '{agent}' trading agent on {ticker}.\n"
            f"Current price: ${price:.2f} | Today's return: {daily_return:+.2%} | "
            f"Data source: {snapshot.get('source', 'unknown')}.\n"
            "Respond with a single integer from -100 to 100."
        )
        try:
            raw = self.generate(prompt, model=_SCORE_MODEL, max_tokens=_MAX_TOKENS_SCORE)
            m = re.search(r"-?\d+", raw)
            if m:
                return float(max(-100, min(100, int(m.group()))))
        except Exception as exc:
            logger.warning("score_agent failed (%s); using mock", exc)
        return round(daily_return * 100, 3)

    # -- prompt improvement (josjo80 + artcompany) --------------------------

    def improve_prompt(self, agent: str, sharpe: float, current_prompt: str) -> str:
        if not self._client:
            return current_prompt + f"\n\n<!-- autoresearch mock tweak: sharpe was {sharpe:.3f} -->"

        prompt = (
            f"You are improving the prompt for the '{agent}' trading agent.\n"
            f"Current rolling Sharpe: {sharpe:.3f} (lowest performing).\n\n"
            f"Current prompt:\n---\n{current_prompt}\n---\n\n"
            "Suggest ONE specific, concrete modification. "
            "Respond with the complete updated prompt text only."
        )
        try:
            return self.generate(prompt, model=_REASON_MODEL, max_tokens=_MAX_TOKENS_REASON)
        except Exception as exc:
            logger.warning("improve_prompt failed (%s); mock tweak", exc)
            return current_prompt + f"\n\n<!-- autoresearch mock tweak: sharpe was {sharpe:.3f} -->"


def make_llm_client(config: "Config") -> LLMClient:
    return LLMClient(api_key=config.anthropic_api_key, config=config)
