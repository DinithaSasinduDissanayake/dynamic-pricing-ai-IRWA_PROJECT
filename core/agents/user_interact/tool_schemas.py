from typing import Dict, List, Optional

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_inventory_items",
            "description": "List items from the local product catalog (app/data.db:product_catalog). Use for inventory overviews.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter by substring in SKU or title."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_item",
            "description": "Get a single inventory item by SKU from app/data.db:product_catalog.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Item SKU (exact match)"},
                },
                "required": ["sku"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pricing_list",
            "description": "List current market pricing entries from app/data.db:pricing_list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter by substring in product_name."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_price_proposals",
            "description": "List recent price proposals from app/data.db:price_proposals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Optional filter by SKU"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_market_data",
            "description": "List products from data/market.db:market_data (market research data). Use this to find products by brand or name in market data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter by substring in product_name or brand."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_price",
            "description": "Request autonomous price optimization for a product SKU. The Price Optimizer Agent will analyze market data, run pricing algorithms, validate constraints, and publish a price proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Product SKU to optimize pricing for"},
                    "algorithm": {
                        "type": "string",
                        "enum": ["rule_based", "profit_maximization", "volatility_adjusted"],
                        "description": "Pricing optimization algorithm to use. Options: 'rule_based' (default), 'profit_maximization' (elasticity-based), 'volatility_adjusted' (market volatility-aware).",
                    },
                },
                "required": ["sku"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_price_proposal",
            "description": (
                "Apply an approved price proposal to the live product catalog (updates product_catalog.current_price). "
                "TWO-STEP CONFIRMATION FLOW: first call with confirm=false to get a preview (sku, current vs proposed price, "
                "margin, algorithm, rationale) and show it to the user. Only after the user explicitly agrees, call again "
                "with confirm=true to apply. Applying validates ownership, rejects already-applied proposals, re-checks the "
                "12% margin floor against live cost, records an audit row in price_history, and publishes a price.applied event. "
                "Never call with confirm=true without the user's explicit approval of the previewed change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "ID of the price proposal to apply (from list_price_proposals)."},
                    "confirm": {"type": "boolean", "default": False, "description": "false = preview only; true = actually apply (requires prior user approval)."},
                },
                "required": ["proposal_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stale_market_data",
            "description": "Check for market data entries in data/market.db:market_data that are older than a specified threshold. Returns count and details of stale items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold_minutes": {"type": "integer", "description": "Age threshold in minutes. Default is 60.", "default": 60, "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_for_alerts",
            "description": "Scan for and retrieve all pricing alerts and incidents from app/alert.db:incidents. Returns open, acknowledged, and resolved alerts with severity levels and details.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_urgency",
            "description": "Compute portfolio-wide pricing urgency summary across all catalog products. Evaluates margin, competitor gap, market data staleness, pending proposals, and open alerts to return a compact ranked list (most urgent first). Use when asked which products most urgently need attention or price changes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

AGENT_TOOL_MAPPING: Dict[str, str] = {
    "list_inventory_items": "UserInteractionAgent",
    "get_inventory_item": "UserInteractionAgent",
    "list_pricing_list": "PriceOptimizationAgent",
    "list_price_proposals": "PriceOptimizationAgent",
    "list_market_data": "DataCollectorAgent",
    "check_stale_market_data": "DataCollectorAgent",
    "run_pricing_workflow": "PriceOptimizationAgent",
    "optimize_price": "PriceOptimizationAgent",
    "apply_price_proposal": "PriceOptimizationAgent",
    "get_portfolio_urgency": "PriceOptimizationAgent",
    "scan_for_alerts": "AlertNotificationAgent",
    "collect_market_data": "DataCollectorAgent",
    "request_market_fetch": "DataCollectorAgent",
}

def get_agent_for_tool(tool_name: Optional[str]) -> str:
    return AGENT_TOOL_MAPPING.get(tool_name or "", "")
