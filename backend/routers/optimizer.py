from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel
import asyncio

from backend.deps import get_current_user
from core.agents.user_interact.context import set_owner_id
from core.agents.user_interact.tools import optimize_price, list_price_proposals

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


class OptimizerRunRequest(BaseModel):
    sku: str
    algorithm: Optional[str] = None


@router.post("/run")
async def run_optimizer(
    req: OptimizerRunRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    owner_id = str(current_user["user_id"])
    set_owner_id(owner_id)

    res = optimize_price(req.sku, algorithm=req.algorithm)
    if not res.get("ok"):
        return {"ok": False, "sku": req.sku, "error": res.get("error") or res.get("message")}

    latest_proposal = None
    for _ in range(6):
        await asyncio.sleep(0.25)
        p_res = list_price_proposals(req.sku, limit=1)
        if isinstance(p_res, dict) and p_res.get("items"):
            latest_proposal = p_res["items"][0]
            break

    return {
        "ok": True,
        "sku": req.sku,
        "algorithm": req.algorithm or (latest_proposal.get("algorithm") if latest_proposal else "auto"),
        "proposal": latest_proposal,
        "message": res.get("message"),
    }
