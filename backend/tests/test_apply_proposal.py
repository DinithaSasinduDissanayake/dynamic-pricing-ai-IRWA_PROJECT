import sys
import sqlite3
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from core.agents.user_interact import tools as ui_tools
from core.agents.user_interact.context import set_owner_id

OWNER = "owner-test-1"
OTHER_OWNER = "owner-test-2"


def _seed_db(db_path: Path, sku="SKU-APPLY-1", current_price=100.0, cost=60.0,
             proposed_price=120.0, owner=OWNER):
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_catalog (
                sku TEXT, title TEXT, currency TEXT, current_price REAL,
                cost REAL, stock INTEGER, updated_at TEXT, owner_id TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_proposals (
                id TEXT PRIMARY KEY, sku TEXT NOT NULL, proposed_price REAL NOT NULL,
                current_price REAL, margin REAL, algorithm TEXT, ts TEXT NOT NULL, rationale TEXT
            )
        """)
        conn.execute(
            "INSERT INTO product_catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sku, "Test Product", "USD", current_price, cost, 10, "2026-01-01T00:00:00Z", owner),
        )
        prop_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO price_proposals (id, sku, proposed_price, current_price, margin, algorithm, ts, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (prop_id, sku, proposed_price, current_price, 0.5, "rule_based",
             "2026-01-02T00:00:00Z", '{"rationale_text": "test rationale"}'),
        )
        conn.commit()
    return prop_id


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db = tmp_path / "data.db"
    real_paths = ui_tools.get_db_paths()
    monkeypatch.setattr(
        ui_tools, "get_db_paths",
        lambda: {"app": db, "market": real_paths["market"], "alert": real_paths["alert"]},
    )
    set_owner_id(OWNER)
    return db


def test_preview_does_not_mutate(temp_db):
    prop_id = _seed_db(temp_db)
    res = ui_tools.apply_price_proposal(prop_id, confirm=False)
    assert res["ok"] is True
    assert res["applied"] is False
    assert res["requires_confirmation"] is True
    assert res["current_price"] == 100.0
    assert res["proposed_price"] == 120.0
    assert res["algorithm"] == "rule_based"
    assert res["rationale"] == "test rationale"
    assert "confirm=true" in res["message"]
    with sqlite3.connect(str(temp_db)) as conn:
        price = conn.execute("SELECT current_price FROM product_catalog").fetchone()[0]
        assert price == 100.0
        applied_at = conn.execute("SELECT applied_at FROM price_proposals WHERE id=?", (prop_id,)).fetchone()[0]
        assert applied_at is None


def test_apply_updates_price_history_and_applied_at(temp_db):
    prop_id = _seed_db(temp_db)
    res = ui_tools.apply_price_proposal(prop_id, confirm=True)
    assert res["ok"] is True, res
    assert res["applied"] is True
    assert res["old_price"] == 100.0
    assert res["new_price"] == 120.0
    with sqlite3.connect(str(temp_db)) as conn:
        conn.row_factory = sqlite3.Row
        price = conn.execute("SELECT current_price FROM product_catalog WHERE sku='SKU-APPLY-1'").fetchone()[0]
        assert price == 120.0
        hist = dict(conn.execute("SELECT * FROM price_history").fetchone())
        assert hist["sku"] == "SKU-APPLY-1"
        assert hist["old_price"] == 100.0
        assert hist["new_price"] == 120.0
        assert hist["proposal_id"] == prop_id
        assert hist["applied_by"] == OWNER
        assert hist["applied_at"]
        applied_at = conn.execute("SELECT applied_at FROM price_proposals WHERE id=?", (prop_id,)).fetchone()[0]
        assert applied_at is not None


def test_apply_refused_for_wrong_owner(temp_db):
    prop_id = _seed_db(temp_db)
    set_owner_id(OTHER_OWNER)
    res = ui_tools.apply_price_proposal(prop_id, confirm=True)
    assert res["ok"] is False
    assert "not found in your inventory" in res["error"]
    with sqlite3.connect(str(temp_db)) as conn:
        price = conn.execute("SELECT current_price FROM product_catalog").fetchone()[0]
        assert price == 100.0


def test_apply_refused_when_already_applied(temp_db):
    prop_id = _seed_db(temp_db)
    first = ui_tools.apply_price_proposal(prop_id, confirm=True)
    assert first["ok"] is True
    second = ui_tools.apply_price_proposal(prop_id, confirm=True)
    assert second["ok"] is False
    assert "already applied" in second["error"].lower()
    with sqlite3.connect(str(temp_db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        assert count == 1


def test_apply_refused_below_margin_floor(temp_db):
    # cost=60, proposed=65 -> margin ~7.7% < 12% floor. Stored margin lies (0.5) — must be rechecked.
    prop_id = _seed_db(temp_db, proposed_price=65.0)
    res = ui_tools.apply_price_proposal(prop_id, confirm=True)
    assert res["ok"] is False
    assert "margin" in res["error"].lower()
    with sqlite3.connect(str(temp_db)) as conn:
        price = conn.execute("SELECT current_price FROM product_catalog").fetchone()[0]
        assert price == 100.0
        applied_at = conn.execute("SELECT applied_at FROM price_proposals WHERE id=?", (prop_id,)).fetchone()[0]
        assert applied_at is None
        count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        assert count == 0


def test_apply_unknown_proposal(temp_db):
    _seed_db(temp_db)
    res = ui_tools.apply_price_proposal("no-such-id", confirm=True)
    assert res["ok"] is False
    assert "not found" in res["error"].lower()
