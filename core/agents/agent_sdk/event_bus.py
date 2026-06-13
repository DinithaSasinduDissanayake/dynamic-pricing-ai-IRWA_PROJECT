"""
Event Bus System for Dynamic Pricing AI

This module provides a lightweight, asynchronous event bus with built-in journaling and validation.
It consolidates previous disparate event handling modules into a single, efficient component.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

# Configure logging
logger = logging.getLogger("event_bus")

# --- Configuration ---
_ROOT = Path(__file__).resolve().parents[3]  # Adjust based on depth: core/agents/agent_sdk/ -> root
_JOURNAL_DIR = _ROOT / "data"
_JOURNAL_FILE = _JOURNAL_DIR / "events.jsonl"

# --- Validation Schemas ---
REQUIRED_KEYS: Dict[str, Iterable[str]] = {
    "price.proposal": ("proposal_id", "product_id", "previous_price", "proposed_price"),
    "price.update": ("proposal_id", "product_id", "final_price"),
    "market.fetch.request": ("request_id", "sku", "market", "sources", "horizon_minutes", "depth"),
    "market.fetch.ack": ("request_id", "job_id", "status"),
    "market.fetch.done": ("request_id", "job_id", "status", "tick_count"),
}

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def validate_payload(topic: str, payload: Mapping) -> Tuple[bool, Optional[str]]:
    """Validate event payload against defined schemas."""
    try:
        req = REQUIRED_KEYS.get(topic)
        if not req:
            return True, None
        missing = [k for k in req if k not in payload]
        if missing:
            return False, f"missing keys: {','.join(missing)}"
        return True, None
    except Exception as e:
        return False, str(e)

def write_event(topic: str, payload: Mapping[str, Any]) -> None:
    """Write event to the journal file (best-effort).

    Optimize: use read-append without fsync to reduce latency.
    """
    try:
        _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _utc_now_iso(),
            "topic": topic,
            "payload": dict(payload),
        }
        # Keep simple append for now - outbox + flusher will ensure durability
        with _JOURNAL_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        # best effort: never raise from journaling
        pass


class EventBus:
    """Asynchronous in-memory event bus."""
    
    def __init__(self):
        self._subs: Dict[str, List[Callable]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Callable):
        """Subscribe a callback to a topic."""
        self._subs[topic].append(callback)

    async def publish(self, topic: str, message: Any):
        """Publish a message to a topic."""
        # Validate
        ok, err = validate_payload(topic, message)
        if not ok:
            logger.warning("invalid_event_payload", topic=topic, error=err, payload=message)
            # We continue anyway, but log the warning
        
        # Journal
        write_event(topic, message)

        # Dispatch
        # Dispatch subscribers concurrently so one slow sink doesn't block others
        tasks = []
        for cb in list(self._subs.get(topic, [])):
            try:
                res = cb(message)
                if asyncio.iscoroutine(res):
                    tasks.append(asyncio.create_task(res))
                else:
                    # Wrap sync callbacks into a threadpool task to avoid blocking
                    loop = asyncio.get_running_loop()
                    tasks.append(loop.run_in_executor(None, lambda cb=cb, m=message: cb(m)))
            except Exception as e:
                logger.error("bus_sink_error", topic=topic, error=str(e), sink=repr(cb))

        if tasks:
            # Fire and forget, but await completion to allow exceptions to be logged
            for t in asyncio.as_completed(tasks):
                try:
                    await t
                except Exception as e:
                    logger.error("bus_sink_error", topic=topic, error=str(e))


# Singleton instance
_BUS: Optional[EventBus] = None

def get_bus() -> EventBus:
    """Get the global event bus instance."""
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS
