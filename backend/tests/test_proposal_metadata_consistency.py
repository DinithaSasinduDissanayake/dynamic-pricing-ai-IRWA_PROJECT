import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest
import sqlite3
import uuid
from core.agents.price_optimizer.tools import Tools
from core.agents.proposal_logger import ProposalLogger
from core.agents.agent_sdk.bus_factory import get_bus
from core.agents.agent_sdk.protocol import Topic


@pytest.mark.asyncio
async def test_proposal_metadata_consistency_from_rationale(tmp_path):
    app_db = tmp_path / "app.db"
    market_db = tmp_path / "market.db"

    # Setup database with price_proposals table
    logger = ProposalLogger(db_path=app_db)
    logger._ensure_table_exists()
    await logger.start()

    tools = Tools(app_db=app_db, market_db=market_db)

    # Publish proposal where top-level algorithm is omitted/default but rationale has profit_maximization
    rationale_data = {
        "sample_count": 5,
        "avg_competitor_price": 1980.0,
        "our_price": 1999.0,
        "cost": 1550.0,
        "margin_floor_pct": 12.0,
        "achieved_margin_pct": 32.0,
        "algorithm": "profit_maximization",
        "confidence": 0.8,
        "rationale_text": "Sampled 5 competitor prices; algorithm profit_maximization chose $2280.45",
    }

    req_id = uuid.uuid4().hex
    pub_res = await tools.publish_price_proposal(
        sku="LAPTOP-001",
        old_price=1999.0,
        new_price=2280.45,
        margin=0.0,  # Default passed in
        algorithm="rule_based",  # Default fallback passed in
        request_id=req_id,
        rationale=rationale_data,
    )
    assert pub_res.get("ok") is True

    # Check that proposal logger correctly recorded profit_maximization and 0.32 margin
    with sqlite3.connect(str(app_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM price_proposals WHERE sku = 'LAPTOP-001'").fetchone()
        assert row is not None
        assert row["algorithm"] == "profit_maximization"
        assert abs(row["margin"] - 0.32) < 1e-4
        assert row["proposed_price"] == 2280.45

    await logger.stop()
