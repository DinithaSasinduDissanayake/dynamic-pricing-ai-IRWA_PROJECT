from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.agents.data_collector.repo import DataRepo
from core.agents.agent_sdk.mcp_client import get_data_collector_client


async def _start_data_collection(
    sku: str, market: str = "DEFAULT", connector: str = "mock", depth: int = 3
) -> Dict[str, Any]:
    client = get_data_collector_client()
    return await client.start_collection(sku, market=market, connector=connector, depth=depth)


async def _get_job_status(job_id: str) -> Dict[str, Any]:
    client = get_data_collector_client()
    return await client.get_job_status(job_id)


async def _optimize_price(sku: str, objective: str = "maximize profit") -> Dict[str, Any]:
    from core.agents.price_optimizer.agent import PricingOptimizerAgent
    optimizer = PricingOptimizerAgent()
    return await optimizer.process_full_workflow(objective, sku)


async def _upsert_product(product_data: Dict[str, Any]) -> Dict[str, Any]:
    from core.agents.user_interact.context import get_owner_id
    owner_id = get_owner_id()
    if not owner_id:
        return {"status": "ignored", "reason": "missing_owner_id"}
    repo = DataRepo()
    await repo.init()
    await repo.upsert_products([product_data], owner_id)
    return {"status": "ok", "sku": product_data.get("sku"), "owner_id": owner_id}


TOOLS: Dict[str, Dict[str, Any]] = {
    "start_data_collection": {
        "fn": _start_data_collection,
        "description": "Start collecting data for a specific SKU and market",
        "schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "market": {"type": "string"},
                "connector": {"type": "string"},
                "depth": {"type": "integer"},
            },
            "required": ["sku"],
        },
    },
    "get_job_status": {
        "fn": _get_job_status,
        "description": "Get the status of a data collection job",
        "schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    "optimize_price": {
        "fn": _optimize_price,
        "description": "Run price optimization for a specific SKU",
        "schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "objective": {"type": "string"},
            },
            "required": ["sku"],
        },
    },
    "upsert_product": {
        "fn": _upsert_product,
        "description": "Insert or update a product in the catalog",
        "schema": {
            "type": "object",
            "properties": {"product_data": {"type": "object"}},
            "required": ["product_data"],
        },
    },
}


class ToolRegistry:
    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": name, "description": t["description"], "schema": t["schema"]}
            for name, t in TOOLS.items()
        ]

    async def execute_tool(self, name: str, **kwargs: Any) -> Any:
        tool = TOOLS.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found")
        return await tool["fn"](**kwargs)


_global_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry