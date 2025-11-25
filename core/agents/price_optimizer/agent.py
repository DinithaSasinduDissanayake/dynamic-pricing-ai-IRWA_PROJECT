from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd
import structlog

from .optimizer import Features, optimize
from .algorithms import ALGORITHMS
from .tools import Tools, get_llm_tools

logger = structlog.get_logger("price_optimizer")

SYSTEM_PROMPT = """You are an autonomous Pricing Optimization Agent.
Workflow:
1. get_product_info(sku)
2. check_market_data_freshness(sku) -> if stale, start_market_data_collection(sku)
3. get_market_intelligence(product_title)
4. run_pricing_algorithm(...)
5. validate_price(...)
6. publish_price_proposal(...)
You MUST publish a proposal to complete the task."""

class PricingOptimizerAgent:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.llm = None
        try:
            from core.agents.llm_client import get_llm_client
            self.llm = get_llm_client(model=model)
        except Exception as e:
            logger.warning("llm_init_failed", error=str(e))

        from core.settings import get_settings
        from core.agents.agent_sdk.mcp_client import get_price_optimizer_client
        
        self.app_db = get_settings().resolve_app_db()
        self.market_db = get_settings().resolve_market_db()
        
        # Use local tools directly for simplicity in this refactor
        self.tools = get_price_optimizer_client(use_mcp=False, app_db=str(self.app_db), market_db=str(self.market_db))

        # Event bus
        self.bus = None
        try:
            from core.agents.agent_sdk.event_bus import get_bus
            self.bus = get_bus()
        except Exception:
            pass

    async def start(self):
        if self.bus:
            from core.agents.agent_sdk.protocol import Topic
            self.bus.subscribe(Topic.OPTIMIZATION_REQUEST.value, self.on_optimization_request)
            logger.info("agent_started", mode="autonomous" if self.llm else "heuristic")

    async def on_optimization_request(self, request: Any):
        req = request if isinstance(request, dict) else request.__dict__
        product = req.get("product_name") or req.get("sku") or req.get("product_id")
        user_req = req.get("user_request", "Optimize price")
        
        if not product:
            logger.error("request_missing_product", request=req)
            return

        logger.info("optimization_request", product=product, request=user_req)
        
        if self.llm:
            await self._run_autonomous(product, user_req)
        else:
            await self._run_heuristic(product, user_req)

    async def _run_autonomous(self, product: str, user_req: str):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Optimize price for {product}. Request: {user_req}"}
        ]
        
        functions_map = {
            "get_product_info": self.tools.get_product_info,
            "get_market_intelligence": self.tools.get_market_intelligence,
            "run_pricing_algorithm": self.tools.run_pricing_algorithm,
            "validate_price": self.tools.validate_price,
            "publish_price_proposal": self.tools.publish_price_proposal,
            "check_market_data_freshness": self.tools.check_market_data_freshness,
            "start_market_data_collection": self.tools.start_market_data_collection
        }
        
        try:
            await self.llm.chat_with_tools(
                messages=messages,
                tools=get_llm_tools(),
                functions_map=functions_map,
                max_rounds=10
            )
        except Exception as e:
            logger.error("autonomous_run_failed", error=str(e))
            await self._run_heuristic(product, user_req)

    async def _run_heuristic(self, product: str, user_req: str):
        # Simplified heuristic workflow
        p_info = await self.tools.get_product_info(product)
        if not p_info.get("ok"):
            logger.error("product_not_found", product=product)
            return

        sku = p_info["sku"]
        current_price = p_info["current_price"]
        
        market = await self.tools.get_market_intelligence(p_info["title"])
        
        # Simple logic: if competitor is lower, match them (with margin check)
        algo = "rule_based"
        if "maximize" in user_req.lower():
            algo = "profit_maximization"
            
        res = await self.tools.run_pricing_algorithm(
            algorithm=algo,
            sku=sku,
            our_price=current_price,
            competitor_price=market.get("competitor_price"),
            cost=p_info.get("cost"),
            market_records=market.get("market_records"),
            min_margin=0.12
        )
        
        if res.get("ok"):
            new_price = res["recommended_price"]
            val = await self.tools.validate_price(new_price, current_price, p_info.get("cost"))
            
            if val.get("valid"):
                await self.tools.publish_price_proposal(
                    sku=sku,
                    old_price=current_price,
                    new_price=new_price,
                    algorithm=algo
                )
                logger.info("proposal_published", sku=sku, price=new_price)
            else:
                logger.warning("proposal_rejected", reason=val.get("error"))
