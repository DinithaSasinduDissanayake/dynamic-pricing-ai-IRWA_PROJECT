import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest
import sqlite3
from core.agents.user_interact.tools import get_portfolio_urgency
from core.agents.user_interact.context import set_owner_id


def test_get_portfolio_urgency_seeded_db():
    set_owner_id("1")
    res = get_portfolio_urgency()
    assert res.get("ok") is True
    items = res.get("ranked_urgency", [])
    assert len(items) > 0
    # Verify fields in each item
    for it in items:
        assert "sku" in it
        assert "margin_pct" in it
        assert "urgency_score" in it
        assert "urgency_level" in it
        assert "reason" in it
    # Check that sorting is descending by urgency_score
    scores = [it["urgency_score"] for it in items]
    assert scores == sorted(scores, reverse=True)
