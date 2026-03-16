"""Structured logging for ATLAS.

JSON file handler + human-readable console.  Accepts a ``log_dir`` parameter
so callers can point to the Config.log_dir without importing config directly.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def get_logger(name: Optional[str] = None, log_dir: Optional[Path] = None) -> logging.Logger:
    """Return a logger with console + optional JSON file handlers."""
    logger = logging.getLogger(name or "atlas")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console (human-readable)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    )
    logger.addHandler(console)

    # File (JSON) — only if log_dir provided
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "atlas.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(JSONFormatter())
        logger.addHandler(fh)

    logger.propagate = False
    return logger


def log_agent_output(
    agent_name: str, date: str, output: dict, log_dir: Optional[Path] = None
) -> None:
    """Append one agent's output to a daily JSONL file."""
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"agents_{date}.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps({"agent": agent_name, "date": date, "output": output}) + "\n")
