from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from .tools import Tools, get_llm_tools
from .repo import DataRepo

logger = logging.getLogger("data_collector_agent")

SYSTEM_PROMPT = """You are a proactive Market Intelligence Agent. Your goal is to ensure all products have fresh market data.
Workflow:
1. Call get_stale_products() to find outdated data.
2. Call get_active_jobs() to avoid duplicates.
3. Call start_collection_job() for stale products (max 3-5 concurrent).
"""

class DataCollectorAgent:
    def __init__(self, repo: DataRepo, check_interval_seconds: int = 180):
        self.repo = repo
        self.check_interval_seconds = check_interval_seconds
        self.tools = Tools(repo)
        self.llm = None
        self.logger = logger
        self.running = False
        
        try:
            from core.agents.llm_client import get_llm_client
            self.llm = get_llm_client()
        except Exception as e:
            self.logger.warning(f"Failed to initialize LLM: {e}")

    async def start(self):
        self.running = True
        self.logger.info(f"DataCollectorAgent started (interval={self.check_interval_seconds}s)")
        asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        self.logger.info("DataCollectorAgent stopped")

    async def _loop(self):
        while self.running:
            try:
                if self.llm:
                    await self._run_autonomous_check()
                else:
                    await self._run_heuristic_check()
            except Exception as e:
                self.logger.error(f"Loop error: {e}", exc_info=True)
            await asyncio.sleep(self.check_interval_seconds)

    async def _run_autonomous_check(self):
        self.logger.info("Running autonomous check...")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Check data freshness and start collection jobs if needed."}
        ]
        
        # Map tools directly to agent methods
        functions_map = {
            "get_all_products": self.tools.get_all_products,
            "check_data_freshness": self.tools.check_data_freshness,
            "get_stale_products": self.tools.get_stale_products,
            "start_collection_job": self.tools.start_collection_job,
            "get_active_jobs": self.tools.get_active_jobs,
            "get_recent_jobs": self.tools.get_recent_jobs,
        }
        
        try:
            result = await self.llm.chat_with_tools(
                messages=messages,
                tools=get_llm_tools(),
                functions_map=functions_map,
                max_rounds=5
            )
            self.logger.info(f"Autonomous check result: {result}")
        except Exception as e:
            self.logger.error(f"Autonomous check failed: {e}")

    async def _run_heuristic_check(self):
        self.logger.info("Running heuristic check...")
        stale = await self.tools.get_stale_products(threshold_minutes=60)
        if not stale.get("ok") or not stale.get("stale_products"):
            return

        active = await self.tools.get_active_jobs()
        active_skus = {j["sku"] for j in active.get("active_jobs", [])}
        
        started = 0
        for p in stale["stale_products"][:5]:
            if p["sku"] in active_skus: continue
            
            connector = "web_scraper" if p.get("source_url") else "mock"
            await self.tools.start_collection_job(sku=p["sku"], connector=connector)
            started += 1
            
        self.logger.info(f"Heuristic check started {started} jobs")
