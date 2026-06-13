from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from core.agents.data_collector.repo import DataRepo
from core.agents.price_optimizer.tools import Tools as PriceTools
from core.agents.alert_service.repo import Repo as AlertRepo
from core.agents.agent_sdk.event_bus import get_bus
from core.agents.agent_sdk.protocol import Topic

logger = logging.getLogger("pricing_service")


class PricingService:
    """Consolidated pricing service that merges DataCollector, PriceOptimizer, and AlertService responsibilities into
    a single in-process component. This reduces cross-agent DB writes and simplifies coordination for small deployments.

    Responsibilities:
    - Ingest market data
    - Run optimization and validation
    - Validate proposals and optionally apply or publish updates

    Notes:
    - For now, this module calls into existing tools/repo classes to preserve the current behavior. Over time we may
      migrate logic directly into this module.
    """

    def __init__(self, app_db: Optional[str] = None, market_db: Optional[str] = None) -> None:
        self.app_db = app_db
        self.market_db = market_db
        self.repo = DataRepo(path=self.app_db) if self.app_db else DataRepo()
        self.price_tools = PriceTools(self.repo.path, self.market_db or self.repo.path)
        self.alert_repo = AlertRepo()
        self.bus = get_bus()

    async def start(self) -> None:
        await self.repo.init()
        await self.alert_repo.init()
        # Subscribe to events and wire into internal methods
        self.bus.subscribe(Topic.MARKET_FETCH_DONE.value, self.on_market_fetch_done)
        self.bus.subscribe(Topic.OPTIMIZATION_REQUEST.value, self.on_optimization_request)
        self.bus.subscribe(Topic.PRICE_PROPOSAL.value, self.on_price_proposal)
        logger.info("PricingService started")

    async def stop(self) -> None:
        logger.info("PricingService stopped")

    async def on_market_fetch_done(self, payload: Dict[str, Any]) -> None:
        # For smaller deployments, handle collected data and trigger re-optimization
        sku = payload.get("sku") or payload.get("product_id")
        if sku:
            # When market data completes, optionally evaluate proposals
            logger.info("market_fetch_done", sku=sku)

    async def on_optimization_request(self, payload: Dict[str, Any]) -> None:
        sku = payload.get("sku")
        if not sku:
            return
        logger.info("opt_request", sku=sku)
        res = await self.price_tools.get_product_info(sku)
        if not res.get("ok"):
            return
        p_info = res
        market = await self.price_tools.get_market_intelligence(p_info["title"]) if p_info.get("title") else {}
        algo = "rule_based"
        try:
            out = await self.price_tools.run_pricing_algorithm(algo, sku, p_info.get("current_price") or 0, market.get("competitor_price"), p_info.get("cost"), market.get("market_records", []))
            if out.get("ok"):
                rec = out["recommended_price"]
                valid = await self.price_tools.validate_price(rec, p_info.get("current_price") or 0, p_info.get("cost"))
                if valid.get("valid"):
                    await self.price_tools.publish_price_proposal(sku, p_info.get("current_price") or 0, rec, valid.get("margin") or 0.0, algo)
        except Exception as e:
            logger.error("optimize_error", error=str(e))

    async def on_price_proposal(self, payload: Dict[str, Any]) -> None:
        # Validate and store decisions via alert and auto apply pathways
        # For now, we call AlertService logic by inserting into the alert repo
        try:
            # Keep light logic: insert proposal and let outbox/flusher handle publication
            await self.repo.insert_price_proposal({
                "id": payload.get("proposal_id"),
                "sku": payload.get("sku") or payload.get("product_id"),
                "proposed_price": payload.get("proposed_price") or payload.get("new_price"),
                "current_price": payload.get("current_price") or payload.get("previous_price") or payload.get("old_price"),
                "margin": payload.get("margin"),
                "algorithm": payload.get("algorithm"),
                "ts": str(payload.get("ts")) if payload.get("ts") else None,
            })
        except Exception as e:
            logger.error("on_price_proposal_failed", error=str(e), payload=payload)
