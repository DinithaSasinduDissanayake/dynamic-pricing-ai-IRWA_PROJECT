from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime, timezone

from backend.deps import get_current_user, get_repo
from core.agents.data_collector.repo import DataRepo

router = APIRouter(prefix="/api/collector", tags=["collector"])


class CollectorRunRequest(BaseModel):
    sku: Optional[str] = None


@router.post("/run")
async def run_collector(
    req: Optional[CollectorRunRequest] = None,
    current_user: dict = Depends(get_current_user),
    repo: DataRepo = Depends(get_repo),
) -> Dict[str, Any]:
    owner_id = str(current_user["user_id"])
    sku = req.sku if req else None

    if sku:
        prod = await repo.get_product_by_sku_and_owner(sku, owner_id)
        prods = [prod] if prod else []
    else:
        prods = await repo.get_products_by_owner(owner_id)

    now_iso = datetime.now(timezone.utc).isoformat()
    collected: List[Dict[str, Any]] = []

    for p in prods:
        item_sku = p["sku"]
        price = float(p.get("current_price") or 100.0)
        tick = {
            "sku": item_sku,
            "market": "DEFAULT",
            "our_price": price,
            "competitor_price": round(price * 0.98, 2),
            "demand_index": 1.02,
            "ts": now_iso,
            "source": "cli_collector_trigger",
        }
        await repo.insert_tick(tick)
        collected.append(tick)

    return {
        "ok": True,
        "sku": sku,
        "count": len(collected),
        "ticks": collected,
    }
