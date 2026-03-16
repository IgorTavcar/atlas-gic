"""FRED (Federal Reserve Economic Data) adapter.

Extracted from artcompany's market_data module.  All functions take
``api_key`` as an explicit parameter.
"""

from typing import Optional

_BASE = "https://api.stlouisfed.org/fred"


def _get(endpoint: str, params: dict, api_key: str) -> Optional[dict]:
    import requests
    params.update({"api_key": api_key, "file_type": "json"})
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def series_latest(series_id: str, api_key: str) -> Optional[float]:
    """Most recent value for a FRED series."""
    data = _get(
        "series/observations",
        {"series_id": series_id, "sort_order": "desc", "limit": 1},
        api_key,
    )
    if data and "observations" in data and data["observations"]:
        try:
            return float(data["observations"][0]["value"])
        except (ValueError, KeyError):
            return None
    return None


def series_range(
    series_id: str, from_date: str, to_date: str, api_key: str
) -> Optional[list]:
    data = _get(
        "series/observations",
        {"series_id": series_id, "observation_start": from_date, "observation_end": to_date},
        api_key,
    )
    if data and "observations" in data:
        return data["observations"]
    return None
