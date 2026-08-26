from typing import Dict, Any
from fastapi import APIRouter, Depends
import os
import time

from backend.deps import get_current_user
from core.agents.llm_client import get_llm_client
from core.agents.agent_sdk.activity_log import get_activity_log

router = APIRouter(prefix="/api/agents", tags=["agents"])
_START_TIME = time.time()


@router.get("/status")
async def get_agents_status(
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    llm = get_llm_client()
    act_log = get_activity_log()
    recent = act_log.recent(limit=10)

    return {
        "ok": True,
        "uptime_sec": int(time.time() - _START_TIME),
        "llm": {
            "available": llm.is_available(),
            "provider": llm.provider(),
            "model": llm.model,
            "mock_mode": os.getenv("MOCK_LLM") == "1",
        },
        "agents": {
            "pricing_optimizer": {
                "status": "active",
                "subscriptions": ["optimization.request", "market.tick"],
            },
            "data_collector": {
                "status": "active",
                "interval_sec": 180,
                "subscriptions": ["market.fetch.request"],
            },
            "proposal_logger": {
                "status": "active",
                "subscriptions": ["price.proposal"],
            },
            "alert_service": {
                "status": "active",
                "subscriptions": ["alert.event", "price.proposal"],
            },
        },
        "recent_activities": recent,
    }
