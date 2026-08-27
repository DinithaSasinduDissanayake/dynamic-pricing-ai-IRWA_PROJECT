"""OpenAI-compatible tool specs GENERATED from the Pydantic models in tool_models.py.

The models are the single source of truth: descriptions live on the model
docstrings and Field(description=...), and the JSON schema handed to
/v1/chat/completions is derived via model_json_schema() with strict-mode
post-processing (additionalProperties: false, every property required and
nullable when optional, no defaults/titles). ``TOOL_SCHEMAS`` keeps its
historical name and shape so all consumers keep working.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from .tool_models import TOOL_MODELS

# Tools advertised to the LLM. Legacy aliases in TOOLS_MAP/TOOL_MODELS
# (list_inventory, run_pricing_workflow, ...) stay dispatchable but hidden.
EXPOSED_TOOLS: List[str] = [
    "list_inventory_items",
    "get_inventory_item",
    "list_pricing_list",
    "list_price_proposals",
    "list_market_data",
    "optimize_price",
    "apply_price_proposal",
    "check_stale_market_data",
    "scan_for_alerts",
    "get_portfolio_urgency",
]

_STRIP_KEYS = ("title", "default")


def _strip_keys(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_keys(v) for k, v in node.items() if k not in _STRIP_KEYS}
    if isinstance(node, list):
        return [_strip_keys(v) for v in node]
    return node


def build_strict_parameters(model: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model's JSON schema into an OpenAI strict-mode
    parameters object: additionalProperties false, all properties listed in
    ``required`` (optional ones are already nullable via anyOf from the
    ``... | None`` annotations), no default/title noise, no $refs."""
    schema = copy.deepcopy(model.model_json_schema())
    props = _strip_keys(schema.get("properties") or {})
    return {
        "type": "object",
        "properties": props,
        "required": list(props.keys()),
        "additionalProperties": False,
    }


def build_tool_spec(name: str, model: Type[BaseModel]) -> Dict[str, Any]:
    description = " ".join((model.__doc__ or name).split())
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": build_strict_parameters(model),
            "strict": True,
        },
    }


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    build_tool_spec(name, TOOL_MODELS[name]) for name in EXPOSED_TOOLS
]


def strip_strict(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a copy of the tool specs without strict-mode flags, for
    providers that reject ``strict`` (capability degradation, not failure)."""
    degraded = copy.deepcopy(tools)
    for t in degraded:
        fn = t.get("function")
        if isinstance(fn, dict):
            fn.pop("strict", None)
    return degraded


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
