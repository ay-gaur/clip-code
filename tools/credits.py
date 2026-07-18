#!/usr/bin/env python3
"""
credits.py — Track cumulative Anthropic API usage across all CLIP calls.

Stores running totals in data/credits.json.
Call track_usage() after every Anthropic API response.
Call get_credits_line() to get a footer string for Telegram messages.
"""

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
CREDITS_FILE = BASE / "data" / "credits.json"

# Pricing per million tokens (USD) — as of April 2026
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-haiku-4-5":          {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5":         {"input": 3.00, "output": 15.00},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
}
DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


def _load() -> dict:
    if CREDITS_FILE.exists():
        try:
            return json.loads(CREDITS_FILE.read_text())
        except Exception:
            pass
    return {"total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0, "calls": 0}


def _save(data: dict) -> None:
    CREDITS_FILE.parent.mkdir(exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    CREDITS_FILE.write_text(json.dumps(data, indent=2))


def track_usage(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Record token usage for one API call. Returns cost of this call in USD.
    Call this after every client.messages.create().
    """
    pricing = PRICING.get(model, DEFAULT_PRICING)
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    CREDITS_FILE.parent.mkdir(exist_ok=True)
    lock_path = CREDITS_FILE.parent / ".credits.lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = _load()
            data["total_cost_usd"] = round(data["total_cost_usd"] + cost, 6)
            data["total_input_tokens"] += input_tokens
            data["total_output_tokens"] += output_tokens
            data["calls"] += 1
            _save(data)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return cost


def get_total_cost() -> float:
    """Return total USD spent so far."""
    return _load().get("total_cost_usd", 0.0)


def get_credits_line() -> str:
    """Return a short footer string for Telegram messages."""
    total = get_total_cost()
    return f"_${total:.4f} used_"
