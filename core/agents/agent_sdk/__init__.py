"""
Agent SDK: lightweight event bus and protocol shared by agents and UI.

Exports:
- Topic: Enum of bus topics
- get_bus(): singleton async event bus instance
"""

from .protocol import Topic
from .event_bus import get_bus

__all__ = ["Topic", "get_bus"]
