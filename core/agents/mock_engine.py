"""
Deterministic Mock LLM Engine for MOCK_LLM=1 offline testing and CLI pipelines.
Zero network dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional


def extract_prompt_sku(prompt: str) -> Optional[str]:
    # Look for SKUs like LAPTOP-001, PROD-001, ASUS-ROG, etc.
    m = re.search(r'\b([A-Za-z0-9]+-[A-Za-z0-9-]+)\b', prompt)
    if m:
        return m.group(1).upper()
    m2 = re.search(r'\b(PROD\d+|LAPTOP\d+)\b', prompt, re.IGNORECASE)
    if m2:
        return m2.group(1).upper()
    return None


class MockLLMEngine:
    """Handles deterministic chat completions and tool calls for MOCK_LLM=1."""

    @staticmethod
    def handle_chat(messages: List[Dict[str, Any]]) -> str:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        last_lower = last_user.lower()
        # If this is a tool-selection prompt (from LLMBrain)
        if "select" in last_lower or "algorithm" in last_lower or "tool" in last_lower:
            if any(w in last_lower for w in ("maximize", "profit", "greedy")):
                return json.dumps({"tool_name": "profit_maximization", "reason": "Profit maximization requested"})
            elif any(w in last_lower for w in ("volatility", "spread", "range")):
                return json.dumps({"tool_name": "volatility_adjusted", "reason": "Volatility adjusted pricing selected"})
            return json.dumps({"tool_name": "rule_based", "reason": "Deterministic rule-based competitive pricing"})

        # If this is a title generation prompt
        if "title" in last_lower or "summarize" in last_lower:
            sku = extract_prompt_sku(last_user)
            if sku:
                return f"Pricing Optimization for {sku}"
            return "Pricing Discussion"

        # General response
        return f"[Mock LLM] Processed request: {last_user[:50]}"

    @staticmethod
    def handle_chat_with_tools(
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        functions_map: Dict[str, Callable[..., Any]],
        trace_id: Optional[str] = None,
    ) -> tuple[str, List[str]]:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        sku = extract_prompt_sku(last_user)
        last_lower = last_user.lower()
        is_pricing_intent = (
            sku is not None
            or any(w in last_lower for w in ("price", "pricing", "optimize", "proposal", "cost", "catalog", "margin"))
        )

        tools_used: List[str] = []
        if is_pricing_intent:
            target_sku = sku or "LAPTOP-001"
            # 1. If optimize_price available, call it
            if "optimize_price" in functions_map:
                try:
                    res = functions_map["optimize_price"](sku=target_sku)
                    tools_used.append("optimize_price")
                except Exception:
                    pass

            # 2. If list_price_proposals available, call it
            proposals_list = []
            if "list_price_proposals" in functions_map:
                try:
                    p_res = functions_map["list_price_proposals"](sku=target_sku, limit=5)
                    tools_used.append("list_price_proposals")
                    if isinstance(p_res, dict):
                        proposals_list = p_res.get("items", [])
                except Exception:
                    pass

            # Format deterministic response
            if proposals_list:
                latest = proposals_list[0]
                prop_p = float(latest.get("proposed_price") or 0.0)
                curr_p = float(latest.get("current_price") or 0.0)
                algo = latest.get("algorithm", "rule_based")
                p_id = latest.get("id", "prop_1")
                margin = float(latest.get("margin") or 0.0)
                return (
                    f"### Price Optimization for SKU `{target_sku}`\n"
                    f"- **Recommended Price:** ${prop_p:.2f}\n"
                    f"- **Current Price:** ${curr_p:.2f}\n"
                    f"- **Algorithm:** `{algo}`\n"
                    f"- **Margin:** {margin:.1%}\n"
                    f"- **Proposal ID:** `{p_id}`\n\n"
                    f"Proposal generated and stored in SQLite database.",
                    tools_used,
                )
            else:
                return (
                    f"### Price Analysis for SKU `{target_sku}`\n"
                    f"Optimization executed via `optimize_price(sku='{target_sku}')`. Proposal logged.",
                    tools_used,
                )

        return (
            "[Mock LLM] I am the FluxPricer assistant running in offline mock mode. "
            "You can ask me to optimize prices for any SKU in your catalog (e.g. 'Optimize LAPTOP-001').",
            tools_used,
        )
